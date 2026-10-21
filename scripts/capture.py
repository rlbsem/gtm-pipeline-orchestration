"""Drive and capture the actual application. No generated image or fabricated interface."""
import argparse
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from gtm.api import create_app
from gtm.cli import build
from publication import source_hashes


def capture(workspace, output):
    output.mkdir(parents=True, exist_ok=True)
    bound_sources = source_hashes()
    engine, destination, worker = build(workspace, "enterprise")
    server = uvicorn.Server(uvicorn.Config(create_app(engine, destination, worker), host="127.0.0.1", port=0,
                                          log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("application_start_timeout")
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1120}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.locator("#accounts tr").first.wait_for()
            baseline = page.request.get(url + "/api/state").json()
            total = sum(a["pipeline_cents"] for a in baseline["measurement"]["arms"].values())
            assert total == 346000000 and len(baseline["accounts"]) == 120
            assert "$3,460,000" in page.locator("#metrics").inner_text()
            page.screenshot(path=output / "pipeline-overview.png")
            page.locator('[data-view="commercial"]').click()
            assert page.locator("#commercial-ledger tr").count() == 5
            assert "$1,200,000" in page.locator("#commercial-ledger").inner_text()
            page.screenshot(path=output / "commercial-scenario.png")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=output / "mobile-commercial.png", full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1320})
            page.locator('[data-view="workspace"]').click()
            page.locator("#receipt").filter(has_text="READ-BACK VERIFIED").wait_for()
            page.screenshot(path=output / "account-workbench.png")
            page.set_viewport_size({"width": 1440, "height": 1120})
            page.locator('[data-view="recovery"]').click()
            page.locator("#reconciliation").filter(has_text="safe_to_resume").wait_for()
            page.screenshot(path=output / "execution-recovery.png")
            # Exercise a genuine fresh vertical slice through browser controls.
            account = next(c["account_id"] for c in engine.rows("cohorts") if c["arm"] == "treatment"
                           and not any(a["account_id"] == c["account_id"] for a in engine.rows("actions")))
            page.locator('[data-view="workspace"]').click()
            page.locator("#account-select").select_option(account)
            page.locator("#prepare").click()
            page.locator("#approve").wait_for(state="visible")
            page.wait_for_function("() => !document.getElementById('approve').disabled")
            page.locator("#approve").click()
            page.wait_for_function("() => !document.getElementById('dispatch').disabled")
            page.locator("#prepared").filter(has_text="Approved by demo-reviewer").wait_for()
            assert page.locator("#approve").is_disabled()
            page.get_by_text("Test a local failure safely", exact=True).click()
            page.locator("#lost-ack").click()
            page.locator("#notice").filter(has_text="will commit").wait_for()
            page.locator("#dispatch").click()
            page.locator("#notice").filter(has_text="uncertain").wait_for()
            page.locator("#dispatch").click()
            page.locator("#receipt").filter(has_text="READ-BACK VERIFIED").wait_for()
            assert "Awaiting exact approval" not in page.locator("#prepared").inner_text()
            for kind in ("reply_positive", "meeting_qualified", "opportunity_accepted"):
                page.locator(f'[data-feedback="{kind}"]').click()
                page.locator("#timeline").filter(has_text=kind.replace("_", " ")).wait_for()
            action = next(a for a in engine.rows("actions") if a["account_id"] == account)
            assert action["status"] == "reconciled" and action["attempts"] == 1
            assert len([f for f in engine.rows("feedback") if f["account_id"] == account]) == 3
            after = page.request.get(url + "/api/state").json()
            after_pipeline = sum(a["pipeline_cents"] for a in after["measurement"]["arms"].values())
            interactive_value = next(f["amount_cents"] for f in after["outcomes"]
                                     if f["kind"] == "opportunity_accepted" and f["account_id"] == account)
            assert after_pipeline == total + interactive_value
            page.locator('[data-view="inbound"]').click()
            page.locator("#inbound-request").select_option("support")
            page.locator('#inbound-form button[type="submit"]').click()
            page.locator("#inbound-result").filter(has_text="service_review").wait_for()
            page.locator('[data-view="proof"]').click()
            page.locator("#native-status").filter(has_text="passed").wait_for()
            page.locator("#native-proof").filter(has_text="Account · Contact · Task").wait_for()
            assert "1 exact effect" in page.locator("#native-proof").inner_text()
            assert "4 assignments removed" in page.locator("#native-proof").inner_text()
            page.locator("#ai-status").filter(has_text="16 RESPONSES").wait_for()
            page.locator("#ai-response").filter(has_text="Juniper").wait_for()
            page.screenshot(path=output / "native-ai-evidence.png")
            # Inspect an actual rejected model response, rendered as text, never executable HTML.
            page.locator("#ai-case").select_option("8")
            page.locator("#ai-case-status").filter(has_text="citation_not_exact").wait_for()
            assert '"prepare_allowed": false' in page.locator("#ai-policy").inner_text()
            mobile_checks = {}
            page.set_viewport_size({"width": 390, "height": 844})
            for name in ("overview", "workspace", "inbound", "recovery", "proof", "commercial"):
                page.locator(f'[data-view="{name}"]').click()
                mobile_checks[name] = page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
                assert mobile_checks[name], "mobile_overflow:" + name
            page.locator('[data-view="workspace"]').click()
            page.screenshot(path=output / "mobile-workbench.png", full_page=True)
            browser.close()
        assert not errors, errors
        assert source_hashes() == bound_sources, "source_changed_during_capture"
        result = {"captured_at": datetime.now(timezone.utc).isoformat(), "method": "actual Chromium / local UI and APIs",
                  "desktop_viewport": {"width": 1440, "height": 1120}, "mobile_viewport": {"width": 390, "height": 844},
                  "account_workbench_viewport": {"width": 1440, "height": 1320},
                  "profile": "enterprise", "baseline_pipeline_cents": total,
                  "after_interaction_pipeline_cents": after_pipeline,
                  "interactive_crm_opportunity_cents": interactive_value,
                  "screenshot_phases": {"before_interaction": ["pipeline-overview.png", "commercial-scenario.png",
                                        "mobile-commercial.png", "account-workbench.png", "execution-recovery.png"],
                                        "after_interaction": ["native-ai-evidence.png", "mobile-workbench.png"]},
                  "no_page_overflow": mobile_checks, "page_errors": errors,
                  "browser_flow": ["prepare", "exact_approval", "real_lost_ack", "independent_receipt_recovery",
                                   "positive_reply", "qualified_meeting", "accepted_opportunity", "inbound_service_route",
                                   "recorded_native_and_ai_evidence", "inspect_rejected_model_citation"],
                  "new_action_attempts": action["attempts"], "new_action_status": action["status"],
                  "inference": "not_executed", "native_vendors": "not_executed",
                  "source_sha256": bound_sources,
                  "image_sha256": {x.name: hashlib.sha256(x.read_bytes()).hexdigest() for x in output.glob("*.png")}}
        (output / "provenance.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
        return result
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        destination.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("docs/images/salesforce-standard"))
    args = parser.parse_args()
    print(json.dumps(capture(args.workspace, args.output), indent=2))
