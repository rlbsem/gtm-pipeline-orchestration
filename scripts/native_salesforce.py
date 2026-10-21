"""Bounded, explicit test-org acceptance. Private CLI tokens and raw observations never leave workspace."""
import argparse
import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from gtm.advice import context
from gtm.engine import Engine
from gtm.salesforce import API, OBJECT, Approval, Mapping, NativeDispatcher, ReviewInbox, SalesforceClient, SalesforceError
from gtm.store import digest
from gtm.upgrade_scenarios import SCENARIO, cases, fixture, mutate
from execution_bindings import lane_hashes


def authenticate(cli, alias):
    result = subprocess.run([str(cli), "org", "auth", "show-access-token", "--target-org", alias, "--json"],
                            capture_output=True, text=True, encoding="utf-8", timeout=90,
                            env={**os.environ, "SF_DISABLE_TELEMETRY": "true", "SF_AUTOUPDATE_DISABLE": "true"})
    try:
        response = json.loads(result.stdout)
        if result.returncode or response.get("status") != 0:
            raise ValueError()
        return response["result"]["accessToken"]
    except (ValueError, KeyError):
        raise SalesforceError("existing_cli_authentication_unavailable") from None


class Observations:
    def __init__(self, folder):
        self.folder, self.rows, self.drop = folder, [], False

    def observe(self, role, method, path, response):
        if len(self.rows) >= 100:
            raise SalesforceError("native_request_budget_exhausted")
        body = response.json() if response.content else None
        entry = {"role": role, "method": method, "path": path, "http": response.status_code,
                 "body": body, "at": datetime.now(timezone.utc).isoformat()}
        self.rows.append(entry)
        (self.folder / "private-responses.json").write_text(json.dumps(self.rows, indent=2), encoding="utf-8")
        if self.drop and role == "integration" and method == "POST" and response.status_code == 201:
            self.drop = False
            raise SalesforceError("client_discarded_successful_acknowledgement", True)

    def public(self):
        result = []
        for row in self.rows:
            body = row["body"]
            errors = [x.get("errorCode") for x in body if isinstance(x, dict) and "errorCode" in x] if isinstance(body, list) else []
            result.append({k: row[k] for k in ("role", "method", "http", "at")} | {
                "resource": "userinfo" if "userinfo" in row["path"] else row["path"].split("/sobjects/")[-1].split("/")[0]
                if "/sobjects/" in row["path"] else "organization_query",
                "response_sha256": digest(body), "error_codes": errors})
        return result


