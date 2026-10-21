"""Verify immutable historical executions and current regression/browser evidence separately."""
import hashlib
import json
import subprocess

from gtm.advice import validate_model_text
from gtm.store import digest
from publication import ROOT, source_hashes

BASELINE = "601d3865e40c4e62836adafa01e377a1579468ec"
NATIVE_AI = "4b06935b23edee3045a58553ec9fcdf2fa056084"


def blob(revision, path):
    return subprocess.run(["git", "show", revision + ":" + path], cwd=ROOT, capture_output=True, check=True).stdout


def historical(report, revision):
    for path, fingerprint in report["source_sha256"].items():
        assert hashlib.sha256(blob(revision, path)).hexdigest() == fingerprint, "historical_source_mismatch:" + path


def browser(path, current):
    provenance = json.loads(path.read_text())
    if current:
        assert provenance["source_sha256"] == source_hashes(), "browser_source_mismatch"
    else:
        historical(provenance, BASELINE)
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
    current = json.loads((ROOT / "docs/evidence/native-ai/local/verification.json").read_text())
    assert current["source_sha256"] == source_hashes(), "current_executed_source_mismatch"
    assert current["tests"]["tests"] >= 108
    assert all(current["tests"][k] == 0 for k in ("failures", "errors", "skipped"))
    browser(ROOT / "docs/images/native-ai/provenance.json", True)
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
    print("Historical and native/model executions match pinned Git bytes; current tests, UI and images match source.")


if __name__ == "__main__":
    check()
