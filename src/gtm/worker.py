"""Receipt-first dispatch. Attempts survive process loss; permissions govern only NEW writes."""
import json
from datetime import timedelta

import httpx

from .contracts import Action, DomainError, loopback_url, moment, stamp
from .store import digest


class EngagementClient:
    def __init__(self, url, token):
        self.url = loopback_url(url)
        self.headers = {"Authorization": "Bearer " + token}

    def receipts(self):
        response = httpx.get(self.url + "/receipts", headers=self.headers, timeout=5, follow_redirects=False)
        response.raise_for_status()
        return response.json()

    def receipt(self, key):
        response = httpx.get(self.url + "/receipts/" + key, headers=self.headers, timeout=5, follow_redirects=False)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def enroll(self, payload, at):
        return httpx.post(self.url + "/enrollments", headers=self.headers,
                          json={"payload": payload, "payload_hash": digest(payload), "at": at},
                          timeout=5, follow_redirects=False)

    def emit_feedback(self, record):
        response = httpx.post(self.url + "/feedback", headers=self.headers, json=record, timeout=5,
                              follow_redirects=False)
        response.raise_for_status()
        # Independent HTTP read-back, not the submitted object echoed locally.
        response = httpx.get(self.url + "/feedback", headers=self.headers, timeout=5, follow_redirects=False)
        response.raise_for_status()
        return next(x for x in response.json() if x["source_id"] == record["source_id"]
                    and x["brand"] == record["brand"] and x["source"] == record["source"])


def bound_approval(db, action):
    payload = Action.model_validate(json.loads(action["payload"])).model_dump()
    if digest(payload) != action["payload_hash"] or payload["action_key"] != action["action_key"]:
        raise DomainError("approval_content_tampered")
    rows = db.execute("SELECT detail FROM audit WHERE event='exact_approval' AND subject=?",
                      (action["action_key"],)).fetchall()
    if not any(json.loads(x[0]).get("payload_hash") == action["payload_hash"] for x in rows):
        raise DomainError("approval_audit_missing")
    return payload


def verify_receipt(action, receipt):
    if not isinstance(receipt, dict) or set(receipt) != {"action_key", "payload_hash", "payload", "accepted_at", "receipt_id"}:
        raise DomainError("receipt_schema_invalid")
    if (receipt.get("action_key") != action["action_key"] or receipt.get("payload_hash") != action["payload_hash"]
            or digest(receipt.get("payload")) != action["payload_hash"]
            or receipt.get("payload") != json.loads(action["payload"])):
        raise DomainError("receipt_content_mismatch")
    if not isinstance(receipt["accepted_at"], str):
        raise DomainError("receipt_timestamp_invalid")
    moment(receipt["accepted_at"])
    if receipt.get("receipt_id") != "rcpt_" + action["payload_hash"][:24]:
        raise DomainError("receipt_identity_mismatch")


def reconcile(engine, client):
    receipts = client.receipts()
    if not isinstance(receipts, list) or any(not isinstance(r, dict) for r in receipts):
        raise DomainError("receipt_inventory_schema_invalid")
    local = {x["action_key"]: x for x in engine.rows("actions")}
    discrepancies = []
    if not engine.audit_valid():
        discrepancies.append({"action_key": None, "reason": "local_audit_integrity_failed"})
    seen = set()
    for receipt in receipts:
        key = receipt.get("action_key")
        if key in seen:
            discrepancies.append({"action_key": key, "reason": "duplicate_remote_receipt"})
        seen.add(key)
        if key not in local:
            discrepancies.append({"action_key": key, "reason": "remote_ahead_missing_intent"})
            continue
        try:
            with engine.connection() as db:
                bound_approval(db, local[key])
            verify_receipt(local[key], receipt)
        except (ValueError, KeyError):
            discrepancies.append({"action_key": key, "reason": "receipt_content_mismatch"})
    for key, action in local.items():
        if action["receipt"] and key not in seen:
            discrepancies.append({"action_key": key, "reason": "remote_receipt_missing"})
    return {"safe_to_resume": not discrepancies, "remote_effects": len(receipts), "discrepancies": discrepancies}


