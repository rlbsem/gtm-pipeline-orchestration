"""Exact-review-gated continuation of connected_prepare; bounded isolated Salesforce writes only."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from connected_prepare import read_context
from gtm.connected import ConnectedCRM, Signal, approve_review
from gtm.engine import Engine
from gtm.salesforce import API, SalesforceError, get_json
from gtm.standard_crm import RECEIPT, Scope, StandardCRM, TaskDispatcher
from gtm.store import digest
from native_standard import Run
from publication import source_hashes


def execution_sources():
    return {p: h for p, h in source_hashes().items() if p.startswith(("src/", "salesforce/"))
            or p in {"scripts/native_connected.py", "scripts/native_standard.py", "scripts/native_salesforce.py",
                     "scripts/connected_prepare.py", "scripts/publication.py"}}


class ConnectedRun(Run):
    def __init__(self, args):
        self.preview = json.loads((args.workspace / "preview.json").read_text(encoding="utf-8"))
        self.scope = Scope(**json.loads((args.workspace / "private-scope.json").read_text(encoding="utf-8")))
        if (self.preview["status"] != "awaiting_exact_review"
                or args.approved_review_sha256 != self.preview["review_hash"]
                or digest(self.preview["review"]) != args.approved_review_sha256):
            raise SalesforceError("exact_connected_review_required")
        original = json.loads(args.retained_manifest.read_text(encoding="utf-8"))
        if (original.get("phase") != "finished" or original["run_id"] != self.scope.run_id
                or original["ids"]["account"] != self.scope.account
                or original["ids"]["contact"] != self.scope.contact):
            raise SalesforceError("retained_manifest_mismatch")
        args.run_id = self.scope.run_id
        super().__init__(args)
        if not self.state["ids"]:
            self.state["ids"] = {k: original["ids"][k] for k in ("account", "contact", "other_account")}
            self.state["retained_manifest_hash"] = digest(original)
            self.save()
        self.engine = Engine(args.workspace / "control.sqlite")

    def execute_connected(self):
        self.pin()
        # Reuse the existing temporary-grant journal. All three fixture rows already exist;
        # setup skips their creation, and the original Task/opportunity are never adopted.
        self.setup()
        scope = self.scope
        crm_args = (self.clients["integration"], self.clients["reviewer"], self.clients["administrator"], self.approval, scope)
        StandardCRM(*crm_args).preflight()
        current = read_context(self.clients["administrator"], self.approval, scope)
        for field in ("account_hash", "contact_hash", "owner_hash", "contact_account_hash",
                      "account_owner_hash", "contact_owner_hash", "active_opportunities"):
            if current[field] != self.preview["crm_context"][field]:
                raise SalesforceError("reviewed_crm_identity_changed")
        account = get_json(self.clients["administrator"], API + "/sobjects/Account/" + scope.account,
                           params={"fields": "GTM_Test_Key__c,GTM_Test_Active__c"})
        contact = get_json(self.clients["administrator"], API + "/sobjects/Contact/" + scope.contact,
                           params={"fields": "GTM_Test_Key__c,HasOptedOutOfEmail"})
        if (account["GTM_Test_Key__c"] != scope.run_id + "/account-a"
                or contact["GTM_Test_Key__c"] != scope.run_id + "/contact-a"
                or account["GTM_Test_Active__c"] is not False or contact["HasOptedOutOfEmail"] is not True):
            raise SalesforceError("retained_scope_or_quiescent_baseline_changed")
        self.state["prior_flags"] = {"account_active": False, "contact_opted_out": True}
        self.save()
        with self.engine.connection() as db:
            local_account = self.engine.account(db, self.preview["review"]["account_id"])
        action = approve_review(self.engine, local_account, self.preview["review_clock"],
            Signal(**self.preview["signal"]), self.preview["crm_context"], self.preview["inference"],
            self.preview["review"], self.args.approved_review_sha256)
        crm = ConnectedCRM(*crm_args, engine=self.engine, action_key=action["action_key"], review=self.preview["review"])
        crm.preflight()
        self.write("Account", {"GTM_Test_Active__c": True}, scope.account)
        self.write("Contact", {"HasOptedOutOfEmail": False}, scope.contact)
        crm.resolve()
        self.checks["exact_native_keys_identity_owner_and_eligibility"] = True
        self.checks["real_inference_exact_review_bound_to_native_payload"] = True
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        dispatcher = TaskDispatcher(self.engine, crm)
        key = dispatcher.prepare(action["action_key"], now)
        self.state["native_key"] = key
        self.save()
        self.drop = True
        first = dispatcher.dispatch(key, now)
        if first["status"] != "uncertain":
            raise SalesforceError("lost_ack_probe_not_established")
        posts = sum(r["role"] == "integration" and r["method"] == "POST" for r in self.raw)
        result = TaskDispatcher(self.engine, crm).dispatch(key, now)
        if result["status"] != "reconciled" or result["receipt"]["task_count"] != 1:
            raise SalesforceError("connected_independent_recovery_failed")
        if posts != sum(r["role"] == "integration" and r["method"] == "POST" for r in self.raw):
            raise SalesforceError("unexpected_recovery_repost")
        self.checks["real_commit_ack_discard_and_restart_without_repost"] = True
        self.verified_receipt = result["receipt"]
        receipt = get_json(crm.reader, API + "/sobjects/" + RECEIPT + "/Action_Key__c/" + key)
        task = get_json(crm.reader, API + "/sobjects/Task/" + receipt["Task_Id__c"], params={
            "fields": "Id,WhatId,WhoId,OwnerId,CreatedById,Description"})
        self.relationships = {"account_hash": digest(scope.account), "contact_account_hash": digest(scope.account),
                              "task_account_hash": digest(task["WhatId"]), "contact_hash": digest(scope.contact),
                              "task_contact_hash": digest(task["WhoId"]), "owner_hash": digest(scope.owner),
                              "task_owner_hash": digest(task["OwnerId"]), "reader_hash": digest(scope.reader),
                              "task_created_by_hash": digest(task["CreatedById"]), "writer_hash": digest(scope.writer),
                              "task_description_hash": digest(json.loads(task["Description"]))}
        self.state["ids"]["task"] = receipt["Task_Id__c"]
        self.save()
        response = crm.writer.request("POST", API + "/sobjects/Task", json=crm.body(key),
                                      headers={"Sforce-Email-Header": "triggerUserEmail=false"})
        if response.status_code != 400 or "DUPLICATE_VALUE" not in response.text:
            raise SalesforceError("server_duplicate_denial_not_established")
        self.checks["server_duplicate_rollback_single_task"] = crm.receipt(key)["task_count"] == 1
        self.negative(crm, "changed_owner", "Account", {"OwnerId": self.admin_id}, {"OwnerId": scope.owner})
        self.negative(crm, "revoked_consent", "Contact", {"HasOptedOutOfEmail": True}, {"HasOptedOutOfEmail": False})
        bad_key = digest([key, "unsupported-personalization"])
        body = crm.body(bad_key)
        envelope = json.loads(body["Description"])
        envelope["message"] = "They have approved a million-dollar budget."
        from gtm.store import canonical
        body["Description"] = canonical(envelope)
        response = crm.writer.request("POST", API + "/sobjects/Task", json=body)
        if response.status_code != 400 or "GTM_SCOPE_OR_AUTHORITY_REJECTED" not in response.text:
            raise SalesforceError("unsupported_native_content_denial_not_established")
        self.absent(bad_key)
        self.checks["unsupported_personalization_server_rejection"] = True
        reviewer_key = digest([key, "reviewer-create"])
        desc = get_json(crm.reader, API + "/sobjects/Task/describe")
        response = crm.reader.request("POST", API + "/sobjects/Task", json=crm.body(reviewer_key))
        if desc.get("createable") is not False or response.status_code < 400:
            raise SalesforceError("reviewer_create_permission_denial_not_established")
        self.absent(reviewer_key)
        self.checks["reviewer_effective_permission_and_rejected_post"] = True
        self.write("Contact", {"HasOptedOutOfEmail": True}, scope.contact)
        self.checks["historical_receipt_after_revoked_eligibility"] = (
            TaskDispatcher(self.engine, crm).dispatch(key, now)["status"] == "reconciled")
        self.connected_body = {"message": self.preview["review"]["message"],
                               "signal_hash": self.preview["review"]["signal_hash"],
                               "model_hash": self.preview["review"]["model_hash"],
                               "review_hash": self.preview["review_hash"], "payload_hash": result["receipt"]["payload_hash"]}

    def quiesce(self):
        # Only the newly created Task is completed. Previously retained Task/opportunity stay untouched.
        if "prior_flags" not in self.state:
            return {"activation_not_started": True}
        return super().quiesce()


def execute(args):
    before = execution_sources()
    run = ConnectedRun(args)
    status = "failed"
    error = None
    try:
        run.execute_connected()
        status = "passed"
    except Exception as exc:
        error = str(exc) if isinstance(exc, SalesforceError) else type(exc).__name__
    finally:
        try:
            cleanup = run.cleanup() if "baseline" in run.state else {"not_started": True}
        except Exception as exc:
            cleanup = {"original_assignments_restored": False, "requires_investigation": True, "error": type(exc).__name__}
            status = "cleanup_failed"
        report = {"status": status, "error": error, "executed_at": datetime.now(timezone.utc).isoformat(),
                  "source_sha256": before, "preview_hash": digest(run.preview), "review_hash": args.approved_review_sha256,
                  "source_binding_scope": "Python package, Salesforce metadata and native controllers; browser/regression evidence binds the complete delivery separately.",
                  "checks": run.checks, "authenticated_requests": len(run.raw), "requests": run.public(),
                  "receipt": getattr(run, "verified_receipt", None), "content": getattr(run, "connected_body", None),
                  "relationships": getattr(run, "relationships", None),
                  "cleanup": cleanup, "boundary": "One real Qwen inference connected to one synthetic internal Salesforce Task. No outreach delivery or commercial pipeline.",
                  "outreach_salesloft": "not_executed_no_approved_test_environment"}
        (args.workspace / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        run.state["phase"] = "finished" if cleanup.get("original_assignments_restored") else "cleanup_required"
        run.save()
        for client in run.clients.values():
            client.close()
        if before != execution_sources():
            raise SalesforceError("source_changed_during_native_execution")
    print(json.dumps({"status": status, "error": error, "authenticated_requests": len(run.raw), "cleanup": cleanup}))
    if status != "passed":
        raise SalesforceError("connected_acceptance_incomplete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--retained-manifest", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--admin", default="csa-demo-owner")
    parser.add_argument("--writer", default="csa-demo-integration")
    parser.add_argument("--reader", default="csa-demo-reviewer")
    parser.add_argument("--approved-review-sha256", required=True)
    parser.add_argument("--approved-isolated-writes", action="store_true", required=True)
    execute(parser.parse_args())
