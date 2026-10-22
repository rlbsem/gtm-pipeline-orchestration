"""Actual desktop/mobile research desk interactions; no vendor or model execution."""
import argparse
import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from gtm.api import create_app
from gtm.cli import build
from publication import ROOT, source_hashes


def capture(workspace, output, audit_tools=None):
    output.mkdir(parents=True, exist_ok=True)
    sources = source_hashes()
    engine, destination, worker = build(workspace, "enterprise")
    server = uvicorn.Server(uvicorn.Config(create_app(engine, destination, worker), host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+30
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("browser_server_timeout")
            time.sleep(.1)
        url = "http://127.0.0.1:"+str(server.servers[0].sockets[0].getsockname()[1])
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors, requests = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: requests.append(r.url))
            page.goto(url)
            page.locator('[data-view="research-desk"]').click()
            page.locator("#research-run-status").filter(has_text="Actual Qwen3").wait_for()
            page.locator('[data-research-account="multi-source"]').click()
            page.select_option("#research-approach", label="evidence-first-v3")
            assert page.locator("#research-approve").is_enabled()
            assert "Northline" in page.locator("#research-opening").input_value()
            page.screenshot(path=output / "account-intelligence.png")
            page.locator("#research-opening").fill("I noticed your second regional site plan. How are you approaching failover planning between sites?")
            # The shared notification can be replaced by the initial pipeline load.
            # Verify the business transaction and durable review, not transient banner timing.
            with page.expect_response(lambda response: response.url.endswith("/api/research/review")
                                      and response.request.method == "POST") as approval_response:
                page.locator("#research-approve").click()
            assert approval_response.value.status == 200, approval_response.value.text()
            page.locator("#research-decisions").filter(has_text='"decision": "approve"').wait_for()
            page.wait_for_function("() => document.getElementById('research-approve').disabled")
            assert page.locator("#research-opening").input_value() == "I noticed your second regional site plan. How are you approaching failover planning between sites?"
            assert page.locator("#research-opening").is_disabled()
            assert "crm_write_authorized" in page.locator("#research-decisions").inner_text()
            page.locator("#research-opening").scroll_into_view_if_needed()
            page.screenshot(path=output / "seller-research-review.png")
            page.locator('[data-research-account="stale-hiring"]').click()
            page.select_option("#research-approach", label="evidence-first-v3")
            assert page.locator("#research-approve").is_disabled()
            assert page.locator("#research-opening").input_value() == ""
            page.locator("#research-dismiss").click()
            page.locator("#research-decisions").filter(has_text='"dismiss"').wait_for()
            # All ten recorded cases, all prompt options: no malformed or executable model HTML.
            page.get_by_text("Inspect an adversarial evaluation", exact=True).click()
            for option in page.locator("#research-case option").all():
                page.select_option("#research-case", option.get_attribute("value"))
                for prompt in page.locator("#research-approach option").all():
                    page.select_option("#research-approach", prompt.get_attribute("value"))
                    assert page.locator("#research-run-status").inner_text().startswith("Actual Qwen3")
            page.locator('[data-research-account="multi-source"]').click()
            layout = {}
            for width in [320, 390, 768, 1024, 1440]:
                page.set_viewport_size({"width": width, "height": 900})
                layout[str(width)] = page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert layout[str(width)], "research_overflow:"+str(width)
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#research-desk").scroll_into_view_if_needed()
            page.screenshot(path=output / "mobile-intelligence.png", full_page=True)
            ids = page.locator("[id]").evaluate_all("nodes => nodes.map(n => n.id)")
            assert len(ids) == len(set(ids)), "duplicate_html_id"
            accessibility, diagrams = {}, []
            if audit_tools:
                from browser_audit_tools import verified
                verified(audit_tools)
                # Test-only context permits audit script injection; application CSP remains unchanged.
                audit = browser.new_page(bypass_csp=True)
                audit.goto(url)
                audit.locator('[data-view="research-desk"]').click()
                audit.locator("#research-run-status").filter(has_text="Actual Qwen3").wait_for()
                audit.add_script_tag(path=str(audit_tools / "axe.min.js"))
                for width in [390, 1440]:
                    audit.set_viewport_size({"width": width, "height": 1000})
                    result = audit.evaluate("async () => await axe.run(document.getElementById('research-desk'), {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})")
                    accessibility[str(width)] = {"violations": [{"id": v["id"], "help": v["help"],
                        "targets": [n["target"] for n in v["nodes"]]} for v in result["violations"]],
                        "incomplete_rules": [v["id"] for v in result["incomplete"]], "passes": len(result["passes"])}
                (output / "accessibility.json").write_text(json.dumps(accessibility, indent=2)+"\n", encoding="utf-8", newline="\n")
                assert all(not a["violations"] for a in accessibility.values()), accessibility
                audit.add_script_tag(path=str(audit_tools / "mermaid.min.js"))
                audit.evaluate("() => mermaid.initialize({startOnLoad:false})")
                for path in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
                    for block in re.findall(r"```mermaid\s*\n(.*?)```", path.read_text(encoding="utf-8"), re.S):
                        assert audit.evaluate("async text => !!(await mermaid.parse(text))", block)
                        diagrams.append(path.relative_to(ROOT).as_posix())
                audit.close()
            metrics = page.request.get(url+"/api/research").json()["metrics"]
            assert sum(r["count"] for r in metrics["seller_decisions"]) == 2
            from gtm.research import research_workspace
            assert engine.audit_valid() and research_workspace(engine).engine.audit_valid()
            assert not errors, errors
            assert all(r.startswith(url+"/") for r in requests), "external_browser_request"
            assert source_hashes() == sources
            browser.close()
        report = {"captured_at": datetime.now(timezone.utc).isoformat(), "method": "actual Chromium / running local application",
                  "source_sha256": sources, "layout_checks": layout, "page_errors": errors,
                  "browser_interactions": ["select_account", "compare_recorded_prompts", "edit_opening", "approve_exact_local_review",
                                           "reject_stale_recommendation", "inspect_all_evaluation_cases"],
                  "metrics": metrics, "external_browser_requests": 0, "native_writes": "not_executed", "fresh_inference": "not_executed",
                  "accessibility": accessibility, "mermaid_diagrams_parsed": diagrams,
                  "audit_scope": "new research section; automated WCAG 2 A/AA and 2.1 AA, not full conformance certification",
                  "image_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob("*.png")}}
        (output / "provenance.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8", newline="\n")
        print(json.dumps({"layout_checks": layout, "page_errors": errors, "browser_interactions": report["browser_interactions"]}))
        return report
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        destination.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/images/research"))
    parser.add_argument("--audit-tools", type=Path)
    args = parser.parse_args()
    capture(args.workspace, args.output, args.audit_tools)
