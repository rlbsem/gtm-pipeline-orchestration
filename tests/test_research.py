"""Adversarial research contracts and durable review; model and vendor calls are never needed."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gtm.contracts import DomainError
from gtm.research import ResearchDesk, Signal, live_context, load_scenario, prioritize, validate_brief, waterfall
from gtm.store import digest
from conftest import mutate

AT = "2026-01-21T12:00:00Z"


def context():
    return {k: v for k, v in load_scenario()["cases"][0].items() if k != "rubric"}


def brief(ctx):
    source = ctx["sources"][0]
    return {"facts": [{"text": source["text"], "source_id": source["source_id"], "quote": source["text"]}],
            "hypotheses": [], "relevance": "May support infrastructure planning discovery; not evidence of a purchase.",
            "gaps": ["No approved procurement."], "action": "review", "opening": "Is planning the second site a useful topic?"}


def run(ctx):
    b = brief(ctx)
    return {"context": ctx, "context_hash": digest(ctx), "approach": "test-contract-not-inference",
            "raw_response": json.dumps(b), "parsed": b, "latency_seconds": 2.5}


@pytest.mark.parametrize("field,value", [("version", "other"), ("kind", "magic"),
    ("account_domain", "real.com"), ("url", "http://internal"), ("url", "https://user:secret@example.com"),
    ("observed_at", "2027-01-01T00:00:00Z"), ("expires_at", "2025-01-01T00:00:00Z"),
    ("confidence", 1.2), ("extra", True)])
def test_signal_closed_contract(field, value):
    s = context()["sources"][0] | {field: value}
    with pytest.raises((DomainError, ValidationError)):
        Signal(**s).checked(AT)


def test_immutable_idempotent_ingestion_and_collision(engine):
    desk = ResearchDesk(engine)
    s = context()["sources"][0]
    assert desk.ingest(s, AT) == "accepted"
    assert desk.ingest(s, AT) == "duplicate"
    with pytest.raises(DomainError, match="collision"):
        desk.ingest(s | {"text": "Changed source content"}, AT)
    with engine.connection() as db, pytest.raises(Exception, match="immutable"):
        db.execute("DELETE FROM research_sources")


def test_duplicate_age_and_weighting_do_not_inflate_priority():
    c = context()
    before = prioritize(c, AT)
    c["sources"] += [c["sources"][0] | {"source_id": "syndication", "confidence": .5}]
    after = prioritize(c, AT)
    assert before["priority"] == after["priority"]
    assert after["contributions"][-1]["reason"] == "duplicate"
    expired = prioritize(c, "2026-05-01T00:00:00Z")
    assert expired["signal_points"] == 0 and not expired["eligible"]
    assert prioritize(c, AT, {k: 0 for k in [s["kind"] for s in c["sources"]]})["signal_points"] == 0


@pytest.mark.parametrize("change,block", [({"owner": ""}, "unverified_owner"),
    ({"consent": False}, "no_contact_permission"), ({"open_opportunities": 1}, "existing_open_opportunity")])
def test_current_authority_is_separate_from_priority(change, block):
    c = context()
    c["crm"].update(change)
    result = prioritize(c, AT)
    assert result["priority"] > 70 and not result["eligible"] and block in result["blocks"]


def test_public_and_wrong_identity_never_authorize():
    c = context()
    c["sources"][0]["account_domain"] = "unrelated.example"
    assert "source_account_mismatch" in prioritize(c, AT)["blocks"]
    c["synthetic"] = False
    assert "public_reference_read_only" in prioritize(c, AT)["blocks"]


def test_unknown_publication_is_not_a_new_signal():
    c = context()
    for s in c["sources"]:
        s["published_at"] = None
    assert prioritize(c, AT)["signal_points"] == 0


def test_waterfall_missing_fallback_costs_and_crm_precedence():
    result = waterfall("account-04.example", {"employees": 240}, load_scenario()["providers"])
    assert [a["status"] for a in result["attempts"]] == ["missing", "found"]
    assert result["values"]["employees"] == 240 and result["conflicts"][0]["rejected"] == 20000
    assert result["modeled_cost_usd_micros"] == 4500 and result["actual_provider_spend_usd"] == 0
    result = waterfall("missing.example", {}, load_scenario()["providers"])
    assert result["missing"] == ["employees", "industry", "territory"]


@pytest.mark.parametrize("mutation", ["unknown_source", "altered_quote", "extra", "empty_support", "bad_hypothesis", "abstain_draft"])
def test_output_negative_contract(mutation):
    c, b = context(), brief(context())
    if mutation == "unknown_source":
        b["facts"][0]["source_id"] = "nonexistent"
    elif mutation == "altered_quote":
        b["facts"][0]["quote"] = "This company has budget"
    elif mutation == "extra":
        b["execute_task"] = True
    elif mutation == "empty_support":
        b["facts"] = []
    elif mutation == "bad_hypothesis":
        b["hypotheses"] = [{"text": "Budget approved", "source_ids": ["fake"], "rationale": "Because I say so"}]
    else:
        b["action"] = "abstain"
    with pytest.raises(DomainError):
        validate_brief(json.dumps(b), c)


def test_exact_quote_can_still_be_semantically_misleading():
    c, b = context(), brief(context())
    b["facts"][0]["text"] = "The company has approved procurement."
    assert validate_brief(json.dumps(b), c) == b  # Deliberate demonstration of the contract's limit.
    assert "not been approved" in c["sources"][1]["text"]


def test_exact_review_restart_idempotency_and_no_execution(seeded):
    desk = ResearchDesk(seeded)
    c = context()
    key = desk.save_run(run(c))
    live = live_context(seeded, c, AT)
    # Account 04 is a treatment fixture account; this is still not a native write authorization.
    assert prioritize(live, AT)["eligible"]
    result = desk.review(key, "A seller-edited question about your second site?", "approve", digest(live), AT)
    assert not result["crm_write_authorized"]
    assert ResearchDesk(seeded).review(key, result["opening"], "approve", digest(live), AT) == result
    with pytest.raises(DomainError, match="already_recorded"):
        desk.review(key, "Different text", "approve", digest(live), AT)
    assert seeded.audit_valid()


@pytest.mark.parametrize("mutation", ["owner", "consent"])
def test_owner_or_permission_change_invalidates_review(seeded, mutation):
    desk = ResearchDesk(seeded)
    c = context()
    key = desk.save_run(run(c))
    before = live_context(seeded, c, AT)
    account = before["crm"]["account_id"]
    mutate(seeded, account, mutation, {"owner": "atlas-emea"} if mutation == "owner" else {"allowed": False}, AT,
           source="crm" if mutation == "owner" else "web")
    with pytest.raises(DomainError, match="context_changed"):
        desk.review(key, "Question?", "approve", digest(before), AT)
    current = live_context(seeded, c, AT)
    if mutation == "consent":
        with pytest.raises(DomainError, match="suppressed"):
            desk.review(key, "Question?", "approve", digest(current), AT)


def test_dismiss_metrics_and_immutable_review(engine):
    desk = ResearchDesk(engine)
    c = context()
    key = desk.save_run(run(c))
    current = live_context(engine, c, AT)
    desk.review(key, "", "dismiss", digest(current), AT)
    m = desk.metrics()
    assert m["accounts_researched"] == 1 and m["inference_seconds"] == 2.5
    assert m["seller_decisions"] == [{"decision": "dismiss", "count": 1}]
    assert m["signal_to_review_seconds"][0]["seconds"] == 86400
    with engine.connection() as db, pytest.raises(Exception, match="immutable"):
        db.execute("UPDATE research_reviews SET decision='approve'")


def test_fixture_generator_matches_versioned_dataset():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from research_fixture import cases
    assert cases() == load_scenario()["cases"]


def test_saved_model_response_not_mutated_in_place():
    c = context()
    old = copy.deepcopy(c)
    prioritize(c, AT)
    assert c == old


def test_new_admission_invalidates_prior_model_until_researched(seeded):
    desk = ResearchDesk(seeded)
    c = context()
    key = desk.save_run(run(c))
    added = c["sources"][0] | {"source_id": "new-source", "event_key": "new-distinct-event", "text": "A new synthetic continuity planning update."}
    assert desk.admit("multi-source", added, AT) == "accepted"
    assert desk.admit("multi-source", added, AT) == "duplicate"
    current = desk.current_context(c, AT)
    assert len(current["sources"]) == len(c["sources"])+1
    with pytest.raises(DomainError, match="sources_changed"):
        desk.review(key, "Question?", "approve", digest(current), AT)
    refreshed = run(current)
    fresh_key = desk.save_run(refreshed)
    assert desk.review(fresh_key, "Question?", "approve", digest(current), AT)["decision"] == "approve"


@pytest.mark.parametrize("change", [{"account_domain": "unrelated.example"}, {"synthetic": False}])
def test_new_source_admission_never_crosses_account_or_public_boundary(engine, change):
    with pytest.raises(DomainError, match="identity_mismatch"):
        ResearchDesk(engine).admit("multi-source", context()["sources"][0] | change, AT)


def test_research_workspace_does_not_modify_primary_engine(engine):
    from gtm.research import research_workspace
    before = engine.rows("sources"), engine.rows("accounts"), engine.rows("audit")
    desk = research_workspace(engine)
    assert len(desk.engine.rows("accounts")) == 6
    assert (engine.rows("sources"), engine.rows("accounts"), engine.rows("audit")) == before
    assert research_workspace(engine).engine.rows("accounts") == desk.engine.rows("accounts")


def test_model_parsed_content_cannot_disagree_with_recorded_text(engine):
    record = run(context())
    record["parsed"]["opening"] = "Unrecorded text"
    with pytest.raises(DomainError, match="parsed_response_mismatch"):
        ResearchDesk(engine).save_run(record)


def test_n8n_reference_has_no_write_or_credential_nodes():
    workflow = json.loads((Path(__file__).resolve().parents[1] / "docs/n8n-research-reference.json").read_text())
    assert not workflow["active"]
    assert {n["type"] for n in workflow["nodes"]} == {"n8n-nodes-base.manualTrigger", "n8n-nodes-base.httpRequest"}
    assert workflow["nodes"][1]["parameters"]["url"] == "http://127.0.0.1:8560/api/research"
