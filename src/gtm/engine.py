"""Account qualification, routing and exact approval. No downstream credentials enter advice."""
import json
from datetime import timedelta
from pathlib import Path

from .contracts import Action, DomainError, Record, moment, stamp
from .store import Store, canonical, digest

DATA_FIELDS = {
    "account": {"name", "employees", "industry", "territory", "lifecycle", "owner"},
    "contact": {"email", "consent"}, "intent": {"signal"},
    "inbound": {"email", "request", "consent"}, "consent": {"allowed"}, "owner": {"owner"},
    "outcome": {"kind", "business_id", "parent_id", "action_key", "origin", "amount_cents", "created_at"},
}
SOURCES = {"account": {"crm", "enrichment"}, "contact": {"crm"}, "owner": {"crm"},
           "consent": {"crm", "web"}, "intent": {"web", "enrichment"},
           "inbound": {"web"}, "outcome": {"crm", "engagement"}}


class Engine(Store):
    def __init__(self, path, policy=None):
        super().__init__(path)
        self.policy = policy or json.loads(Path(__file__).with_name("policy.json").read_text())
        self.policy_hash = digest(self.policy)

    def account(self, db, account_id):
        row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise DomainError("account_not_found")
        return dict(row)

    def _match(self, db, record):
        if record.account_id:
            row = self.account(db, record.account_id)
            if row["brand"] != record.brand or row["domain"] != record.domain:
                raise DomainError("brand_or_domain_mismatch")
            return row["id"], "verified_reference"
        rows = db.execute("SELECT id FROM accounts WHERE brand=? AND domain=?",
                          (record.brand, record.domain)).fetchall()
        if len(rows) > 1:
            return None, "ambiguous_identity"
        return (rows[0][0], "unique_brand_domain") if rows else (None, "unmatched_identity")

    def ingest(self, data, now):
        r = Record.model_validate(data)
        now = stamp(moment(now))
        if moment(r.observed_at) > moment(now):
            raise DomainError("future_observation")
        if set(r.data) - DATA_FIELDS[r.kind] or r.source not in SOURCES[r.kind]:
            raise DomainError("schema_drift_or_source_authority")
        if len(canonical(r.data)) > 12000:
            raise DomainError("source_too_large")
        if any(type(value) not in {str, int, bool, type(None)} for value in r.data.values()):
            raise DomainError("scalar_source_fields_required")
        key = f"{r.source}:{r.brand}:{r.source_id}"
        body = r.model_dump()
        fingerprint = digest(body)
        with self.transaction() as db:
            prior = db.execute("SELECT * FROM sources WHERE source_key=?", (key,)).fetchone()
            if prior:
                if prior["payload_hash"] != fingerprint:
                    raise DomainError("source_key_content_collision")
                return {"source_key": key, "account_id": prior["account_id"],
                        "status": "duplicate", "reason": prior["reason"]}
            account_id, reason = self._match(db, r)
            status = "accepted"
            # A CRM reference can create an explicit second account with the same domain.
            if r.kind == "account" and r.source == "crm" and r.data.get("name") and not r.account_id:
                # Distinct trusted CRM record IDs do NOT silently collapse just because domains match.
                candidate = self.account(db, account_id) if account_id else None
                if not candidate or candidate["lifecycle"] != "unverified":
                    account_id = "acc_" + digest([r.brand, r.domain, r.source_id])[:16]
            elif r.kind == "account" and not account_id and reason == "unmatched_identity":
                account_id = "acc_" + digest([r.brand, r.domain])[:16]
            if not account_id:
                status = "quarantined"
            else:
                if r.kind == "account":
                    self._account_input(db, r, account_id, key)
                else:
                    account = self.account(db, account_id)
                    if r.kind == "contact":
                        email = r.data.get("email", "")
                        self._email(email, account)
                        allowed = self._bool(r.data.get("consent", False))
                        existing = db.execute("SELECT * FROM contacts WHERE account_id=?", (account_id,)).fetchone()
                        if existing and existing["email"] != email:
                            raise DomainError("contact_replacement_requires_review")
                        if not existing or r.observed_at > existing["consent_at"]:
                            db.execute("INSERT INTO contacts VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                                       "email=excluded.email,consent=excluded.consent,consent_at=excluded.consent_at",
                                       (account_id, email, int(allowed), r.observed_at))
                    elif r.kind == "owner":
                        owner = r.data.get("owner")
                        if owner not in self.policy["owners"].values() or not owner.startswith(r.brand + "-"):
                            raise DomainError("invalid_brand_owner")
                        if r.observed_at > account["owner_at"]:
                            db.execute("UPDATE accounts SET owner=?,owner_at=?,revision=revision+1 WHERE id=?",
                                       (owner, r.observed_at, account_id))
                    elif r.kind == "consent":
                        allowed = self._bool(r.data.get("allowed"))
                        # A late opt-out always suppresses; stale opt-in cannot re-authorize.
                        contact = db.execute("SELECT * FROM contacts WHERE account_id=?", (account_id,)).fetchone()
                        if not contact:
                            raise DomainError("contact_required")
                        if not allowed or r.observed_at > contact["consent_at"]:
                            db.execute("UPDATE contacts SET consent=?,consent_at=max(consent_at,?) WHERE account_id=?",
                                       (int(allowed), r.observed_at, account_id))
                    elif r.kind == "intent" and r.data.get("signal") not in self.policy["signal_weights"]:
                        raise DomainError("unknown_signal")
                    elif r.kind == "outcome":
                        reason = self._outcome(db, r, account_id, key, now)
                    elif r.kind == "inbound":
                        self._email(r.data.get("email", ""), account)
                        if r.data.get("request") not in {"discovery", "support", "pricing"}:
                            raise DomainError("invalid_inquiry")
                        self._bool(r.data.get("consent"))
                        contact = db.execute("SELECT * FROM contacts WHERE account_id=?", (account_id,)).fetchone()
                        if not contact or contact["email"] != r.data["email"]:
                            status, reason = "quarantined", "unverified_contact"
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (key, r.source, r.source_id, r.brand, r.kind, account_id,
                        r.observed_at, now, canonical(body), fingerprint, status, reason))
            self.audit(db, now, "source_admission", key, {"status": status, "reason": reason})
        if r.kind == "inbound":
            return self.route(key, now)
        return {"source_key": key, "account_id": account_id, "status": status, "reason": reason}

    @staticmethod
    def _bool(value):
        if type(value) is not bool:
            raise DomainError("boolean_required")
        return value

    @staticmethod
    def _email(value, account):
        if not isinstance(value, str) or len(value) > 180 or value.count("@") != 1:
            raise DomainError("invalid_contact")
        if value.rsplit("@", 1)[1] != account["domain"]:
            raise DomainError("contact_account_mismatch")

    def _account_input(self, db, r, account_id, key):
        d = r.data
        if "employees" in d and (type(d["employees"]) is not int or not 0 <= d["employees"] <= 10000000):
            raise DomainError("invalid_employee_count")
        for field in ("name", "industry", "territory", "lifecycle", "owner"):
            if field in d and (not isinstance(d[field], str) or len(d[field]) > 150):
                raise DomainError("invalid_account_field")
        existing = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not existing:
            territory = d.get("territory", "unknown")
            # Discovered accounts need CRM confirmation before eligible activation.
            owner = d.get("owner", "") if r.source == "crm" else ""
            if owner and (owner not in self.policy["owners"].values() or not owner.startswith(r.brand + "-")):
                raise DomainError("invalid_brand_owner")
            lifecycle = d.get("lifecycle", "prospect") if r.source == "crm" else "unverified"
            if lifecycle not in {"prospect", "customer", "excluded", "unverified"}:
                raise DomainError("invalid_lifecycle")
            db.execute("INSERT INTO accounts(id,brand,domain,name,territory,lifecycle,owner,owner_at) VALUES(?,?,?,?,?,?,?,?)",
                       (account_id, r.brand, r.domain, d.get("name", r.domain), territory, lifecycle, owner, r.observed_at))
        elif r.source == "crm" and (r.observed_at > existing["owner_at"] or existing["lifecycle"] == "unverified"):
            owner = d.get("owner", existing["owner"])
            if owner and (owner not in self.policy["owners"].values() or not owner.startswith(r.brand + "-")):
                raise DomainError("invalid_brand_owner")
            lifecycle = d.get("lifecycle", existing["lifecycle"])
            if lifecycle not in {"prospect", "customer", "excluded", "unverified"}:
                raise DomainError("invalid_lifecycle")
            db.execute("UPDATE accounts SET name=?,territory=?,lifecycle=?,owner=?,owner_at=?,revision=revision+1 WHERE id=?",
                       (d.get("name", existing["name"]), d.get("territory", existing["territory"]),
                        lifecycle, owner, r.observed_at, account_id))
        for field in ("employees", "industry"):
            if field not in d:
                continue
            prior = db.execute("SELECT * FROM fields WHERE account_id=? AND name=?", (account_id, field)).fetchone()
            if prior and prior["source"] == "crm" and r.source != "crm":
                if json.loads(prior["value"]) != d[field]:
                    self.audit(db, r.observed_at, "field_conflict", account_id,
                               {"field": field, "retained_source": "crm", "rejected_source_key": key})
                continue
            if prior and prior["source"] == r.source and prior["observed_at"] >= r.observed_at:
                continue
            db.execute("INSERT INTO fields VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,name) DO UPDATE SET "
                       "value=excluded.value,source=excluded.source,observed_at=excluded.observed_at,source_key=excluded.source_key",
                       (account_id, field, canonical(d[field]), r.source, r.observed_at, key))

    def _outcome(self, db, r, account_id, key, now):
        d = r.data
        kind = d.get("kind")
        if kind not in {"reply_positive", "reply_negative", "meeting_qualified", "opportunity_accepted"}:
            raise DomainError("unknown_outcome")
        if (kind == "opportunity_accepted") != (r.source == "crm"):
            raise DomainError("outcome_source_authority")
        business_id = d.get("business_id")
        if not isinstance(business_id, str) or not business_id or len(business_id) > 100:
            raise DomainError("business_id_required")
        amount = d.get("amount_cents", 0)
        if type(amount) is not int or amount < 0 or amount > 100000000000:
            raise DomainError("invalid_pipeline_value")
        if kind != "opportunity_accepted" and amount:
            raise DomainError("non_opportunity_value")
        origin = d.get("origin")
        if origin not in {"sequence", "organic"}:
            raise DomainError("outcome_origin_required")
        created_at = stamp(moment(d["created_at"])) if "created_at" in d else r.observed_at
        if kind == "opportunity_accepted" and "created_at" not in d:
            raise DomainError("opportunity_creation_time_required")
        if created_at > r.observed_at:
            raise DomainError("outcome_before_creation")
        action_key = d.get("action_key")
        if origin == "sequence":
            action = db.execute("SELECT * FROM actions WHERE action_key=?", (action_key,)).fetchone()
            if not action or action["account_id"] != account_id or not action["receipt"]:
                raise DomainError("verified_enrollment_required")
            receipt = json.loads(action["receipt"])
            if r.observed_at < receipt["accepted_at"]:
                raise DomainError("outcome_before_enrollment")
        elif action_key:
            raise DomainError("organic_cannot_claim_sequence")
        parent = d.get("parent_id")
        expected = {"meeting_qualified": "reply_positive", "opportunity_accepted": "meeting_qualified"}.get(kind)
        if expected and origin == "sequence":
            row = db.execute("SELECT * FROM feedback WHERE account_id=? AND business_id=? AND kind=?",
                             (account_id, parent, expected)).fetchone()
            if not row or row["action_key"] != action_key or row["occurred_at"] > r.observed_at:
                raise DomainError("outcome_transition_invalid")
        prior = db.execute("SELECT * FROM feedback WHERE account_id=? AND business_id=? AND kind=?",
                           (account_id, business_id, kind)).fetchone()
        if prior:
            if (prior["occurred_at"], prior["amount_cents"], prior["action_key"], prior["origin"], prior["created_at"], prior["parent_id"]) != (
                    r.observed_at, amount, action_key, origin, created_at, parent):
                raise DomainError("outcome_content_collision")
            return "duplicate_business_outcome"
        db.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (key, account_id, kind, business_id, r.observed_at, now, amount, action_key, origin, key, created_at, parent))
        return "feedback_recorded"

    def _score(self, db, account_id, now):
        account = self.account(db, account_id)
        p = self.policy
        fields, contributions, reasons = {}, [], []
        for row in db.execute("SELECT * FROM fields WHERE account_id=?", (account_id,)):
            ttl = p["crm_fresh_days"] if row["source"] == "crm" else p["enrichment_fresh_days"]
            fresh = timedelta(0) <= moment(now) - moment(row["observed_at"]) <= timedelta(days=ttl)
            fields[row["name"]] = json.loads(row["value"]) if fresh else None
            contributions.append({"field": row["name"], "source_key": row["source_key"], "fresh": fresh})
        fit = 0
        if (fields.get("employees") or 0) >= p["minimum_employees"]:
            fit += p["employees_points"]
        if fields.get("industry") in p["industries"]:
            fit += p["industry_points"]
        if f'{account["brand"]}:{account["territory"]}' in p["owners"]:
            fit += p["territory_points"]
        intent_by_type = {}
        for row in db.execute("SELECT * FROM sources WHERE account_id=? AND kind IN('intent','inbound') "
                              "AND disposition='accepted' AND observed_at<=? AND received_at<=?",
                              (account_id, now, now)):
            data = json.loads(row["payload"])["data"]
            signal = "inquiry" if row["kind"] == "inbound" else data["signal"]
            age = (moment(now) - moment(row["observed_at"])).total_seconds() / 86400
            if 0 <= age < p["intent_days"]:
                points = round(p["signal_weights"][signal] * (1 - age / p["intent_days"]), 3)
                if signal not in intent_by_type or points > intent_by_type[signal]["points"]:
                    intent_by_type[signal] = {"signal": signal, "points": points, "source_key": row["source_key"]}
        intent = min(100, round(sum(x["points"] for x in intent_by_type.values()), 3))
        contact = db.execute("SELECT * FROM contacts WHERE account_id=?", (account_id,)).fetchone()
        if account["lifecycle"] != "prospect":
            reasons.append("not_new_business_prospect")
        if db.execute("SELECT count(*) FROM accounts WHERE brand=? AND domain=?",
                      (account["brand"], account["domain"])).fetchone()[0] != 1:
            reasons.append("identity_requires_review")
        if account["suppressed"] or not contact or not contact["consent"]:
            reasons.append("permission_missing_or_suppressed")
        if not account["owner"] or not account["owner"].startswith(account["brand"] + "-"):
            reasons.append("owner_unverified")
        if not timedelta(0) <= moment(now) - moment(account["owner_at"]) <= timedelta(days=p["crm_fresh_days"]):
            reasons.append("owner_authority_stale")
        if fit < p["fit_min"]:
            reasons.append("fit_below_policy")
        if intent < p["intent_min"]:
            reasons.append("intent_stale_or_insufficient")
        return {"account_id": account_id, "at": now, "policy_version": p["version"], "policy_hash": self.policy_hash,
                "fit": fit, "intent": intent, "eligible": not reasons, "reasons": reasons,
                "field_evidence": contributions, "signals": list(intent_by_type.values()),
                "owner": account["owner"], "owner_revision": account["revision"]}

    def score(self, account_id, now):
        now = stamp(moment(now))
        with self.transaction() as db:
            body = self._score(db, account_id, now)
            decision_id = "dec_" + digest(body)[:24]
            db.execute("INSERT OR IGNORE INTO decisions VALUES(?,?,?,?,?)",
                       (decision_id, account_id, now, self.policy_hash, canonical(body)))
            self.audit(db, now, "qualification", decision_id, {"eligible": body["eligible"], "reasons": body["reasons"]})
        return {"id": decision_id, **body}

    def assign(self, account_id, now):
        decision = self.score(account_id, now)
        with self.transaction() as db:
            prior = db.execute("SELECT * FROM cohorts WHERE experiment=? AND account_id=?",
                               (self.policy["experiment"], account_id)).fetchone()
            if prior:
                return dict(prior)
            if "dec_" + digest(self._score(db, account_id, now))[:24] != decision["id"]:
                raise DomainError("cohort_context_changed")
            if not decision["eligible"]:
                raise DomainError("cohort_ineligible")
            if db.execute("SELECT 1 FROM feedback WHERE account_id=? AND kind='opportunity_accepted' AND occurred_at<=?",
                          (account_id, now)).fetchone():
                raise DomainError("preexisting_pipeline_excluded")
            # Same domain across operating units cannot receive opposing treatment assignments.
            # This is a conservative allocation cluster, not a cross-brand identity merge.
            account = self.account(db, account_id)
            bucket = int(digest([self.policy["salt"], self.policy["experiment"], account["domain"]])[:8], 16) % 10000
            arm = "treatment" if bucket < 5000 else "holdout"
            end = stamp(moment(now) + timedelta(days=self.policy["window_days"]))
            db.execute("INSERT INTO cohorts VALUES(?,?,?,?,?,?)",
                       (self.policy["experiment"], account_id, arm, now, end, decision["id"]))
            self.audit(db, now, "cohort_assignment", account_id,
                       {"arm": arm, "bucket": bucket, "allocation_cluster": account["domain"]})
            return dict(db.execute("SELECT * FROM cohorts WHERE account_id=? AND experiment=?",
                                   (account_id, self.policy["experiment"])).fetchone())

    def route(self, source_key, now):
        with self.transaction() as db:
            prior = db.execute("SELECT * FROM routes WHERE source_key=?", (source_key,)).fetchone()
            if prior:
                return dict(prior)
            source = db.execute("SELECT * FROM sources WHERE source_key=? AND kind='inbound'", (source_key,)).fetchone()
            if not source:
                raise DomainError("inbound_source_required")
            account_id, owner, status, reason = source["account_id"], None, "exception", source["reason"]
            if source["disposition"] == "accepted":
                account = self.account(db, account_id)
                owner = account["owner"]
                request = json.loads(source["payload"])["data"]
                if not request["consent"]:
                    reason = "inbound_permission_missing"
                elif account["lifecycle"] == "customer" or request["request"] == "support":
                    status, reason = "service_review", "existing_relationship_or_service"
                elif not owner:
                    reason = "owner_unverified"
                else:
                    decision = self._score(db, account_id, now)
                    status = "seller_review" if decision["eligible"] else "exception"
                    reason = "qualified_inbound" if decision["eligible"] else ",".join(decision["reasons"])
            db.execute("INSERT INTO routes VALUES(?,?,?,?,?,?,NULL)",
                       (source_key, account_id, now, owner, status, reason))
            self.audit(db, now, "inbound_route", source_key, {"status": status, "reason": reason, "owner": owner})
            return dict(db.execute("SELECT * FROM routes WHERE source_key=?", (source_key,)).fetchone())

    def _context(self, db, account_id, now):
        # Bind material facts/permission/owner and actual scoring evidence; timestamps alone do not invalidate.
        score = self._score(db, account_id, now)
        return digest({"account": self.account(db, account_id),
                       "contact": dict(db.execute("SELECT * FROM contacts WHERE account_id=?", (account_id,)).fetchone()),
                       "fields": [dict(x) for x in db.execute("SELECT * FROM fields WHERE account_id=? ORDER BY name", (account_id,))],
                       "signals": sorted(x["source_key"] for x in score["signals"]), "policy": self.policy_hash})

    def prepare(self, account_id, now):
        decision = self.score(account_id, now)
        with self.connection() as db:
            cohort = db.execute("SELECT * FROM cohorts WHERE account_id=? AND experiment=?",
                                (account_id, self.policy["experiment"])).fetchone()
            if not decision["eligible"] or not cohort or cohort["arm"] != "treatment":
                raise DomainError("eligible_treatment_required")
            if not cohort["assigned_at"] <= now < cohort["window_end"]:
                raise DomainError("experiment_window_closed")
            account = self.account(db, account_id)
            contact = db.execute("SELECT * FROM contacts WHERE account_id=?", (account_id,)).fetchone()
            action_key = "act_" + digest([self.policy["experiment"], account_id, "research-review-v1"])[:24]
            payload = Action(action_key=action_key, account_id=account_id, brand=account["brand"],
                             contact=contact["email"], owner=account["owner"],
                             message="Synthetic discovery sequence: ask whether an introductory conversation would be useful. "
                                     "No availability, pricing or delivery commitment is authorized.").model_dump()
            return {"decision_id": decision["id"], "payload": payload, "payload_hash": digest(payload),
                    "context_hash": self._context(db, account_id, now), "policy_hash": self.policy_hash}

    def approve(self, account_id, prepared, reviewer, now):
        if reviewer != "demo-reviewer":
            raise DomainError("reviewer_required")
        expected = self.prepare(account_id, now)
        if prepared != expected:
            raise DomainError("stale_or_modified_review")
        with self.transaction() as db:
            # Recheck while holding the same admission lock used for source mutations.
            if self._context(db, account_id, now) != expected["context_hash"]:
                raise DomainError("context_changed")
            key = expected["payload"]["action_key"]
            prior = db.execute("SELECT * FROM actions WHERE action_key=?", (key,)).fetchone()
            if prior:
                if prior["payload_hash"] != expected["payload_hash"] or prior["context_hash"] != expected["context_hash"]:
                    raise DomainError("action_key_already_bound")
                return dict(prior)
            account = self.account(db, account_id)
            db.execute("INSERT INTO actions(action_key,account_id,experiment,decision_id,approved_at,owner_revision,"
                       "context_hash,payload,payload_hash,reviewer,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (key, account_id, self.policy["experiment"], expected["decision_id"], now, account["revision"],
                        expected["context_hash"], canonical(expected["payload"]), expected["payload_hash"], reviewer, "approved"))
            db.execute("UPDATE routes SET action_key=? WHERE account_id=? AND status='seller_review' AND action_key IS NULL",
                       (key, account_id))
            self.audit(db, now, "exact_approval", key, {"payload_hash": expected["payload_hash"], "reviewer": reviewer})
            return dict(db.execute("SELECT * FROM actions WHERE action_key=?", (key,)).fetchone())

    def authorize(self, db, action, now):
        payload = Action.model_validate(json.loads(action["payload"])).model_dump()
        if digest(payload) != action["payload_hash"] or payload["action_key"] != action["action_key"]:
            raise DomainError("approval_content_tampered")
        audit = db.execute("SELECT detail FROM audit WHERE event='exact_approval' AND subject=?",
                           (action["action_key"],)).fetchall()
        if not any(json.loads(x[0]).get("payload_hash") == action["payload_hash"] for x in audit):
            raise DomainError("approval_audit_missing")
        if now < action["approved_at"]:
            raise DomainError("approval_time_not_reached")
        if moment(now) - moment(action["approved_at"]) > timedelta(hours=self.policy["approval_hours"]):
            raise DomainError("approval_expired")
        score = self._score(db, action["account_id"], now)
        if not score["eligible"]:
            raise DomainError("current_authorization_denied:" + ",".join(score["reasons"]))
        if self._context(db, action["account_id"], now) != action["context_hash"]:
            raise DomainError("current_context_changed")
        cohort = db.execute("SELECT * FROM cohorts WHERE experiment=? AND account_id=?",
                            (action["experiment"], action["account_id"])).fetchone()
        if not cohort or cohort["arm"] != "treatment" or not cohort["assigned_at"] <= now < cohort["window_end"]:
            raise DomainError("experiment_authority_denied")
        return payload
