"""Fresh read-only cleanup check; verifies old records as well as the new Task and restored grants."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from gtm.connected import Signal, validate_inference
from gtm.salesforce import API, Approval, SalesforceClient, SalesforceError, get_json
from gtm.standard_crm import Scope, StandardCRM
from gtm.store import canonical, digest
from native_salesforce import authenticate
from publication import source_hashes


def check(args):
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    original = json.loads(args.retained_manifest.read_text(encoding="utf-8"))
    state = json.loads((args.workspace / "private-checkpoint.json").read_text(encoding="utf-8"))
    preview = json.loads((args.workspace / "preview.json").read_text(encoding="utf-8"))
    acceptance = json.loads((args.workspace / "acceptance.json").read_text(encoding="utf-8"))
    scope = Scope(**json.loads((args.workspace / "private-scope.json").read_text(encoding="utf-8")))
    approval = Approval(**configuration["approval"])
    if original["phase"] != state["phase"] or state["phase"] != "finished" or acceptance["status"] != "passed":
        raise SalesforceError("completed_native_runs_required")
    validate_inference(preview["inference"], Signal(**preview["signal"]), preview["crm_context"])
    rows, clients = [], {}
    def observe(role, method, path, response):
        rows.append({"role": role, "method": method, "http": response.status_code,
                     "response_hash": digest(response.json()) if response.content else None,
                     "at": datetime.now(timezone.utc).isoformat()})
    before = source_hashes()
    try:
        for role, alias in (("administrator", args.admin), ("integration", args.writer), ("reviewer", args.reader)):
            clients[role] = SalesforceClient(configuration["instance_url"], authenticate(args.cli, alias),
                lambda m, p, r, role=role: observe(role, m, p, r), read_only=True)
        admin = clients["administrator"]
        approval.verify(get_json(admin, API + "/query", params={"q": "SELECT Id,IsSandbox,OrganizationType FROM Organization"})["records"][0])
        identities = {}
        for role, client in clients.items():
            who = get_json(client, "/services/oauth2/userinfo")
            if who["organization_id"] != approval.org_id or (role != "administrator" and who["user_id"] != configuration[role + "_user_id"]):
                raise SalesforceError("postcheck_pinned_identity_mismatch")
            identities[role] = who["user_id"]
        for role, user in identities.items():
            grants = get_json(admin, API + "/query", params={
                "q": "SELECT PermissionSetId FROM PermissionSetAssignment WHERE AssigneeId='" + user + "'"})
            if not grants["done"] or sorted(r["PermissionSetId"] for r in grants["records"]) != state["baseline"][role]:
                raise SalesforceError("postcheck_permission_baseline_mismatch")
        entitlements = get_json(admin, API + "/query", params={"q": "SELECT PermissionSetLicenseId FROM PermissionSetLicenseAssign WHERE AssigneeId='" + scope.writer + "'"})
        if not entitlements["done"] or sorted(r["PermissionSetLicenseId"] for r in entitlements["records"]) != state["baseline_psl"]:
            raise SalesforceError("postcheck_license_baseline_mismatch")
        expected_old = StandardCRM(None, None, None, approval, scope).envelope(original["native_key"])
        expected_new = StandardCRM(None, None, None, approval, scope).envelope(state["native_key"]) | {
            "version": "gtm-connected-v1", "message": preview["review"]["message"],
            "signal_hash": preview["review"]["signal_hash"], "model_hash": preview["review"]["model_hash"],
            "review_hash": preview["review_hash"], "question_id": preview["review"]["question_id"]}
        verified = {}
        for label, task_id, expected in (("original_task_unchanged", original["ids"]["task"], expected_old),
                                          ("connected_task_completed", state["ids"]["task"], expected_new)):
            task = get_json(admin, API + "/sobjects/Task/" + task_id, params={
                "fields": "Id,Status,WhatId,WhoId,OwnerId,Description"})
            if (task["Description"] != canonical(expected) or task["Status"] != "Completed"
                    or task["WhatId"] != scope.account or task["WhoId"] != scope.contact or task["OwnerId"] != scope.owner):
                raise SalesforceError("postcheck_task_content_or_status_mismatch")
            verified[label] = {"task_hash": digest(task_id), "payload_hash": digest(expected), "exact_content": True}
        opportunity = get_json(admin, API + "/sobjects/Opportunity/" + original["ids"]["opportunity"],
                               params={"fields": "Id,AccountId,IsClosed,IsWon"})
        if opportunity["AccountId"] != scope.account or not opportunity["IsClosed"] or opportunity["IsWon"]:
            raise SalesforceError("original_closed_lost_opportunity_changed")
        boundaries = {}
        for role, obj in (("integration", "Account"), ("integration", "Contact"),
                          ("reviewer", "Account"), ("reviewer", "Contact")):
            response = clients[role].request("GET", API + "/sobjects/" + obj + "/describe")
            if response.status_code != 404:
                raise SalesforceError("restricted_standard_source_visibility_not_restored")
            boundaries[role + ":" + obj] = {"http": 404, "error_codes": [r["errorCode"] for r in response.json()]}
        # Eligibility fields are intentionally hidden again. Their final independent readback is in
        # the immutable acceptance journal, before retiring the grants; do not silently bypass FLS.
        result = {"status": "passed", "read_only": True, "executed_at": datetime.now(timezone.utc).isoformat(),
                  "acceptance_hash": digest(acceptance), "source_sha256": before,
                  "original_assignments_exactly_restored": True, "original_closed_lost_opportunity_unchanged": True,
                  "verified_tasks": verified, "restored_visibility": boundaries,
                  "scope_flags": "disabled/opted-out readback verified in acceptance before grant retirement; now hidden by FLS",
                  "authenticated_requests": len(rows), "requests": rows}
        if source_hashes() != before:
            raise SalesforceError("source_changed_during_postcheck")
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status": "passed", "read_only_requests": len(rows), "old_and_new_tasks": "verified", "permissions": "restored"}))
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--retained-manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--admin", default="csa-demo-owner")
    parser.add_argument("--writer", default="csa-demo-integration")
    parser.add_argument("--reader", default="csa-demo-reviewer")
    parser.add_argument("--output", type=Path, required=True)
    check(parser.parse_args())
