"""Verify immutable historical executions and current regression/browser evidence separately."""
import hashlib
import json
import subprocess

from gtm.advice import validate_model_text
from gtm.store import digest
from publication import ROOT, source_hashes

BASELINE = "601d3865e40c4e62836adafa01e377a1579468ec"
NATIVE_AI = "4b06935b23edee3045a58553ec9fcdf2fa056084"
NATIVE_UI = "644065dd561019b351ca7330d2146fd4c10e1d66"
ENTERPRISE = "9f13ea79977dda1b56f25df5ca5c4060ffaf345f"
STANDARD = "c54503f00e65ad4195a74c0bacf2ce003add091c"
CLEANUP = "36fd314015812f2114d5e96a0cbbaee24b17b2e4"
CAD_UI = "62e48215a3609ba136f4ce581f98cc893e2378d9"
USD_UI = "6da3603a8e447dacfdbde25a8aab5c5fa3721328"


def blob(revision, path):
    return subprocess.run(["git", "show", revision + ":" + path], cwd=ROOT, capture_output=True, check=True).stdout


def historical(report, revision):
    for path, fingerprint in report["source_sha256"].items():
        assert hashlib.sha256(blob(revision, path)).hexdigest() == fingerprint, "historical_source_mismatch:" + path


def browser(path, current, revision=BASELINE):
    provenance = json.loads(path.read_text())
    if current:
        assert provenance["source_sha256"] == source_hashes(), "browser_source_mismatch"
    else:
        historical(provenance, revision)
        assert path.read_bytes() == blob(revision, path.relative_to(ROOT).as_posix())
    for name, fingerprint in provenance["image_sha256"].items():
        assert hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == fingerprint
    assert not provenance["page_errors"] and all(provenance["no_page_overflow"].values())
    assert provenance["new_action_attempts"] == 1 and provenance["new_action_status"] == "reconciled"


