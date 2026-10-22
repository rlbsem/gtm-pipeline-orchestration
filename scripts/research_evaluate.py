"""Explicit, authenticated local inference. Preserve every response, including failures."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from gtm.research import PROMPTS, infer, load_scenario
from gtm.store import digest
from publication import ROOT


def contract_assessment(run, rubric):
    """Limited reproducible rubric checks. Semantic and usefulness judgments are separate."""
    brief = run["parsed"]
    if not brief:
        return {"schema": False, "expected_action": False, "opening_relevant": False, "banned_phrases_absent": False}
    opening = brief["opening"].lower()
    return {"schema": True, "expected_action": brief["action"] == rubric["expected_action"],
            "opening_relevant": not opening if brief["action"] == "abstain" else any(w in opening for w in rubric["must_mention"]),
            "banned_phrases_absent": not any(w in opening for w in rubric["forbidden_claims"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8093")
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--runtime-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approach", choices=list(PROMPTS), action="append")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dataset = load_scenario()
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [ROOT / "src/gtm/research.py", ROOT / "src/gtm/research-scenario.json", Path(__file__)]}
    runtime = {"model_sha256": hashlib.file_digest(args.model_file.open("rb"), "sha256").hexdigest(),
               "executable_sha256": hashlib.file_digest(args.runtime_file.open("rb"), "sha256").hexdigest(),
               "model": "Qwen3-14B-Q4_K_M", "transport": "authenticated loopback llama.cpp", "api_spend_usd": 0,
               "energy_cost": "not_metered"}
    for case in dataset["cases"]:
        context = {k: v for k, v in case.items() if k != "rubric"}
        for approach in args.approach or PROMPTS:
            path = args.output / (case["id"] + "--" + approach + ".json")
            # Resume is exact-input only; never replace a failure with a convenient later output.
            if path.exists():
                old = json.loads(path.read_text())
                assert old["context_hash"] == digest(context) and old["source_sha256"] == hashes
                continue
            run = infer(context, approach, args.origin, args.key_file.read_text().strip(), "qwen3-14b")
            run.update(case_id=case["id"], source_sha256=hashes, runtime=runtime,
                       contract_assessment=contract_assessment(run, case["rubric"]))
            path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(case["id"], approach, run["error"] or run["parsed"]["action"], flush=True)
    records = [json.loads(p.read_text()) for p in sorted(args.output.glob("*--*.json"))]
    report = {"version": "research-evaluation/v1", "evaluated_at": datetime.now(timezone.utc).isoformat(),
              "records": records, "source_sha256": hashes, "runtime": runtime,
              "limitations": "Automated checks assess schema, exact citations and finite rubric terms; they do not establish semantic entailment or seller usefulness. See separate reviewer assessment.",
              "comparisons": {a: {"responses": len([r for r in records if r["approach"] == a]),
                                  "contract_passes": sum(all(r["contract_assessment"].values()) for r in records if r["approach"] == a),
                                  "latency_seconds": round(sum(r["latency_seconds"] for r in records if r["approach"] == a), 3),
                                  "completion_tokens": sum((r["usage"] or {}).get("completion_tokens", 0) for r in records if r["approach"] == a)} for a in PROMPTS}}
    (args.output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
