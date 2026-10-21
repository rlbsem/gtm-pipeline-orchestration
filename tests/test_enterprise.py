"""Enterprise source economics, original fixture preservation and independent financial checks."""
import copy
import json
from pathlib import Path

import pytest

from gtm.api import create_app
from gtm.cli import build
from gtm.commercial import financial_audit
from gtm.enterprise import describe, seed_enterprise, specification
from gtm.fixtures import FINISH
from gtm.measurement import measure


@pytest.fixture(scope="module")
def enterprise(tmp_path_factory):
    engine, destination, worker = build(tmp_path_factory.mktemp("enterprise"), "enterprise")
    try:
        yield engine, destination, worker
    finally:
        destination.close()


def test_enterprise_economics_are_five_real_crm_events(enterprise):
    engine, _, worker = enterprise
    report = financial_audit(engine, measure(engine, FINISH), worker.client)
    # Independent arithmetic literal oracle; none of these values are frontend constants.
    expected = [18000000, 45000000, 100000000, 63000000, 120000000]
    assert sorted(r["amount_cents"] for r in report["opportunities"]) == sorted(expected)
    assert report["pipeline_cents"] == sum(expected) == 346000000
    assert report["opportunity_count"] == 5 and report["source_to_sql_parity"]
    assert report["assigned_segment_counts"] == {"mid_market": 48, "enterprise": 48, "strategic": 24}
    assert len(engine.rows("accounts")) == 120
    assert report["currency"] == describe(engine)["currency"] == specification()["currency"] == "USD"
    source = {r["source_key"]: json.loads(r["payload"]) for r in engine.rows("sources")}
    for opportunity in report["opportunities"]:
        event = source[opportunity["source_key"]]
        assert event["source"] == "crm" and event["data"]["amount_cents"] == opportunity["amount_cents"]
        assert event["data"]["currency"] == opportunity["currency"] == report["currency"]


def test_enterprise_preserves_all_execution_controls_and_denominators(enterprise):
    engine, _, worker = enterprise
    report = measure(engine, FINISH)
    assert sum(arm["assigned"] for arm in report["arms"].values()) == 120
    assert all(arm["assigned"] == arm["mature_accounts"] > 0 for arm in report["arms"].values())
    assert report["leakage_accounts"] == []
    assert report["arms"]["holdout"]["exposed_accounts"] == 0
    assert len([a for a in engine.rows("actions") if a["status"] == "blocked"]) == 2
    assert any(a["status"] == "reconciled" and a["attempts"] == 1 for a in engine.rows("actions"))
    assert any(a["attempts"] == 2 for a in engine.rows("actions"))
    assert len(worker.client.receipts()) == report["arms"]["treatment"]["exposed_accounts"]
    assert engine.audit_valid()


def test_opportunity_indices_are_fixed_independently_of_assignment(enterprise):
    engine, _, _ = enterprise
    config = specification()
    sources = {r["source_id"]: r["account_id"] for r in engine.rows("sources") if r["kind"] == "account"}
    expected = {sources[f'enterprise-account-{r["account_index"]:03}'] for r in config["opportunities"]}
    actual = {f["account_id"] for f in engine.rows("feedback") if f["kind"] == "opportunity_accepted"}
    assert actual == expected
    quotes = describe(engine)["scope_quotes"]
    assert all(q["amount_cents"] == q["sites"] * q["annual_site_value_cents"] for q in quotes)


@pytest.mark.parametrize("defect", ["amount", "count"])
def test_independent_financial_check_rejects_mart_discrepancy(enterprise, defect):
    engine, _, worker = enterprise
    report = copy.deepcopy(measure(engine, FINISH))
    report["arms"]["treatment"]["pipeline_cents" if defect == "amount" else "accepted_opportunities"] += 1
    with pytest.raises(ValueError, match="financial_mismatch"):
        financial_audit(engine, report, worker.client)


def test_financial_check_requires_exact_remote_source_readback(enterprise, monkeypatch):
    import httpx
    engine, _, worker = enterprise
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, request=httpx.Request("GET", "http://localhost"), json=[]))
    with pytest.raises(ValueError, match="readback_mismatch"):
        financial_audit(engine, measure(engine, FINISH), worker.client)


def test_profile_cannot_silently_rewrite_existing_workspace(tmp_path):
    engine, destination, _ = build(tmp_path / "fixture", "fixture")
    destination.close()
    with pytest.raises(ValueError, match="profile_mismatch"):
        build(tmp_path / "fixture", "enterprise")
    assert describe(engine)["profile"] == "fixture"


def test_original_fixture_demo_payload_remains_exact(tmp_path):
    from gtm.worker import reconcile
    engine, destination, worker = build(tmp_path / "small", "fixture")
    try:
        baseline = json.loads((Path(__file__).resolve().parents[1] / "docs/evidence/demo.json").read_text())
        assert measure(engine, FINISH) == baseline["measurement"]
        assert engine.rows("sources") == baseline["source_records"]
        assert engine.rows("actions") == baseline["actions"]
        assert reconcile(engine, worker.client) == baseline["reconciliation"]
    finally:
        destination.close()


