"""Reproduce tests and two independent HTTP executions; publish only sanitized successful evidence."""
import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from publication import ROOT, checks, source_hashes


def run(command, env):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        print(result.stdout[-14000:])
        print(result.stderr[-5000:])
        raise RuntimeError("verification_step_failed:" + command[2])
    return result.stdout


def verify(output):
    output.mkdir(parents=True, exist_ok=True)
    work = ROOT / "work" / ("verification-" + uuid.uuid4().hex)
    work.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
    before = source_hashes()
    run([sys.executable, "-m", "pip", "check"], env)
    run([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"], env)
    test_xml = work / "tests.xml"
    run([sys.executable, "-m", "pytest", "--tb=short", "--basetemp", str(work / "pytest"),
         "--junitxml", str(test_xml)], env)
    tree = ET.parse(test_xml)
    suites = list(tree.getroot())
    totals = {key: sum(int(s.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    assert totals["tests"] >= 65 and not any(totals[k] for k in ("failures", "errors", "skipped")), totals
    for suite in suites:
        suite.attrib.pop("hostname", None)
    tree.write(output / "tests.xml", encoding="utf-8", xml_declaration=True)
    (output / "tests.xml").write_bytes((output / "tests.xml").read_bytes().replace(b"\r\n", b"\n"))
    for profile in ("fixture", "enterprise"):
        demos = []
        for index in range(2):
            workspace = work / f"{profile}-{index}"
            run([sys.executable, "-m", "gtm.cli", "demo", "--profile", profile, "--workspace", str(workspace)], env)
            demos.append(json.loads((workspace / "demo.json").read_text()))
        assert demos[0] == demos[1], "independent_demo_mismatch:" + profile
        assert demos[0]["reconciliation"]["safe_to_resume"] and demos[0]["audit_valid"]
        assert demos[0]["measurement"]["leakage_accounts"] == []
        assert len([a for a in demos[0]["actions"] if a["status"] == "blocked"]) == 2
        assert any(a["attempts"] == 2 for a in demos[0]["actions"]), "rate_limit_not_exercised"
        if profile == "fixture":
            assert demos[0] == json.loads((ROOT / "docs/evidence/demo.json").read_text()), "original_fixture_changed"
        else:
            assert demos[0]["financial_audit"]["source_to_sql_parity"]
            assert 200000000 <= demos[0]["financial_audit"]["pipeline_cents"] <= 500000000
        name = "fixture-demo.json" if profile == "fixture" else "demo.json"
        (output / name).write_text(json.dumps(demos[0], indent=2) + "\n", encoding="utf-8", newline="\n")
    assert source_hashes() == before, "source_changed_during_verification"
    result = {"executed_at": datetime.now(timezone.utc).isoformat(), "platform": platform.system(),
              "python": platform.python_version(), "tests": totals, "independent_demo_runs": 4,
              "runs_per_profile": {"fixture": 2, "enterprise": 2},
              "demo_equality": "exact", "pip_check": "passed", "ruff": "passed",
              "dependencies": {name: importlib.metadata.version(name) for name in
                               ["fastapi", "pydantic", "httpx", "uvicorn", "pytest", "playwright"]},
              "fresh_inference": "not_executed", "native_vendors": "not_executed",
              "source_sha256": before}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    result.update(checks())
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"tests": totals, "independent_demo_runs": 4, **checks()}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/salesforce-standard/local"))
    args = parser.parse_args()
    verify(args.output)