def acceptance(args):
    args.workspace.mkdir(parents=True, exist_ok=True)
    checkpoint = args.workspace / "checkpoint.json"
    if checkpoint.exists():
        prior = json.loads(checkpoint.read_text())
        if prior["run_id"] != args.run_id or prior.get("finished"):
            raise SalesforceError("use_exact_unfinished_run_or_fresh_workspace")
    else:
        checkpoint.write_text(json.dumps({"run_id": args.run_id, "finished": False}), encoding="utf-8")
    before = lane_hashes("salesforce")
    config = json.loads(args.config.read_text())
    engine = Engine(args.workspace / "control.sqlite")
    case = cases()["cases"][0]
    if not engine.rows("accounts"):
        account, _ = fixture(engine, case)
    else:
        cohort = next(c for c in engine.rows("cohorts") if c["arm"] == "treatment")
        with engine.connection() as db:
            account = engine.account(db, cohort["account_id"])
    provider = config["mappings"][0]
    mapping = Mapping(account["brand"], account["id"], account["owner"], provider["brand"], provider["account"],
                      provider["owner"], provider["registry_id"], provider["user_id"])
    observation = Observations(args.workspace)
    clients = {}
    try:
        for role, alias in (("administrator", args.admin), ("integration", args.writer), ("reviewer", args.reader)):
            clients[role] = SalesforceClient(config["instance_url"], authenticate(args.cli, alias),
                                            lambda method, path, response, r=role: observation.observe(r, method, path, response),
                                            read_only=role == "administrator")
        inbox = ReviewInbox(clients["integration"], clients["reviewer"], clients["administrator"],
                            Approval(**config["approval"]), mapping, config["integration_user_id"], config["reviewer_user_id"])
        preflight = inbox.preflight()
        source_before = inbox.validate_source()
        standard = {}
        for name in ("Account", "Contact", "Task"):
            response = inbox.writer.request("GET", API + "/sobjects/" + name + "/describe")
            standard[name] = {"http": response.status_code, "executed_record_access": False}
        research = json.loads(args.ai_evidence.read_text())["records"][0]
        assert research["case_id"] == "fresh_inbound" and research["inference"] == "executed"
        assert research["context_hash"] == digest(context(engine, account["id"], SCENARIO))
        prepared = engine.prepare(account["id"], SCENARIO)
        action = engine.approve(account["id"], prepared, "demo-reviewer", SCENARIO)
        dispatcher = NativeDispatcher(engine, inbox)
        intent = dispatcher.prepare(action["action_key"], args.run_id, SCENARIO,
                                    {k: research[k] for k in ("request_hash", "context_hash", "validation_error")})
        key, envelope = intent["native_key"], json.loads(intent["envelope"])
        observation.drop = True
        first = dispatcher.dispatch(key, SCENARIO)
        # New dispatcher reads durable state; receipt reconciles before any new POST.
        second = NativeDispatcher(Engine(args.workspace / "control.sqlite"), inbox).dispatch(key, "2026-01-21T12:00:03Z")
        assert first["status"] in {"uncertain", "reconciled"} and second["status"] == "reconciled"
        receipt = second["receipt"]
        body = {**inbox.body(key, envelope), "Review_Status__c": "Pending"}
        duplicate = inbox.writer.request("POST", API + "/sobjects/" + OBJECT + "/", json=body)
        assert duplicate.status_code == 400 and any(x.get("errorCode") == "DUPLICATE_VALUE" for x in duplicate.json())
        # Effective schema denial + rejected operation + absence, rather than guessing from trigger error names.
        probe_key = digest([key, "reviewer-create-denial"])
        assert inbox.receipt(probe_key, envelope, independent=True) is None
        denial = inbox.reader.request("POST", API + "/sobjects/" + OBJECT + "/",
                                     json={**body, "Action_Key__c": probe_key})
        if denial.status_code == 201:
            # Own synthetic unexpected record only; preserve it as Rejected for audit before failing.
            unexpected = denial.json()["id"]
            inbox.reader.request("PATCH", API + "/sobjects/" + OBJECT + "/" + unexpected,
                                 json={"Review_Status__c": "Rejected"})
            raise SalesforceError("reviewer_unexpectedly_created_record")
        assert denial.status_code in {400, 401, 403} and inbox.receipt(probe_key, envelope, independent=True) is None
        protected = inbox.writer.request("PATCH", API + "/sobjects/" + OBJECT + "/" + receipt["record_id"],
                                         json={"Draft__c": body["Draft__c"]})
        assert protected.status_code in {400, 401, 403}
        verified = inbox.receipt(key, envelope, independent=True)
        assert verified["exact_content_verified"]
        inventory = inbox.reader.request("GET", API + "/query", params={
            "q": f"SELECT Id FROM {OBJECT} WHERE Action_Key__c = '{key}'"})
        assert inventory.status_code == 200 and inventory.json()["totalSize"] == 1
        # Historical receipt remains valid after local opt-out; no NEW action may be prepared.
        mutate(engine, account, "consent", {"allowed": False}, source="web", at="2026-01-21T12:00:04Z")
        after_optout = dispatcher.dispatch(key, "2026-01-21T12:00:05Z")
        assert after_optout["status"] == "reconciled"
        try:
            engine.prepare(account["id"], "2026-01-21T12:00:05Z")
        except ValueError:
            new_action_blocked = True
        else:
            new_action_blocked = False
        assert new_action_blocked
        cleanup = inbox.reader.request("PATCH", API + "/sobjects/" + OBJECT + "/" + receipt["record_id"],
                                       json={"Review_Status__c": "Rejected"})
        assert cleanup.status_code == 204
        final = inbox.receipt(key, envelope, independent=True)
        assert final["review_status"] == "Rejected" and inbox.validate_source() == source_before
        assert engine.audit_valid() and lane_hashes("salesforce") == before
        result = {"executed_at": datetime.now(timezone.utc).isoformat(), "run_id": args.run_id,
                  "status": "passed", "boundary": "native synthetic internal review; not native sequence or commercial outcomes",
                  "source_sha256": before, "preflight": preflight, "standard_objects": standard,
                  "mapping": {k: v for k, v in asdict(mapping).items() if k not in {"registry_id", "user_id"}},
                  "native_key": key, "record_id_sha256": digest(receipt["record_id"]),
                  "envelope_sha256": digest(envelope), "advisory_reference": envelope["advisory_reference"],
                  "checks": {"client_lost_ack_recovered": True, "unique_duplicate_rejected": True,
                             "reviewer_effective_create_false": True, "reviewer_post_rejected_and_absent": True,
                             "integration_protected_update_rejected": True, "exact_independent_readback": True,
                             "one_record_for_action_key": True, "receipt_reconciled_after_optout": True,
                             "new_action_blocked_after_optout": True, "source_unchanged": True, "audit_valid": True},
                  "cleanup": {"new_review_status": "Rejected", "readback_verified": True,
                              "record_retained_for_audit": True, "users_permissions_and_existing_records_changed": False},
                  "requests": observation.public(), "authenticated_requests": len(observation.rows),
                  "limits": ["Standard Account/Contact/Task access not granted; no standard record lane executed.",
                             "Lost acknowledgement is client-side fault injection after actual POST 201.",
                             "Rejected POST error codes are recorded without classifying trigger errors as permission codes.",
                             "Raw record identifiers and response bodies remain in private operator workspace.",
                             "Source changes after last read cannot be prevented atomically across two systems."]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        checkpoint.write_text(json.dumps({"run_id": args.run_id, "finished": True,
                                          "record_id": receipt["record_id"], "result_sha256": digest(result)}), encoding="utf-8")
        print(json.dumps({"status": "passed", "authenticated_requests": len(observation.rows), "cleanup": result["cleanup"]}))
        return result
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ai-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--admin", required=True)
    parser.add_argument("--writer", required=True)
    parser.add_argument("--reader", required=True)
    acceptance(parser.parse_args())