def check():
    # Full history is intentional: a ZIP runs the core verifier; history attestation needs a clone.
    report = json.loads((ROOT / "docs/evidence/verification.json").read_text())
    historical(report, BASELINE)
    for path in ["docs/evidence/verification.json", "docs/evidence/tests.xml", "docs/evidence/demo.json",
                 "docs/evidence/README.md", "docs/images/provenance.json"]:
        assert (ROOT / path).read_bytes() == blob(BASELINE, path), "historical_record_rewritten:" + path
    assert report["tests"]["tests"] == 73
    browser(ROOT / "docs/images/provenance.json", False)
    historical(json.loads((ROOT / "docs/evidence/native-ai/local/verification.json").read_text()), NATIVE_UI)
    for name in ("verification.json", "tests.xml", "demo.json"):
        path = "docs/evidence/native-ai/local/" + name
        assert (ROOT / path).read_bytes() == blob(NATIVE_UI, path), "historical_upgrade_record_rewritten"
    browser(ROOT / "docs/images/native-ai/provenance.json", False, NATIVE_UI)
    historical(json.loads((ROOT / "docs/evidence/enterprise/verification.json").read_text()), ENTERPRISE)
    for folder in ("docs/evidence/enterprise", "docs/images/enterprise"):
        paths = subprocess.run(["git", "ls-tree", "-r", "--name-only", ENTERPRISE, folder], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.splitlines()
        for path in paths:
            assert (ROOT / path).read_bytes() == blob(ENTERPRISE, path), "enterprise_history_rewritten:" + path
    browser(ROOT / "docs/images/enterprise/provenance.json", False, ENTERPRISE)
    historical(json.loads((ROOT / "docs/evidence/salesforce-standard/local/verification.json").read_text()), CAD_UI)
    for folder in ("docs/evidence/salesforce-standard", "docs/images/salesforce-standard"):
        paths = subprocess.run(["git", "ls-tree", "-r", "--name-only", CAD_UI, folder], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.splitlines()
        for path in paths:
            assert (ROOT / path).read_bytes() == blob(CAD_UI, path), "native_or_cad_history_rewritten:" + path
    browser(ROOT / "docs/images/salesforce-standard/provenance.json", False, CAD_UI)
    for folder in ("docs/evidence/enterprise-usd", "docs/images/enterprise-usd"):
        paths = subprocess.run(["git", "ls-tree", "-r", "--name-only", USD_UI, folder], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.splitlines()
        for path in paths:
            assert (ROOT / path).read_bytes() == blob(USD_UI, path), "usd_history_rewritten:" + path
    historical(json.loads((ROOT / "docs/evidence/enterprise-usd/verification.json").read_text()), USD_UI)
    browser(ROOT / "docs/images/enterprise-usd/provenance.json", False, USD_UI)
    current = json.loads((ROOT / "docs/evidence/connected/local/verification.json").read_text())
    assert current["source_sha256"] == source_hashes(), "current_executed_source_mismatch"
    assert current["tests"]["tests"] >= 163 and current["independent_demo_runs"] == 4
    assert all(current["tests"][k] == 0 for k in ("failures", "errors", "skipped"))
    browser(ROOT / "docs/images/connected/provenance.json", True)
    connected_browser = json.loads((ROOT / "docs/images/connected/provenance.json").read_text())
    connected_preview = json.loads((ROOT / "docs/evidence/connected/preview.json").read_text())
    assert connected_browser["connected_execution"]["preview_hash"] == digest(connected_preview)
    assert connected_browser["connected_execution"]["review_hash"] == connected_preview["review_hash"]
    assert connected_browser["connected_execution"]["native_status"] == "passed"
    assert all(connected_browser["connected_layout_checks"].values())
    usd = json.loads((ROOT / "docs/evidence/enterprise-usd/demo.json").read_text())
    assert usd["scenario"]["currency"] == usd["measurement"]["currency"] == usd["financial_audit"]["currency"] == "USD"
    assert usd["scenario"]["locale"] == "en-US"
    usd_browser = json.loads((ROOT / "docs/images/enterprise-usd/provenance.json").read_text())
    assert usd_browser["currency"] == usd["scenario"]["currency"]
    assert usd_browser["locale"] == usd["scenario"]["locale"]
    outcomes = [json.loads(s["payload"])["data"] for s in usd["source_records"] if s["kind"] == "outcome"]
    assert all(r["currency"] == "USD" for r in outcomes)
    assert sum(r["amount_cents"] for r in outcomes if r["kind"] == "opportunity_accepted") == usd["financial_audit"]["pipeline_cents"] == 346000000
    assert json.loads((ROOT / "docs/evidence/enterprise-usd/fixture-demo.json").read_text()) == json.loads((ROOT / "docs/evidence/demo.json").read_text())
    fixture = json.loads((ROOT / "docs/evidence/enterprise/fixture-demo.json").read_text())
    assert fixture == json.loads((ROOT / "docs/evidence/demo.json").read_text())
    enterprise = json.loads((ROOT / "docs/evidence/enterprise/demo.json").read_text())
    amounts = [json.loads(s["payload"])["data"]["amount_cents"] for s in enterprise["source_records"]
               if s["kind"] == "outcome" and json.loads(s["payload"])["data"]["kind"] == "opportunity_accepted"]
    assert len(amounts) == 5 and sum(amounts) == 346000000
    assert enterprise["financial_audit"]["pipeline_cents"] == sum(amounts)
    ai = json.loads((ROOT / "docs/evidence/native-ai/ai-evaluation.json").read_text())
    native = json.loads((ROOT / "docs/evidence/native-ai/salesforce-acceptance.json").read_text())
    for name, record in [("ai-evaluation.json", ai), ("salesforce-acceptance.json", native)]:
        historical(record, NATIVE_AI)
        assert (ROOT / "docs/evidence/native-ai" / name).read_bytes() == blob(NATIVE_AI, "docs/evidence/native-ai/" + name)
    assert ai["inferences_executed"] == len(ai["records"]) == 16
    exact = 0
    for record in ai["records"]:
        assert record["context_hash"] == digest(record["context"])
        assert record["inference"] == "executed" and record["advisory_only"]
        try:
            validate_model_text(record["raw_response"], record["context"])
        except ValueError as error:
            assert record["validation_error"] == str(error)
        else:
            assert record["validation_error"] is None
            exact += 1
    assert ai["exact_citation_checks_passed"] == exact
    assert native["status"] == "passed" and all(native["checks"].values())
    assert native["authenticated_requests"] == len(native["requests"]) == 29
    assert native["cleanup"]["new_review_status"] == "Rejected" and native["cleanup"]["readback_verified"]
    assert all(r["method"] == "GET" for r in native["requests"] if r["role"] == "administrator")
    assert native["advisory_reference"]["request_hash"] == ai["records"][0]["request_hash"]
    standard_path = "docs/evidence/salesforce-standard/acceptance.json"
    standard = json.loads((ROOT / standard_path).read_text())
    historical(standard, STANDARD)
    assert (ROOT / standard_path).read_bytes() == blob(STANDARD, standard_path)
    assert standard["status"] == "passed" and all(standard["checks"].values())
    assert standard["authenticated_requests"] == len(standard["requests"]) == 140
    assert standard["receipt"]["task_count"] == 1 and standard["receipt"]["exact_content"]
    assert standard["cleanup"]["original_assignments_restored"]
    assert standard["cleanup"]["temporary_assignments_removed"] == 4
    assert all(standard["cleanup"]["readback_verified"].values())
    cleanup_path = "docs/evidence/salesforce-standard/post-cleanup.json"
    cleanup = json.loads((ROOT / cleanup_path).read_text())
    historical(cleanup, CLEANUP)
    assert (ROOT / cleanup_path).read_bytes() == blob(CLEANUP, cleanup_path)
    assert cleanup["status"] == "passed" and cleanup["read_only"]
    assert cleanup["authenticated_requests"] == len(cleanup["requests"]) == 20
    assert all(r["method"] == "GET" for r in cleanup["requests"])
    assert cleanup["original_assignments_exactly_restored"] and cleanup["original_custom_review_boundaries_preserved"]
    details = json.loads((ROOT / "docs/evidence/salesforce-standard/native-details.json").read_text())
    assert details["derived_from_acceptance_sha256"] == digest(standard)
    for rejection in details["rejected_operations"]:
        assert rejection["response_sha256"] == standard["requests"][rejection["request_index"]]["response_sha256"]
    rel = details["relationships"]
    assert rel["account_id_hash"] == rel["contact_account_id_hash"] == rel["task_account_id_hash"]
    assert rel["contact_id_hash"] == rel["task_contact_id_hash"]
    assert rel["account_owner_hash"] == rel["contact_owner_hash"] == rel["task_owner_hash"] == rel["independent_reader_hash"]
    assert rel["task_created_by_hash"] != rel["independent_reader_hash"]
    assert details["apex_deployment"]["tests_completed"] == 3 and details["apex_deployment"]["tests_failed"] == 0
    from check_connected import check as check_connected
    check_connected()
    print("Historical and native/model executions match pinned Git bytes; current tests, UI and images match source.")


if __name__ == "__main__":
    check()
