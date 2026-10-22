"""Offline connected-execution lineage checks. No model or vendor calls."""
import hashlib
import json
import subprocess

from gtm.connected import Signal, message, validate_inference
from gtm.store import digest
from publication import ROOT

CONNECTED_REVISION = "e20b9fef9ad03ab061857d2d4f7098fa20fbf25e"


def recorded_source(path):
    return subprocess.run(["git", "show", CONNECTED_REVISION + ":" + path],
                          cwd=ROOT, capture_output=True, check=True).stdout


def check():
    folder = ROOT / "docs/evidence/connected"
    preview = json.loads((folder / "preview.json").read_text(encoding="utf-8"))
    signal = Signal(**preview["signal"])
    context = preview["crm_context"]
    brief = validate_inference(preview["inference"], signal, context)
    assert preview["review"]["message"] == message(brief)
    assert preview["review_hash"] == digest(preview["review"])
    assert preview["review"]["model_hash"] == digest(preview["inference"])
    assert preview["review"]["signal_hash"] == digest(preview["signal"])
    assert preview["signal_ingestion"]["source_hash"] == digest(preview["signal"])
    assert preview["repeated_source"]["status"] == "duplicate"
    assert preview["signal_ingestion"]["classification"] == "research"
    assert context["account_hash"] == context["contact_account_hash"]
    assert context["owner_hash"] == context["account_owner_hash"] == context["contact_owner_hash"]
    assert context["active_opportunities"] == 0
    assert preview["native_task"] == preview["prospect_communications"] == "not_executed"
    assert len(preview["native_read_only"]) == 6
    assert all(r["method"] == "GET" and r["http"] == 200 for r in preview["native_read_only"])
    for path, checksum in preview["source_sha256"].items():
        assert hashlib.sha256(recorded_source(path)).hexdigest() == checksum, "inference_source_changed:" + path
    native_path = folder / "acceptance.json"
    if not native_path.exists():
        return {"fresh_inference": "verified", "native_context": "six_authenticated_GETs", "native_task": "not_executed"}
    native = json.loads(native_path.read_text(encoding="utf-8"))
    versions = json.loads((folder / "execution-source.json").read_text(encoding="utf-8"))
    assert versions["acceptance_hash"] == digest(native)
    assert native["preview_hash"] == digest(preview)
    assert native["review_hash"] == preview["review_hash"]
    assert native["authenticated_requests"] == len(native["requests"])
    for path, checksum in native["source_sha256"].items():
        executed = subprocess.run(["git", "show", versions["native_revision"] + ":" + path],
                                  cwd=ROOT, capture_output=True, check=True).stdout
        assert hashlib.sha256(executed).hexdigest() == checksum, "native_source_mismatch:" + path
        if path not in versions["post_execution_hardened_files"]:
            assert hashlib.sha256(recorded_source(path)).hexdigest() == checksum, "native_dependency_changed:" + path
    assert native["status"] == "passed" and all(native["checks"].values())
    assert native["receipt"]["exact_content"] and native["receipt"]["task_count"] == 1
    assert native["cleanup"]["original_assignments_restored"]
    assert native["cleanup"]["temporary_assignments_removed"] == 4
    assert native["cleanup"]["account_disabled"] and native["cleanup"]["contact_opted_out"]
    assert native["cleanup"]["task_status"] == "Completed"
    assert native["content"]["message"] == preview["review"]["message"]
    assert native["content"]["signal_hash"] == preview["review"]["signal_hash"]
    assert native["content"]["model_hash"] == preview["review"]["model_hash"]
    assert native["content"]["review_hash"] == preview["review_hash"]
    assert native["content"]["payload_hash"] == native["receipt"]["payload_hash"]
    r = native["relationships"]
    assert r["account_hash"] == r["contact_account_hash"] == r["task_account_hash"] == context["account_hash"]
    assert r["contact_hash"] == r["task_contact_hash"] == context["contact_hash"]
    assert r["owner_hash"] == r["task_owner_hash"] == r["reader_hash"] == context["owner_hash"]
    assert r["task_created_by_hash"] == r["writer_hash"] != r["reader_hash"]
    assert r["task_description_hash"] == native["receipt"]["payload_hash"]
    apex = json.loads((folder / "apex.json").read_text(encoding="utf-8"))
    assert apex["status"] == "Succeeded" and apex["tests_completed"] == 5 and apex["tests_failed"] == apex["component_errors"] == 0
    hardening = json.loads((folder / "apex-owner-hardening.json").read_text(encoding="utf-8"))
    assert hardening["status"] == "Succeeded" and hardening["tests_completed"] == 5
    assert hardening["tests_failed"] == hardening["component_errors"] == 0
    assert set(versions["post_execution_hardened_files"]) == set(hardening["source_sha256"])
    for path, checksum in hardening["source_sha256"].items():
        assert hashlib.sha256(recorded_source(path)).hexdigest() == checksum
    post = json.loads((folder / "post-cleanup.json").read_text(encoding="utf-8"))
    assert post["status"] == "passed" and post["read_only"] and post["acceptance_hash"] == digest(native)
    assert post["original_assignments_exactly_restored"] and post["original_closed_lost_opportunity_unchanged"]
    assert post["authenticated_requests"] == len(post["requests"])
    assert all(r["method"] == "GET" for r in post["requests"])
    for label in ("original_task_unchanged", "connected_task_completed"):
        assert post["verified_tasks"][label]["exact_content"]
    assert post["verified_tasks"]["connected_task_completed"]["payload_hash"] == native["receipt"]["payload_hash"]
    for path, checksum in post["source_sha256"].items():
        assert hashlib.sha256(recorded_source(path)).hexdigest() == checksum, "postcheck_source_changed:" + path
    return {"fresh_inference": "verified", "native_task": "exact_content_and_relationships_verified",
            "authenticated_requests": native["authenticated_requests"], "cleanup": "verified"}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
