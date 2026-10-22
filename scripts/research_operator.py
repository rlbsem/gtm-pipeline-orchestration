"""Explicit new-source ingestion and fresh research, persisted into the running desk workspace."""
import argparse
import json
from pathlib import Path

from gtm.engine import Engine
from gtm.research import infer, load_scenario, research_workspace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest", "infer"])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--case", choices=load_scenario()["workspace_cases"], required=True)
    parser.add_argument("--at", default=load_scenario()["as_of"])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--origin", default="http://127.0.0.1:8093")
    args = parser.parse_args()
    desk = research_workspace(Engine(args.workspace / "control.sqlite"))
    if args.command == "ingest":
        if not args.source:
            parser.error("ingest requires source JSON")
        print(desk.admit(args.case, json.loads(args.source.read_text(encoding="utf-8")), args.at))
    else:
        if not args.key_file:
            parser.error("infer requires private key-file; no browser-supplied model responses")
        case = next(c for c in load_scenario()["cases"] if c["id"] == args.case)
        context = desk.current_context({k: v for k, v in case.items() if k != "rubric"}, args.at)
        record = infer(context, "evidence-first-v3", args.origin, args.key_file.read_text().strip(), "qwen3-14b")
        record.update(case_id=args.case, operator_execution=True)
        key = desk.save_run(record)
        path = args.workspace / ("research-"+key+".json")
        path.write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8", newline="\n")
        print("Actual operator research persisted; no CRM action authorized. Run hash:", key)


if __name__ == "__main__":
    main()
