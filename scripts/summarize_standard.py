"""Derive reviewed, identifier-free native detail from a private response journal."""
import argparse
import json
import re
from pathlib import Path

from gtm.standard_crm import REQUIRED_FIELDS
from gtm.store import digest


def summarize(workspace, deployment, output):
    raw = json.loads((workspace / "private-responses.json").read_text())
    report = json.loads((workspace / "verification.json").read_text())
    state = json.loads((workspace / "private-checkpoint.json").read_text())
    assert report["status"] == "passed"
    assert [digest(r["body"]) for r in raw] == [r["response_sha256"] for r in report["requests"]]
    ids = set(re.findall(r"\b(?:00[A-Za-z0-9]|01[A-Za-z0-9]|0P[A-Za-z0-9]|a[A-Za-z0-9]{2})[A-Za-z0-9]{15}\b", json.dumps(raw)))
    def safe(message):
        for value in ids:
            message = message.replace(value, "[record-id]")
        assert not re.search(r"https://|@|Bearer ", message)
        return message
    errors = []
    for index, row in enumerate(raw):
        if row["http"] >= 400 and isinstance(row["body"], list):
            errors.append({"request_index": index, "http": row["http"], "role": row["role"],
                           "response_sha256": digest(row["body"]),
                           "errors": [{"code": e.get("errorCode"), "message": safe(e.get("message", ""))}
                                      for e in row["body"] if isinstance(e, dict)]})
    permissions = {}
    fields = REQUIRED_FIELDS
    for row in raw:
        if row["path"].endswith("/describe") and row["role"] != "administrator" and row["http"] == 200:
            obj = row["path"].split("/")[-2]
            if obj in fields:
                desc = row["body"]
                permissions.setdefault(row["role"], {})[obj] = {
                    **{k: desc[k] for k in ("queryable", "createable", "updateable", "deletable")},
                    "fields": {f["name"]: {k: f.get(k) for k in ("createable", "updateable", "unique", "externalId")}
                               for f in desc["fields"] if f["name"] in fields[obj]}}
    task = next(r["body"] for r in raw if r["role"] == "reviewer" and r["method"] == "GET" and
                isinstance(r["body"], dict) and r["body"].get("Id") == state["ids"]["task"])
    contact = next(r["body"] for r in raw if r["role"] == "integration" and r["method"] == "GET" and
                   isinstance(r["body"], dict) and r["body"].get("Id") == state["ids"]["contact"])
    account = next(r["body"] for r in raw if r["role"] == "integration" and r["method"] == "GET" and
                   isinstance(r["body"], dict) and r["body"].get("Id") == state["ids"]["account"])
    relationships = {"account_id_hash": digest(account["Id"]), "contact_account_id_hash": digest(contact["AccountId"]),
                     "task_account_id_hash": digest(task["WhatId"]), "contact_id_hash": digest(contact["Id"]),
                     "task_contact_id_hash": digest(task["WhoId"]), "account_owner_hash": digest(account["OwnerId"]),
                     "contact_owner_hash": digest(contact["OwnerId"]), "task_owner_hash": digest(task["OwnerId"]),
                     "task_created_by_hash": digest(task["CreatedById"]), "independent_reader_hash": digest(task["OwnerId"])}
    result = json.loads(deployment.read_text())["result"]
    assert result["status"] == "Succeeded" and result["numberTestsCompleted"] == 3
    apex = result["details"]["runTestResult"]
    details = {"derived_from_acceptance_sha256": digest(report), "effective_permissions": permissions,
               "relationships": relationships, "rejected_operations": errors,
               "apex_deployment": {"status": result["status"], "tests_completed": result["numberTestsCompleted"],
                                   "tests_failed": result["numberTestErrors"],
                                   "successes": [{k: row.get(k) for k in ("name", "methodName", "time")} for row in apex["successes"]],
                                   "coverage": [{k: row.get(k) for k in ("name", "type", "numLocations", "numLocationsNotCovered")}
                                                for row in apex["codeCoverage"]]},
               "boundary": "Sanitized derivation of recorded native responses; hashes are not vendor signatures."}
    output.write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.workspace, args.deployment, args.output)
