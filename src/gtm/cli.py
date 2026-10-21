import argparse
import json
from pathlib import Path

import uvicorn

from .api import create_app
from .destination import Destination
from .engine import Engine
from .fixtures import FINISH, replay
from .measurement import measure
from .worker import EngagementClient, Worker, reconcile


def build(workspace):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    engine = Engine(workspace / "control.sqlite")
    destination = Destination(workspace / "engagement.sqlite").start()
    worker = Worker(engine, EngagementClient(destination.url, destination.token))
    try:
        if not engine.rows("accounts"):
            replay(engine, destination, worker)
    except BaseException:
        destination.close()
        raise
    return engine, destination, worker


def main():
    parser = argparse.ArgumentParser(description="Synthetic-only pipeline orchestration")
    parser.add_argument("command", choices=["demo", "serve", "infer"])
    parser.add_argument("--workspace", default=".local/demo")
    parser.add_argument("--port", type=int, default=8560)
    parser.add_argument("--container-bind", action="store_true", help="Bind inside a container only; publish port on host loopback")
    parser.add_argument("--account")
    parser.add_argument("--model-origin")
    parser.add_argument("--model")
    parser.add_argument("--model-key-file")
    args = parser.parse_args()
    engine, destination, worker = build(args.workspace)
    try:
        if args.command == "serve":
            print(f"Local synthetic workbench: http://127.0.0.1:{args.port}")
            uvicorn.run(create_app(engine, destination, worker), host="0.0.0.0" if args.container_bind else "127.0.0.1",
                        port=args.port, log_level="warning")
        elif args.command == "infer":
            from .advice import infer
            if not all([args.account, args.model_origin, args.model, args.model_key_file]):
                parser.error("infer requires account, model-origin, model and private model-key-file")
            result = infer(engine, args.account, args.model_origin,
                           Path(args.model_key_file).read_text().strip(), args.model)
            output = Path(args.workspace) / "advisory-inference.json"
            output.write_text(json.dumps(result, indent=2) + "\n")
            print("Advisory model result saved privately; no activation was authorized.")
        else:
            result = {"measurement": measure(engine, FINISH), "reconciliation": reconcile(engine, worker.client),
                      "actions": engine.rows("actions"), "routes": engine.rows("routes"),
                      "audit_valid": engine.audit_valid(), "http_requests": destination.request_counts(),
                      "source_records": engine.rows("sources"), "qualification_decisions": engine.rows("decisions"),
                      "feedback": engine.rows("feedback"), "account_records": engine.rows("accounts"),
                      "audit": engine.rows("audit"), "receiver_requests": destination.request_log(),
                      "fresh_inference": "not_executed", "native_vendors": "not_executed"}
            (Path(args.workspace) / "demo.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"accounts": len(engine.rows("accounts")), "arms": result["measurement"]["arms"],
                              "reconciliation": result["reconciliation"], "audit_valid": result["audit_valid"]}, indent=2))
    finally:
        destination.close()


if __name__ == "__main__":
    main()
