"""Explicit, bounded isolated-org standard CRM acceptance. Tokens and raw IDs stay private."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from gtm.engine import Engine
from gtm.salesforce import API, Approval, SalesforceClient, SalesforceError, get_json, success
from gtm.standard_crm import RECEIPT, Scope, StandardCRM, TaskDispatcher
from gtm.store import digest
from gtm.upgrade_scenarios import SCENARIO, cases, fixture
from native_salesforce import authenticate
from publication import source_hashes


class Run:
    def __init__(self, args):
        self.args = args
        args.workspace.mkdir(parents=True, exist_ok=True)
        self.path = args.workspace / "private-checkpoint.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            "run_id": args.run_id, "ids": {}, "assignments": [], "phase": "new"}
        if self.state["run_id"] != args.run_id or self.state["phase"] == "finished":
            raise SalesforceError("fresh_or_exact_unfinished_run_required")
        self.config = json.loads(args.config.read_text())
        self.approval = Approval(**self.config["approval"])
        self.raw_path = args.workspace / "private-responses.json"
        self.raw = json.loads(self.raw_path.read_text()) if self.raw_path.exists() else []
        self.clients = {}
        self.checks = {}
        for role, alias in (("administrator", args.admin), ("integration", args.writer), ("reviewer", args.reader)):
            self.clients[role] = SalesforceClient(self.config["instance_url"], authenticate(args.cli, alias),
                lambda method, path, response, r=role: self.observe(r, method, path, response))
        self.drop = False

    def save(self):
        self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def observe(self, role, method, path, response):
        body = response.json() if response.content else None
        self.raw.append({"role": role, "method": method, "path": path, "http": response.status_code,
                         "body": body, "at": datetime.now(timezone.utc).isoformat()})
        self.raw_path.write_text(json.dumps(self.raw, indent=2), encoding="utf-8")
        if len(self.raw) > 350:
            raise SalesforceError("native_request_budget_exhausted")
        if self.drop and role == "integration" and method == "POST" and response.status_code == 201:
            self.drop = False
            raise SalesforceError("client_discarded_successful_acknowledgement", True)

    def query(self, q, role="administrator"):
        rows = get_json(self.clients[role], API + "/query", params={"q": q})
        if not rows["done"]:
            raise SalesforceError("unbounded_native_inventory")
        return rows["records"]

    def write(self, obj, body, record=None):
        # Administrator setup/lifecycle only; exact newly journaled IDs, never arbitrary records.
        allowed = {"PermissionSetAssignment", "PermissionSetLicenseAssign", "Account", "Contact", "Opportunity", "Task"}
        if obj not in allowed or (record and record not in self.state["ids"].values()):
            raise SalesforceError("setup_write_outside_private_manifest")
        r = self.clients["administrator"].request("PATCH" if record else "POST",
                API + "/sobjects/" + obj + ("/" + record if record else ""), json=body)
        success(r)
        return r.json()["id"] if not record else record

    def pin(self):
        self.approval.verify(self.query("SELECT Id,IsSandbox,OrganizationType FROM Organization")[0])
        for role, client in self.clients.items():
            who = get_json(client, "/services/oauth2/userinfo")
            if who["organization_id"] != self.approval.org_id:
                raise SalesforceError("pinned_org_mismatch")
            if role == "administrator":
                self.admin_id = who["user_id"]
            elif who["user_id"] != self.config[role + "_user_id"]:
                raise SalesforceError("pinned_identity_mismatch")

    def setup(self):
        s = self.state
        writer, reader = self.config["integration_user_id"], self.config["reviewer_user_id"]
        if "baseline" not in s:
            s["baseline"] = {}
            for role, uid in (("administrator", self.admin_id), ("integration", writer), ("reviewer", reader)):
                s["baseline"][role] = sorted(r["PermissionSetId"] for r in self.query(
                    "SELECT PermissionSetId FROM PermissionSetAssignment WHERE AssigneeId='" + uid + "'"))
            s["baseline_psl"] = sorted(r["PermissionSetLicenseId"] for r in self.query(
                "SELECT PermissionSetLicenseId FROM PermissionSetLicenseAssign WHERE AssigneeId='" + writer + "'"))
            self.save()
        psl = self.query("SELECT Id FROM PermissionSetLicense WHERE MasterLabel='Salesforce API Integration'")
        if len(psl) != 1:
            raise SalesforceError("integration_entitlement_unavailable")
        if psl[0]["Id"] not in s["baseline_psl"]:
            self.assign("PermissionSetLicenseAssign", writer, psl[0]["Id"], "PermissionSetLicenseId")
        for name, uid in (("GTM_Standard_Setup", self.admin_id), ("GTM_Standard_Integration", writer), ("GTM_Standard_Observer", reader)):
            rows = self.query("SELECT Id FROM PermissionSet WHERE Name='" + name + "'")
            if len(rows) != 1:
                raise SalesforceError("deploy_scoped_metadata_first")
            self.assign("PermissionSetAssignment", uid, rows[0]["Id"], "PermissionSetId")
        # Fail before creating any fixture if an object is still hidden by license/profile/system permissions.
        for role in ("integration", "reviewer"):
            for obj in ("Account", "Contact", "Opportunity", "Task", RECEIPT):
                desc = get_json(self.clients[role], API + "/sobjects/" + obj + "/describe")
                if not desc.get("queryable"):
                    raise SalesforceError("standard_object_read_access_missing")
        for label, obj, suffix, body in (
            ("account", "Account", "account-a", {"Name": "SYNTHETIC GTM native acceptance", "OwnerId": reader,
             "Website": "https://account-04.example", "GTM_Test_Active__c": True}),
            ("other_account", "Account", "account-b", {"Name": "SYNTHETIC GTM wrong-association control", "OwnerId": reader}),
            ("contact", "Contact", "contact-a", {"LastName": "SYNTHETIC GTM Review", "OwnerId": reader,
             "Email": "review+" + s["run_id"] + "@account-04.example", "HasOptedOutOfEmail": False})):
            if label in s["ids"]:
                continue
            marker = s["run_id"] + "/" + suffix
            r = self.clients["administrator"].request("GET", API + "/sobjects/" + obj +
                 "/GTM_Test_Key__c/" + quote(marker, safe=""))
            if r.status_code == 200:
                record = r.json()["Id"]
            elif r.status_code == 404:
                if obj == "Contact":
                    body["AccountId"] = s["ids"]["account"]
                record = self.write(obj, body | {"GTM_Test_Key__c": marker})
            else:
                success(r)
            s["ids"][label] = record
            self.save()
        s["phase"] = "setup"
        self.save()

    def assign(self, obj, uid, grant, field):
        rows = self.query("SELECT Id FROM " + obj + " WHERE AssigneeId='" + uid + "' AND " + field + "='" + grant + "'")
        if rows:
            if not any(x["id"] == rows[0]["Id"] for x in self.state["assignments"]):
                raise SalesforceError("unexpected_preexisting_temporary_grant")
            return
        record = self.write(obj, {"AssigneeId": uid, field: grant})
        self.state["assignments"].append({"object": obj, "id": record})
        self.save()

    def absent(self, key):
        for obj, field in (("Task", "GTM_Action_Key__c"), (RECEIPT, "Action_Key__c")):
            assert not self.query("SELECT Id FROM " + obj + " WHERE " + field + "='" + key + "'")

    def negative(self, crm, label, patch_obj, patch_body, restore):
        target = self.state["ids"]["contact" if patch_obj == "Contact" else "account"]
        self.write(patch_obj, patch_body, target)
        try:
            try:
                crm.resolve()
            except SalesforceError as e:
                self.checks[label + "_client"] = str(e)
            else:
                raise SalesforceError("expected_current_authority_rejection")
            key = digest([self.state["run_id"], label])
            response = crm.writer.request("POST", API + "/sobjects/Task", json=crm.body(key))
            assert response.status_code == 400
            assert "GTM_SCOPE_OR_AUTHORITY_REJECTED" in response.text
            self.absent(key)
            self.checks[label + "_server"] = True
        finally:
            self.write(patch_obj, restore, target)

    def execute(self):
        c, s = self.config, self.state
        scope = Scope(s["run_id"], s["ids"]["account"], s["ids"]["contact"], c["reviewer_user_id"],
                      c["integration_user_id"], c["reviewer_user_id"])
        crm = StandardCRM(self.clients["integration"], self.clients["reviewer"], self.clients["administrator"], self.approval, scope)
        crm.preflight()
        self.checks["effective_object_and_unique_receipt_permissions"] = True
        crm.resolve()
        self.checks["deterministic_identity_owner_contact_and_no_open_opportunity"] = True
        engine = Engine(self.args.workspace / "control.sqlite")
        if not engine.rows("accounts"):
            account, _ = fixture(engine, cases()["cases"][0])
            action = engine.approve(account["id"], engine.prepare(account["id"], SCENARIO), "demo-reviewer", SCENARIO)
            s["local_action"] = action["action_key"]
            self.save()
        dispatcher = TaskDispatcher(engine, crm)
        key = dispatcher.prepare(s["local_action"], SCENARIO)
        s["native_key"] = key
        self.save()
        self.drop = True
        result = dispatcher.dispatch(key, SCENARIO)
        assert result["status"] == "uncertain"
        self.checks["lost_acknowledgement_after_native_commit"] = True
        # New dispatcher, durable journal, independent identity. No second POST.
        posts = sum(r["role"] == "integration" and r["method"] == "POST" for r in self.raw)
        result = TaskDispatcher(engine, crm).dispatch(key, SCENARIO)
        assert result["status"] == "reconciled" and result["receipt"]["task_count"] == 1
        assert posts == sum(r["role"] == "integration" and r["method"] == "POST" for r in self.raw)
        self.checks["restart_receipt_recovery_without_repost"] = True
        self.verified_receipt = result["receipt"]
        receipt = get_json(crm.reader, API + "/sobjects/" + RECEIPT + "/Action_Key__c/" + key)
        s["ids"]["task"] = receipt["Task_Id__c"]
        self.save()
        response = crm.writer.request("POST", API + "/sobjects/Task", json=crm.body(key))
        assert response.status_code == 400 and "DUPLICATE_VALUE" in response.text
        assert crm.receipt(key)["task_count"] == 1
        self.checks["server_duplicate_transaction_rolled_back"] = True
        for obj, record, body in (("Account", scope.account, {"Website": "https://forbidden.example"}),
                                  ("Contact", scope.contact, {"Email": "forbidden@example.invalid"}),
                                  ("Task", s["ids"]["task"], {"Description": "forbidden mutation"})):
            response = crm.writer.request("PATCH", API + "/sobjects/" + obj + "/" + record, json=body)
            assert response.status_code >= 400
            self.checks[obj.lower() + "_mutation_rejected"] = True
        self.negative(crm, "changed_owner", "Account", {"OwnerId": self.admin_id}, {"OwnerId": scope.owner})
        self.negative(crm, "revoked_consent", "Contact", {"HasOptedOutOfEmail": True}, {"HasOptedOutOfEmail": False})
        self.negative(crm, "wrong_contact_account", "Contact", {"AccountId": s["ids"]["other_account"]}, {"AccountId": scope.account})
        self.negative(crm, "disabled_synthetic_scope", "Account", {"GTM_Test_Active__c": False}, {"GTM_Test_Active__c": True})
        stage = self.query("SELECT MasterLabel FROM OpportunityStage WHERE IsActive=true AND IsClosed=false LIMIT 1")[0]["MasterLabel"]
        opp = self.write("Opportunity", {"Name": "SYNTHETIC GTM active-opportunity blocker", "AccountId": scope.account,
                         "OwnerId": scope.owner, "StageName": stage, "CloseDate": "2026-12-01"})
        s["ids"]["opportunity"] = opp
        self.save()
        try:
            crm.resolve()
        except SalesforceError as e:
            assert str(e) == "standard_active_opportunity"
        else:
            raise SalesforceError("active_opportunity_not_blocked")
        blocked_key = digest([s["run_id"], "open-opportunity"])
        response = crm.writer.request("POST", API + "/sobjects/Task", json=crm.body(blocked_key))
        assert response.status_code == 400 and "GTM_SCOPE_OR_AUTHORITY_REJECTED" in response.text
        self.absent(blocked_key)
        self.checks["active_opportunity_client_and_server_rejection"] = True
        # Historical receipt reconciliation remains permitted after NEW action consent is revoked.
        self.write("Contact", {"HasOptedOutOfEmail": True}, scope.contact)
        assert TaskDispatcher(engine, crm).dispatch(key, SCENARIO)["status"] == "reconciled"
        self.checks["historical_receipt_after_consent_revocation"] = True
        fresh_key = digest([s["run_id"], "reviewer-create-probe"])
        response = crm.reader.request("POST", API + "/sobjects/Task", json=crm.body(fresh_key))
        desc = get_json(crm.reader, API + "/sobjects/Task/describe")
        assert response.status_code >= 400 and desc["createable"] is False
        self.absent(fresh_key)
        self.checks["reviewer_effective_create_denial_and_rejected_post"] = True
        # Atomic receipt endpoint cannot be forged through the integration identity.
        response = crm.writer.request("POST", API + "/sobjects/" + RECEIPT, json={"Action_Key__c": fresh_key})
        assert response.status_code >= 400
        self.absent(fresh_key)
        self.checks["direct_receipt_forgery_denied"] = True
        self.checks["final_exact_task_receipt_and_single_effect"] = crm.receipt(key)["exact_content"]
        return crm

    def cleanup(self):
        s = self.state
        if "native_key" in s and "task" not in s["ids"]:
            rows = self.query("SELECT Task_Id__c FROM " + RECEIPT + " WHERE Action_Key__c='" + s["native_key"] + "'")
            if rows:
                s["ids"]["task"] = rows[0]["Task_Id__c"]
                self.save()
        for name, obj, body in (("task", "Task", {"Status": "Completed"}),
                                 ("contact", "Contact", {"HasOptedOutOfEmail": True}),
                                 ("account", "Account", {"GTM_Test_Active__c": False, "OwnerId": self.config["reviewer_user_id"]})):
            if name in s["ids"]:
                self.write(obj, body, s["ids"][name])
        if "opportunity" in s["ids"]:
            closed = self.query("SELECT MasterLabel FROM OpportunityStage WHERE IsActive=true AND IsClosed=true AND IsWon=false LIMIT 1")[0]["MasterLabel"]
            self.write("Opportunity", {"StageName": closed}, s["ids"]["opportunity"])
        verified = {}
        for name, obj, fields, expected in (
            ("task", "Task", "Status", {"Status": "Completed"}),
            ("contact", "Contact", "HasOptedOutOfEmail", {"HasOptedOutOfEmail": True}),
            ("account", "Account", "GTM_Test_Active__c,OwnerId", {"GTM_Test_Active__c": False, "OwnerId": self.config["reviewer_user_id"]})):
            if name in s["ids"]:
                row = get_json(self.clients["administrator"], API + "/sobjects/" + obj + "/" + s["ids"][name], params={"fields": fields})
                assert all(row.get(k) == v for k, v in expected.items()), "cleanup_readback_mismatch"
                verified[name] = True
        for grant in reversed(s["assignments"]):
            response = self.clients["administrator"].request("DELETE", API + "/sobjects/" + grant["object"] + "/" + grant["id"])
            if response.status_code != 404:
                success(response)
        for role in ("administrator", "integration", "reviewer"):
            uid = self.admin_id if role == "administrator" else self.config[role + "_user_id"]
            rows = self.query("SELECT PermissionSetId FROM PermissionSetAssignment WHERE AssigneeId='" + uid + "'")
            assert sorted(r["PermissionSetId"] for r in rows) == s["baseline"][role]
        rows = self.query("SELECT PermissionSetLicenseId FROM PermissionSetLicenseAssign WHERE AssigneeId='" + self.config["integration_user_id"] + "'")
        assert sorted(r["PermissionSetLicenseId"] for r in rows) == s["baseline_psl"]
        if "task" in s["ids"]:
            assert not self.query("SELECT Id FROM Opportunity WHERE AccountId='" + s["ids"]["account"] + "' AND IsClosed=false")
        return {"temporary_assignments_removed": len(s["assignments"]), "original_assignments_restored": True,
                "retained_new_synthetic_records": {k: digest(v) for k, v in s["ids"].items()},
                "readback_verified": verified, "task_status": "Completed" if "task" in verified else None,
                "contact_opted_out": "contact" in verified, "account_disabled": "account" in verified,
                "metadata_retained_unassigned": True}

    def public(self):
        rows = []
        for row in self.raw:
            errors = [v.get("errorCode") for v in row["body"] if isinstance(v, dict)] if isinstance(row["body"], list) else []
            rows.append({k: row[k] for k in ("role", "method", "http", "at")} | {
                "resource": row["path"].split("/sobjects/")[-1].split("/")[0] if "/sobjects/" in row["path"] else "scoped_query_or_identity",
                "error_codes": errors, "response_sha256": digest(row["body"])})
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--admin", default="csa-demo-owner")
    parser.add_argument("--writer", default="csa-demo-integration")
    parser.add_argument("--reader", default="csa-demo-reviewer")
    parser.add_argument("--approved-isolated-writes", action="store_true", required=True)
    args = parser.parse_args()
    # Scope syntax is checked before any write; IDs are verified after deterministic setup.
    import re
    if not re.fullmatch(r"gtm-standard-[a-z0-9-]{8,60}", args.run_id):
        raise SalesforceError("invalid_synthetic_run")
    before = source_hashes()
    run = Run(args)
    status = "failed"
    try:
        run.pin()
        run.setup()
        run.execute()
        status = "passed"
    finally:
        cleanup = run.cleanup() if "baseline" in run.state else {"not_started": True}
        report = {"status": status, "executed_at": datetime.now(timezone.utc).isoformat(), "source_sha256": before,
                  "boundary": "Native synthetic Account/Contact/Task REST execution; no prospect communication or commercial pipeline outcome.",
                  "checks": run.checks, "requests": run.public(), "authenticated_requests": len(run.raw), "cleanup": cleanup,
                  "receipt": getattr(run, "verified_receipt", None), "outreach_salesloft": "not_executed_no_approved_test_environment"}
        assert before == source_hashes(), "executable_source_changed_during_native_run"
        (args.workspace / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        run.state["phase"] = "finished"
        run.save()
        for client in run.clients.values():
            client.close()
    print(json.dumps({"status": status, "requests": len(run.raw), "checks": run.checks, "cleanup_verified": cleanup.get("original_assignments_restored")}))


if __name__ == "__main__":
    main()
