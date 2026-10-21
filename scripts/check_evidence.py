"""Check evidence byte bindings and recorded assertions without describing this as a fresh execution."""
import hashlib
import json

from publication import ROOT, source_hashes


def check():
    report = json.loads((ROOT / "docs/evidence/verification.json").read_text())
    assert report["source_sha256"] == source_hashes(), "executed_evidence_source_mismatch"
    assert report["tests"]["tests"] >= 65
    assert all(report["tests"][k] == 0 for k in ("failures", "errors", "skipped"))
    provenance = json.loads((ROOT / "docs/images/provenance.json").read_text())
    assert provenance["source_sha256"] == source_hashes(), "browser_source_mismatch"
    for name, fingerprint in provenance["image_sha256"].items():
        assert hashlib.sha256((ROOT / "docs/images" / name).read_bytes()).hexdigest() == fingerprint
    assert not provenance["page_errors"] and all(provenance["no_page_overflow"].values())
    assert provenance["new_action_attempts"] == 1 and provenance["new_action_status"] == "reconciled"
    print("Recorded source, browser and image bindings verified; no fresh vendor or model execution implied.")


if __name__ == "__main__":
    check()
