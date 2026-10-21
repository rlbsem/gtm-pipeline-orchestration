"""Explicit real inference lane. Default demo and CI never invoke a model."""
import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from gtm.advice import infer_record
from gtm.contracts import DomainError
from gtm.destination import Destination
from gtm.engine import Engine
from gtm.store import digest
from gtm.upgrade_scenarios import SCENARIO, cases, fixture, mutate
from gtm.worker import EngagementClient, Worker
from execution_bindings import lane_hashes


def policy_check(engine, account, case, directory, model_record):
    """Independent finite executor checks. These are NOT a semantic model-quality score."""
    result = {"prepare_allowed": False, "modified_copy_rejected": None, "dispatch_status": None}
    try:
        prepared = engine.prepare(account["id"], SCENARIO)
    except DomainError as error:
        result["prepare_error"] = str(error)
        assert not case["prepare_allowed"]
        return result
    assert case["prepare_allowed"]
    result["prepare_allowed"] = True
    altered = json.loads(json.dumps(prepared))
    # Try actual model prose when valid, otherwise an explicitly labelled adversarial test string.
    altered["payload"]["message"] = ((model_record.get("parsed") or {}).get("suggested_question")
                                      or "TEST: unapproved delivery commitment")
    if altered["payload"]["message"] == prepared["payload"]["message"]:
        altered["payload"]["message"] += " TEST: unapproved guarantee"
    try:
        engine.approve(account["id"], altered, "demo-reviewer", SCENARIO)
    except DomainError:
        result["modified_copy_rejected"] = True
    assert result["modified_copy_rejected"] is True
    action = engine.approve(account["id"], prepared, "demo-reviewer", SCENARIO)
    if case["mutation"] == "owner_after_approval":
        mutate(engine, account, "owner", {"owner": "atlas-emea"}, at="2026-01-21T12:00:01Z")
    if case["mutation"] == "optout_after_approval":
        mutate(engine, account, "consent", {"allowed": False}, source="web", at="2026-01-21T12:00:01Z")
    destination = Destination(directory / "receiver.sqlite").start()
    try:
        client = EngagementClient(destination.url, destination.token)
        state = Worker(engine, client).dispatch(action["action_key"], "2026-01-21T12:00:02Z")
        result.update({"dispatch_status": state["status"], "independent_effects": len(client.receipts()),
                       "approved_payload_hash": prepared["payload_hash"], "audit_valid": engine.audit_valid()})
    finally:
        destination.close()
    allowed = case.get("dispatch_allowed", True)
    assert result["dispatch_status"] == ("delivered" if allowed else "blocked")
    assert result["independent_effects"] == int(allowed) and result["audit_valid"]
    return result


def evaluate(args):
    args.workspace.mkdir(parents=True, exist_ok=False)
    before = lane_hashes("ai")
    token = args.token_file.read_text().strip()
    configuration = cases()
    records = []
    for case in configuration["cases"]:
        for seed in (42, 43):
            folder = args.workspace / (case["id"] + "-" + str(seed))
            folder.mkdir()
            engine = Engine(folder / "control.sqlite")
            account, documents = fixture(engine, case)
            record = infer_record(engine, account["id"], args.origin, token, args.model,
                                  now=SCENARIO, documents=documents, seed=seed, temperature=0.2)
            record.update({"case_id": case["id"], "policy": policy_check(engine, account, case, folder, record)})
            records.append(record)
            # Checkpoint after every real response; no fabricated replacement on interruption.
            (args.workspace / "responses.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            print(case["id"], seed, record["validation_error"] or "exact citations", flush=True)
    assert lane_hashes("ai") == before
    version = subprocess.run([str(args.runtime), "--version"], capture_output=True, text=True,
                             encoding="utf-8", env={**os.environ}, check=True)
    result = {"boundary": "actual authenticated loopback Qwen inference; local synthetic execution only",
              "executed_at": datetime.now(timezone.utc).isoformat(), "scenario_at": SCENARIO,
              "source_sha256": before, "cases_sha256": digest(configuration),
              "runtime": {"version": (version.stdout + version.stderr).strip(),
                          "executable_sha256": hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
                          "weights_sha256": hashlib.file_digest(args.weights.open("rb"), "sha256").hexdigest(),
                          "model": args.model, "backend": "Vulkan", "context_tokens": 8192,
                          "reasoning": "off", "parallel_slots": 1},
              "inferences_executed": len(records),
              "exact_citation_checks_passed": sum(r["validation_error"] is None for r in records),
              "limits": ["Exact quotations do not establish semantic entailment, usefulness or injection resistance.",
                         "Execution policy rejects arbitrary model prose; model output does not authorize CRM writes.",
                         "Two seeds per case are a small repeatability probe, not a statistical model benchmark.",
                         "No native sales communications, meetings, opportunities or commercial uplift."],
              "records": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--origin", default="http://127.0.0.1:8093")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--model", default="qwen3-14b")
    evaluate(parser.parse_args())