def test_segmentation_and_owner_distribution_are_source_derived(engine):
    from gtm.enterprise import account_segment
    seed_enterprise(engine)
    assert {a["territory"] for a in engine.rows("accounts")} == {"NA", "EMEA"}
    fields = [json.loads(f["value"]) for f in engine.rows("fields") if f["name"] == "industry"]
    assert set(fields) == {"software", "manufacturing", "financial_services"}
    assert {account_segment(engine, a["id"]) for a in engine.rows("accounts")} == {"mid_market", "enterprise", "strategic"}


def test_browser_api_declares_enterprise_values_as_synthetic(enterprise):
    from fastapi.testclient import TestClient
    engine, destination, worker = enterprise
    with TestClient(create_app(engine, destination, worker)) as client:
        state = client.get("/api/state").json()
    assert state["scenario"]["synthetic"] and state["scenario"]["profile"] == "enterprise"
    assert state["scenario"]["currency"] == state["measurement"]["currency"] == "USD"
    assert state["scenario"]["locale"] == "en-US"
    assert all(q["currency"] == "USD" for q in state["scenario"]["scope_quotes"])
    assert all(f["currency"] == "USD" for f in state["outcomes"])
    assert "not revenue" in state["scenario"]["value_basis"]
    assert sum(a["pipeline_cents"] for a in state["measurement"]["arms"].values()) == 346000000


@pytest.mark.parametrize("currency", [None, "CAD", "usd", "EUR"])
def test_enterprise_rejects_missing_or_mixed_currency_events(enterprise, currency):
    engine, _, _ = enterprise
    event = copy.deepcopy(next(json.loads(s["payload"]) for s in engine.rows("sources")
                               if s["kind"] == "outcome" and json.loads(s["payload"])["data"]["kind"] == "opportunity_accepted"))
    event["source_id"] = "currency-negative-" + str(currency)
    event["data"]["business_id"] = event["source_id"]
    if currency is None:
        event["data"].pop("currency")
    else:
        event["data"]["currency"] = currency
    before = len(engine.rows("feedback"))
    with pytest.raises(ValueError, match="enterprise_outcome_currency_mismatch"):
        engine.ingest(event, FINISH)
    assert len(engine.rows("feedback")) == before


def test_independent_financial_audit_rejects_currency_relabel(enterprise):
    engine, _, worker = enterprise
    report = copy.deepcopy(measure(engine, FINISH))
    report["currency"] = "CAD"
    with pytest.raises(ValueError, match="measurement_currency_mismatch"):
        financial_audit(engine, report, worker.client)


def test_sql_rejects_host_injected_mixed_source_currency(enterprise, tmp_path):
    from gtm.engine import Engine
    engine, _, _ = enterprise
    faulty = Engine(tmp_path / "isolated-host-fault.sqlite")
    with engine.connection() as original, faulty.connection() as replica:
        original.backup(replica)
    source = next(s for s in engine.rows("sources") if s["kind"] == "outcome")
    bad = json.loads(source["payload"])
    bad["data"]["currency"] = "CAD"
    # Fault injection bypasses a guard ONLY in a disposable copy; normal source rows stay immutable.
    with faulty.connection() as db:
        db.execute("DROP TRIGGER source_no_update")
        db.execute("UPDATE sources SET payload=? WHERE source_key=?", (json.dumps(bad), source["source_key"]))
    with pytest.raises(ValueError, match="measurement_source_currency_mismatch"):
        measure(faulty, FINISH)
    with engine.connection() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='source_no_update'").fetchone()


def test_legacy_enterprise_workspace_cannot_be_relabelled(tmp_path):
    from gtm.engine import Engine
    from gtm.fixtures import START, record
    workspace = tmp_path / "legacy"
    engine = Engine(workspace / "control.sqlite")
    engine.ingest(record("crm", "old-enterprise", "atlas", "account", "enterprise-001.example", {"name": "Old synthetic account"}), START)
    with engine.connection() as db:
        db.execute("INSERT INTO runtime VALUES('scenario_profile','enterprise')")
    before = engine.rows("sources")
    with pytest.raises(ValueError, match="legacy_enterprise_currency_use_fresh_workspace"):
        build(workspace, "enterprise")
    assert engine.rows("sources") == before
    with engine.connection() as db:
        assert not db.execute("SELECT 1 FROM runtime WHERE key='enterprise_specification'").fetchone()


def test_enterprise_specification_is_pinned_not_read_as_a_new_label(engine, monkeypatch):
    import gtm.enterprise as module
    original = module.pin_specification(engine)
    changed = copy.deepcopy(original)
    changed["currency"], changed["locale"] = "CAD", "en-CA"
    monkeypatch.setattr(module, "specification", lambda: changed)
    assert describe(engine)["currency"] == "USD"
    with pytest.raises(ValueError, match="specification_changed_use_fresh_workspace"):
        module.pin_specification(engine)


def test_historical_fixture_metadata_remains_cad(ready):
    engine, _, _, _, _ = ready
    assert describe(engine)["currency"] == "CAD" and describe(engine)["locale"] == "en-CA"
