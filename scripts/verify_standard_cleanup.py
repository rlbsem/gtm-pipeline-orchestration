"""Fresh read-only permission and retained-Task checks after native acceptance cleanup."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from gtm.salesforce import API, Approval, SalesforceClient, get_json
from gtm.standard_crm import Scope, StandardCRM
from gtm.store import digest
from native_salesforce import authenticate
from publication import source_hashes


def verify(args):
    config = json.loads(args.config.read_text())
    state = json.loads((args.workspace / "private-checkpoint.json").read_text())
    approval = Approval(**config["approval"])
    raw, clients, objects = [], {}, {}
    def observe(role, method, path, response):
        assert method == "GET"
        raw.append({"role": role, "method": method, "path": path, "http": response.status_code,
                    "body": response.json() if response.content else None})
        (args.workspace / "private-post-cleanup-responses.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    try:
        for role, alias in (("administrator", args.admin), ("integration", args.writer), ("reviewer", args.reader)):
            clients[role] = SalesforceClient(config["instance_url"], authenticate(args.cli, alias),
                lambda method, path, response, r=role: observe(r, method, path, response), read_only=True)
            who = get_json(clients[role], "/services/oauth2/userinfo")
            assert who["organization_id"] == approval.org_id
            if role == "administrator":
                admin_id = who["user_id"]
            else:
                assert who["user_id"] == config[role + "_user_id"]
        admin = clients["administrator"]
        def query(q):
            result = get_json(admin, API + "/query", params={"q": q})
            assert result["done"]
            return result["records"]
        approval.verify(query("SELECT Id,IsSandbox,OrganizationType FROM Organization")[0])
        for role, client in clients.items():
            uid = admin_id if role == "administrator" else config[role + "_user_id"]
            assert sorted(r["PermissionSetId"] for r in query(
                "SELECT PermissionSetId FROM PermissionSetAssignment WHERE AssigneeId='" + uid + "'")) == state["baseline"][role]
            if role != "administrator":
                objects[role] = {}
                for obj in ("Account", "Contact", "Opportunity", "Task", "Seller_Action__c"):
                    response = client.request("GET", API + "/sobjects/" + obj + "/describe")
                    entry = {"http": response.status_code}
                    if response.status_code == 200:
                        entry.update({k: response.json()[k] for k in ("queryable", "createable", "updateable", "deletable")})
                    objects[role][obj] = entry
        assert sorted(r["PermissionSetLicenseId"] for r in query(
            "SELECT PermissionSetLicenseId FROM PermissionSetLicenseAssign WHERE AssigneeId='" + config["integration_user_id"] + "'")) == state["baseline_psl"]
        assert all(objects["integration"][o]["http"] == 404 for o in ("Account", "Contact", "Opportunity", "Task"))
        assert objects["integration"]["Seller_Action__c"]["createable"] is True
        assert objects["reviewer"]["Seller_Action__c"]["createable"] is False
        assert objects["reviewer"]["Seller_Action__c"]["updateable"] is True
        assert objects["reviewer"]["Task"]["createable"] is False
        scope = Scope(state["run_id"], state["ids"]["account"], state["ids"]["contact"], config["reviewer_user_id"],
                      config["integration_user_id"], config["reviewer_user_id"])
        crm = StandardCRM(clients["integration"], clients["reviewer"], admin, approval, scope)
        task = get_json(admin, API + "/sobjects/Task/" + state["ids"]["task"], params={
            "fields": "Id,Status,WhatId,WhoId,OwnerId,CreatedById,Subject,Description"})
        expected = crm.body(state["native_key"])
        assert all(task[k] == expected[k] for k in ("WhatId", "WhoId", "OwnerId", "Subject", "Description"))
        assert task["Status"] == "Completed" and task["CreatedById"] == scope.writer
        opportunity = get_json(admin, API + "/sobjects/Opportunity/" + state["ids"]["opportunity"], params={"fields": "IsClosed,IsWon,AccountId"})
        assert opportunity["IsClosed"] is True and opportunity["IsWon"] is False and opportunity["AccountId"] == scope.account
        report = {"status": "passed", "executed_at": datetime.now(timezone.utc).isoformat(), "read_only": True,
                  "source_sha256": source_hashes(), "authenticated_requests": len(raw), "original_assignments_exactly_restored": True,
                  "original_custom_review_boundaries_preserved": True, "post_cleanup_effective_access": objects,
                  "completed_task_content_and_relationships_unchanged": True, "task_id_hash": digest(task["Id"]),
                  "synthetic_blocker_closed_lost": True,
                  "requests": [{"role": r["role"], "method": r["method"], "http": r["http"],
                                "response_sha256": digest(r["body"])} for r in raw]}
        (args.workspace / "post-cleanup.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({k: report[k] for k in ("status", "read_only", "authenticated_requests", "original_assignments_exactly_restored")}))
    finally:
        for client in clients.values():
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--admin", default="csa-demo-owner")
    parser.add_argument("--writer", default="csa-demo-integration")
    parser.add_argument("--reader", default="csa-demo-reviewer")
    verify(parser.parse_args())
