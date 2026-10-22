"""Read-only native context and one fresh local inference. This command cannot write Salesforce."""
import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from gtm.connected import Signal, infer_signal, ingest_signal, mirror_account, prepare_review
from gtm.engine import Engine
from gtm.salesforce import API, Approval, SalesforceClient, SalesforceError, get_json
from gtm.standard_crm import Scope
from gtm.store import digest
from native_salesforce import authenticate


def read_context(client, approval, scope):
    approval.verify(get_json(client, API + "/query", params={
        "q": "SELECT Id,IsSandbox,OrganizationType FROM Organization"})["records"][0])
    identity = get_json(client, "/services/oauth2/userinfo")
    if identity.get("organization_id") != approval.org_id:
        raise SalesforceError("pinned_org_mismatch")
    # Restored administrator FLS may hide the custom scope fields. Do not bypass that boundary.
    account = get_json(client, API + "/sobjects/Account/" + scope.account,
                       params={"fields": "Id,Name,OwnerId,Website"})
    visible = {f["name"] for f in get_json(client, API + "/sobjects/Contact/describe")["fields"]}
    contact_fields = {"Id", "LastName", "AccountId", "OwnerId", "Email"}
    if not contact_fields <= visible:
        raise SalesforceError("standard_context_field_hidden")
    contact = get_json(client, API + "/sobjects/Contact/" + scope.contact,
                       params={"fields": ",".join(sorted(contact_fields | ({"HasOptedOutOfEmail"} & visible)))})
    if (not account["Name"].startswith("SYNTHETIC GTM") or not contact["LastName"].startswith("SYNTHETIC GTM")
            or account["Website"] != "https://account-04.example"
            or contact["Email"] != "review+" + scope.run_id + "@account-04.example"
            or contact["AccountId"] != scope.account
            or account["OwnerId"] != scope.owner or contact["OwnerId"] != scope.owner):
        raise SalesforceError("existing_synthetic_identity_mismatch")
    opp = get_json(client, API + "/query", params={
        "q": "SELECT Id FROM Opportunity WHERE AccountId='" + scope.account + "' AND IsClosed=false LIMIT 1"})
    if opp["totalSize"] != 0 or not opp["done"]:
        raise SalesforceError("standard_active_opportunity")
    return {"environment": approval.environment, "domain": "account-04.example",
            "account_hash": digest(scope.account), "contact_hash": digest(scope.contact),
            "owner_hash": digest(scope.owner), "contact_account_hash": digest(contact["AccountId"]),
            "account_owner_hash": digest(account["OwnerId"]), "contact_owner_hash": digest(contact["OwnerId"]),
            "active_opportunities": 0, "account_active": "custom_field_requires_scoped_setup_permission",
            "contact_opted_out": contact.get("HasOptedOutOfEmail", "field_requires_scoped_setup_permission"),
            "identity_match": "pinned retained journal + synthetic names + reserved domain + contact relation + owner",
            "execution_precondition": "Exact unique custom CRM keys and active scope must be reverified after temporary setup permission; no Task before that check.",
            "proposed_test_authorization": "Temporarily activate only these retained synthetic records, then restore both flags.",
            "fit_and_intent": "240 employees / software / research are explicit synthetic scenario inputs, not vendor enrichment."}


def prepare(args):
    if args.workspace.exists():
        raise SalesforceError("fresh_connected_workspace_required")
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    manifest = json.loads(args.scope_manifest.read_text(encoding="utf-8"))
    if manifest.get("phase") != "finished":
        raise SalesforceError("prior_native_cleanup_must_be_finished")
    scope = Scope(manifest["run_id"], manifest["ids"]["account"], manifest["ids"]["contact"],
                  configuration["reviewer_user_id"], configuration["integration_user_id"], configuration["reviewer_user_id"])
    approval = Approval(**configuration["approval"])
    observed = []
    def observe(method, path, response):
        observed.append({"method": method, "http": response.status_code, "response_hash": digest(response.json()),
                         "at": datetime.now(timezone.utc).isoformat()})
    client = SalesforceClient(configuration["instance_url"], authenticate(args.cli, args.admin), observe, read_only=True)
    try:
        context = read_context(client, approval, scope)
    finally:
        client.close()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signal = Signal(args.source_key, now)
    engine = Engine(args.workspace / "control.sqlite")
    account = mirror_account(engine, now)
    first = ingest_signal(engine, signal, account, now)
    duplicate = ingest_signal(engine, signal, account, now)
    cohort = engine.assign(account["id"], now)
    if cohort["arm"] != "treatment":
        raise SalesforceError("existing_policy_assignment_is_not_treatment")
    model = infer_signal(signal, context, args.origin, args.token_file.read_text(encoding="utf-8").strip())
    # Preserve even a rejected model response. No fallback text masquerades as a real response.
    output = {"status": "model_rejected" if model["validation_error"] else "awaiting_exact_review",
              "executed_at": datetime.now(timezone.utc).isoformat(), "review_clock": now,
              "signal": asdict(signal), "crm_context": context, "native_read_only": observed,
              "signal_ingestion": first, "repeated_source": duplicate, "inference": model,
              "native_task": "not_executed", "prospect_communications": "not_executed",
              "boundary": "Fresh inference uses actual read-only Salesforce context. Native Task requires separate exact review and scoped test activation."}
    if not model["validation_error"]:
        output["review"] = prepare_review(engine, account, now, signal, context, model)
        output["review_hash"] = digest(output["review"])
    bindings = ["src/gtm/connected.py", "src/gtm/engine.py", "src/gtm/contracts.py", "src/gtm/store.py",
                "src/gtm/fixtures.py", "src/gtm/policy.json", "src/gtm/schema.sql", "scripts/connected_prepare.py",
                "scripts/native_salesforce.py", "src/gtm/salesforce.py", "src/gtm/standard_crm.py"]
    root = Path(__file__).resolve().parents[1]
    output["source_sha256"] = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in bindings}
    runtime = subprocess.run([str(args.runtime), "--version"], capture_output=True, text=True,
                             encoding="utf-8", timeout=30, check=True)
    with args.weights.open("rb") as weights:
        weights_hash = hashlib.file_digest(weights, "sha256").hexdigest()
    output["runtime"] = {"version": (runtime.stdout + runtime.stderr).strip(),
                         "executable_sha256": hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
                         "weights_sha256": weights_hash, "model": "Qwen3-14B Q4_K_M",
                         "backend": "existing local Vulkan runtime; loopback only"}
    (args.workspace / "preview.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.workspace / "private-scope.json").write_text(json.dumps(asdict(scope), indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "native_gets": len(observed), "fresh_inferences": 1,
                      "review_hash": output.get("review_hash"), "native_writes": 0}))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scope-manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--admin", default="csa-demo-owner")
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:8093")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    prepare(parser.parse_args())
