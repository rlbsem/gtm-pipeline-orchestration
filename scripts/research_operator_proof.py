"""Finish an explicitly executed operator run through real local HTTP; never invoke a model or vendor."""
import argparse
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import uvicorn

from gtm.api import create_app
from gtm.cli import build
from gtm.research import research_workspace, validate_brief
from gtm.store import digest
from publication import ROOT


def prove(workspace, run_file, output):
    run = json.loads(run_file.read_text(encoding="utf-8"))
    assert run["operator_execution"] and run["inference"] == "executed" and run["parsed"]
    validate_brief(run["raw_response"], run["context"])
    paths = ["src/gtm/research.py", "src/gtm/research.sql", "scripts/research_operator.py", "src/gtm/api.py",
             "scripts/research_operator_proof.py"]
    snapshots = {p: (ROOT / p).read_text(encoding="utf-8") for p in paths}
    engine, destination, worker = build(workspace, "enterprise")
    server = uvicorn.Server(uvicorn.Config(create_app(engine, destination, worker), host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+30
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("operator_proof_server_timeout")
            time.sleep(.1)
        origin = "http://127.0.0.1:"+str(server.servers[0].sockets[0].getsockname()[1])
        with httpx.Client(base_url=origin, headers={"X-Demo-Intent": "operator"}) as client:
            before = client.get("/api/state").json()
            catalog = client.get("/api/research").json()
            account = next(a for a in catalog["accounts"] if a["id"] == run["case_id"])
            option = next(r for r in account["runs"] if r["run_hash"] == digest(run))
            assert option["source_snapshot_current"]
            payload = {"run_hash": digest(run), "opening": run["parsed"]["opening"],
                       "decision": "approve", "context_hash": account["context_hash"]}
            response = client.post("/api/research/review", json=payload)
            assert response.status_code == 200, response.text
            again = client.post("/api/research/review", json=payload)
            assert again.status_code == 200 and again.json() == response.json()
            after = client.get("/api/state").json()
            assert before == after, "research_changed_primary_pipeline_state"
        desk = research_workspace(engine)
        assert desk.engine.audit_valid()
        proof = {"executed_at": datetime.now(timezone.utc).isoformat(), "transport": "actual local TCP HTTP / uvicorn + httpx",
                 "record": run, "run_hash": digest(run), "review": response.json(), "repeat_review_identical": True,
                 "current_sources_verified": True, "primary_120_account_state_unchanged": True,
                 "source_snapshots": snapshots, "source_sha256": {p: hashlib.sha256(v.encode()).hexdigest() for p, v in snapshots.items()},
                 "native_writes": "not_executed", "prospect_communications": "not_executed"}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proof, indent=2)+"\n", encoding="utf-8", newline="\n")
        print("Fresh operator inference / exact local approval / idempotent HTTP readback verified; primary pipeline unchanged.")
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        destination.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prove(args.workspace, args.run, args.output)
