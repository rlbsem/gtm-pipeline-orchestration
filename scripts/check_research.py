"""Recompute research lineage, actual request contracts and rubric counts, entirely offline."""
import hashlib
import json

from gtm.research import validate_brief
from gtm.store import digest
from publication import ROOT, source_hashes
from research_evaluate import contract_assessment


def check(images=None):
    folder = ROOT / "docs/evidence/research"
    combined = json.loads((folder / "evaluation.json").read_text())
    records = []
    for item in combined["rounds"]:
        report = json.loads((folder / item["evaluation"]).read_text())
        sources = json.loads((folder / item["sources"]).read_text())
        for name, expected in report["source_sha256"].items():
            assert hashlib.sha256(sources[name].encode()).hexdigest() == expected, "executed_research_source_mismatch:"+name
        dataset = json.loads(sources["src/gtm/research-scenario.json"])
        for r in report["records"]:
            case = next(c for c in dataset["cases"] if c["id"] == r["case_id"])
            assert r["context"] == {k: v for k, v in case.items() if k != "rubric"}
            assert r["context_hash"] == digest(r["context"]) and r["request_hash"] == digest(r["request"])
            assert json.loads(r["request"]["messages"][1]["content"]) == r["context"]
            assert r["request"]["messages"][0]["content"] == r["prompt"]
            assert r["inference"] == "executed" and r["latency_seconds"] > 0 and r["usage"]["completion_tokens"] > 0
            assert r["source_sha256"] == report["source_sha256"]
            try:
                parsed = validate_brief(r["raw_response"], r["context"])
            except ValueError as error:
                assert r["parsed"] is None and r["error"] == str(error)
            else:
                assert r["error"] is None and r["parsed"] == parsed
            assert r["contract_assessment"] == contract_assessment(r, case["rubric"])
        for approach, stats in report["comparisons"].items():
            subset = [r for r in report["records"] if r["approach"] == approach]
            assert stats["responses"] == len(subset)
            assert stats["contract_passes"] == sum(all(r["contract_assessment"].values()) for r in subset)
        records.extend(report["records"])
    assert records == combined["records"] and len(records) == 40
    assessment = json.loads((folder / "reviewer-assessment.json").read_text())
    assert assessment["evaluation_hash"] == digest(combined)
    assert {r["run_hash"] for r in assessment["records"]} == {digest(r) for r in records}
    public = json.loads((folder / "public-jobs.json").read_text())
    assert public["http_status"] == 200 and public["published_at"] is None and len(public["records"]) == 3
    operator = json.loads((folder / "operator-proof.json").read_text())
    assert operator["run_hash"] == digest(operator["record"])
    assert operator["review"]["run_hash"] == operator["run_hash"] and not operator["review"]["crm_write_authorized"]
    assert operator["repeat_review_identical"] and operator["primary_120_account_state_unchanged"]
    validate_brief(operator["record"]["raw_response"], operator["record"]["context"])
    for path, checksum in operator["source_sha256"].items():
        assert hashlib.sha256(operator["source_snapshots"][path].encode()).hexdigest() == checksum
    images = images or ROOT / "docs/images/current-research"
    provenance = json.loads((images / "provenance.json").read_text())
    assert provenance["source_sha256"] == source_hashes() and not provenance["page_errors"]
    assert all(provenance["layout_checks"].values()) and provenance["external_browser_requests"] == 0
    assert provenance["accessibility"] and all(not r["violations"] for r in provenance["accessibility"].values())
    assert len(provenance["mermaid_diagrams_parsed"]) >= 5
    for name, checksum in provenance["image_sha256"].items():
        assert hashlib.sha256((images / name).read_bytes()).hexdigest() == checksum
    print("40 actual responses, three prompt approaches, preserved failures, exact source snapshots and browser proof verified.")


if __name__ == "__main__":
    check()