class Worker:
    def __init__(self, engine, client):
        self.engine, self.client = engine, client

    def dispatch(self, key, now):
        now = stamp(moment(now))
        engine = self.engine
        # Fresh independent inventory is a recovery gate, not a locally cached flag.
        try:
            recovery = reconcile(engine, self.client)
        except (httpx.HTTPError, ValueError):
            return self._record(key, now, "uncertain", "receipt_inventory_unavailable")
        if not recovery["safe_to_resume"]:
            return self._record(key, now, "blocked", "recovery_reconciliation_failed")
        with engine.connection() as db:
            found = db.execute("SELECT * FROM actions WHERE action_key=?", (key,)).fetchone()
            if not found:
                raise DomainError("approval_required")
            action = dict(found)
            bound_approval(db, action)
        try:
            receipt = self.client.receipt(key)
        except (httpx.HTTPError, ValueError):
            return self._record(key, now, "uncertain", "receipt_lookup_unavailable")
        if receipt:
            verify_receipt(action, receipt)
            return self._record(key, now, "reconciled", None, receipt)
        if action["attempts"] >= engine.policy["max_attempts"]:
            return self._record(key, now, "exhausted", "write_budget_exhausted")
        if action["status"] == "blocked":
            return {"status": "blocked", "reason": action["last_error"]}
        if action["next_attempt"] and now < action["next_attempt"]:
            return {"status": "waiting", "next_attempt": action["next_attempt"]}
        with engine.transaction() as db:
            # Reserve the attempt durably BEFORE the network call; no worker-death reset.
            current = db.execute("SELECT * FROM actions WHERE action_key=?", (key,)).fetchone()
            if current["attempts"] != action["attempts"] or current["receipt"]:
                return {"status": "busy"}
            db.execute("UPDATE actions SET attempts=attempts+1,status='uncertain' WHERE action_key=?", (key,))
            engine.audit(db, now, "attempt_reserved", key, {"attempt": action["attempts"] + 1})
        try:
            # Hold admission lock across the bounded request; local consent/owner cannot race it.
            # Source-system changes not yet received remain an explicit integration limitation.
            with engine.transaction() as db:
                current = dict(db.execute("SELECT * FROM actions WHERE action_key=?", (key,)).fetchone())
                payload = engine.authorize(db, current, now)
                response = self.client.enroll(payload, now)
                if response.status_code == 429:
                    state, error = "waiting", "downstream_rate_limited"
                elif response.status_code in {401, 403, 409, 422}:
                    state, error = "blocked", f"downstream_rejected_{response.status_code}"
                elif response.status_code != 200:
                    state, error = "uncertain", "downstream_outcome_unknown"
                else:
                    state, error = "uncertain", "readback_required"
                due = stamp(moment(now) + timedelta(seconds=2 ** current["attempts"]))
                db.execute("UPDATE actions SET status=?,last_error=?,next_attempt=? WHERE action_key=?",
                           (state, error, due, key))
                engine.audit(db, now, "dispatch_response", key, {"status": state, "reason": error})
        except DomainError as error:
            return self._record(key, now, "blocked", str(error))
        except httpx.HTTPError:
            return self._record(key, now, "uncertain", "acknowledgement_lost")
        # A status code never establishes success: independently GET and compare the entire content.
        try:
            receipt = self.client.receipt(key)
            if receipt:
                verify_receipt(action, receipt)
                return self._record(key, now, "delivered", None, receipt)
        except (httpx.HTTPError, ValueError):
            return self._record(key, now, "uncertain", "readback_unavailable_or_mismatched")
        return {"status": state, "reason": error}

    def _record(self, key, now, status, error, receipt=None):
        from .store import canonical
        with self.engine.transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_key=?", (key,)).fetchone()
            if not row:
                raise DomainError("approval_required")
            db.execute("UPDATE actions SET status=?,last_error=?,receipt=coalesce(?,receipt) WHERE action_key=?",
                       (status, error, canonical(receipt) if receipt else None, key))
            self.engine.audit(db, now, "delivery_observation", key, {"status": status, "reason": error,
                              "receipt_id": receipt.get("receipt_id") if receipt else None})
        return {"status": status, "reason": error, "receipt": receipt}
