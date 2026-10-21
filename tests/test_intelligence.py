import copy
import json

import pytest
from pydantic import ValidationError

from gtm.contracts import DomainError, Record
from gtm.fixtures import START, record
from conftest import mutate


def account_input(source="crm", source_id="one", brand="atlas", domain="meridian.example"):
    return record(source, source_id, brand, "account", domain,
                  {"name": "Meridian", "employees": 200, "industry": "software", "territory": "NA",
                   "owner": brand + "-na", "lifecycle": "prospect"})


@pytest.mark.parametrize("field,value", [("brand", "other"),("kind", "magic"),("source", "unknown"),
    ("domain", "real-company.com"),("observed_at", "2026-01-01T12:00:00"),
    ("observed_at", "2026-01-01T12:00:00-05:00"),("source_id", "../bad"),("version", "source/v2")])
def test_closed_contract(field, value):
    data = account_input()
    data[field] = value
    with pytest.raises((ValidationError, ValueError)):
        Record.model_validate(data)


def test_source_collision_and_immutable_history(engine):
    data = account_input()
    admitted = engine.ingest(data, START)
    assert engine.ingest(data, START)["status"] == "duplicate"
    data["data"]["employees"] = 999
    with pytest.raises(DomainError, match="collision"):
        engine.ingest(data, START)
    assert len(engine.rows("sources")) == 1
    with engine.connection() as db, pytest.raises(Exception, match="immutable_source"):
        db.execute("DELETE FROM sources WHERE account_id=?", (admitted["account_id"],))


@pytest.mark.parametrize("data", [{"employees": -1},{"employees": True},{"employees": "100"},
    {"employees": 10000001},{"hidden_score": 100},{"owner": "harbor-na"},{"lifecycle": "won"}])
def test_invalid_account_content(engine, data):
    source = account_input()
    source["data"].update(data)
    with pytest.raises(DomainError):
        engine.ingest(source, START)
    assert not engine.rows("accounts")


def test_discovery_requires_crm_confirmation(engine):
    source = account_input("enrichment")
    first = engine.ingest(source, START)["account_id"]
    assert engine.rows("accounts")[0]["owner"] == ""
    assert not engine.score(first, START)["eligible"]
    crm = account_input(source_id="crm-confirmation")
    assert engine.ingest(crm, START)["account_id"] == first
    assert engine.rows("accounts")[0]["owner"] == "atlas-na"


def test_conflicting_enrichment_cannot_overwrite_crm(seeded):
    account = seeded.rows("accounts")[0]
    mutate(seeded, account["id"], "account", {"employees": 10000, "owner": "harbor-emea"}, source="enrichment")
    assert next(f for f in seeded.rows("fields") if f["account_id"] == account["id"] and f["name"] == "employees")["value"] == "150"
    assert next(a for a in seeded.rows("accounts") if a["id"] == account["id"])["owner"] == "atlas-na"
    assert any(a["event"] == "field_conflict" for a in seeded.rows("audit"))


def test_distinct_crm_ids_domain_ambiguity_and_brand_scope(engine):
    ids = [engine.ingest(account_input(source_id=x), START)["account_id"] for x in ("crm-A", "crm-B")]
    other = engine.ingest(account_input(source_id="crm-C", brand="harbor"), START)["account_id"]
    assert len(set(ids + [other])) == 3
    inbound = record("web", "form-one", "atlas", "inbound", "meridian.example",
                     {"email": "review@meridian.example", "request": "pricing", "consent": True})
    result = engine.ingest(inbound, START)
    assert result["status"] == "exception" and result["reason"] == "ambiguous_identity"
    inbound["account_id"] = other
    inbound["source_id"] = "wrong-brand"
    with pytest.raises(DomainError, match="brand_or_domain"):
        engine.ingest(inbound, START)


def test_duplicate_signals_do_not_accumulate_and_decay(seeded):
    account = seeded.rows("accounts")[0]["id"]
    before = seeded.score(account, START)
    for i in range(20):
        mutate(seeded, account, "intent", {"signal": "pricing"}, at=START, source="web", source_id=f"dup-{i}")
    after = seeded.score(account, START)
    assert before["intent"] == after["intent"] == 50
    late = seeded.score(account, "2026-02-02T12:00:00Z")
    assert late["intent"] == 0 and not late["eligible"]


def test_stale_fields_and_future_sources_do_not_promote(engine):
    source = account_input("enrichment")
    source["observed_at"] = "2025-01-01T12:00:00Z"
    account = engine.ingest(source, START)["account_id"]
    assert engine.score(account, START)["fit"] == 20
    source["observed_at"] = "2026-01-02T12:00:00Z"
    with pytest.raises(DomainError, match="future"):
        engine.ingest(source, START)


def test_out_of_order_owner_cannot_regress(seeded):
    a = seeded.rows("accounts")[0]["id"]
    mutate(seeded, a, "owner", {"owner": "atlas-emea"}, "2026-01-03T00:00:00Z")
    mutate(seeded, a, "owner", {"owner": "atlas-na"}, "2026-01-02T00:00:00Z", source_id="late-owner")
    assert next(x for x in seeded.rows("accounts") if x["id"] == a)["owner"] == "atlas-emea"


def test_late_optout_wins_but_old_optin_does_not(seeded):
    a = seeded.rows("accounts")[0]["id"]
    mutate(seeded, a, "consent", {"allowed": False}, "2026-01-03T00:00:00Z")
    mutate(seeded, a, "consent", {"allowed": True}, "2026-01-02T00:00:00Z", source_id="late-optin")
    assert not next(x for x in seeded.rows("contacts") if x["account_id"] == a)["consent"]


@pytest.mark.parametrize("inquiry_type,consent,lifecycle,expected", [
    ("pricing",True,"prospect","seller_review"),("support",True,"prospect","service_review"),
    ("pricing",True,"customer","service_review"),("pricing",False,"prospect","exception")])
def test_inbound_routing_uses_current_relationship(seeded, inquiry_type, consent, lifecycle, expected):
    a = seeded.rows("accounts")[0]
    if lifecycle == "customer":
        mutate(seeded, a["id"], "account", {"lifecycle": "customer"})
    inquiry = record("web", "new-inquiry", a["brand"], "inbound", a["domain"],
                     {"email": "review@"+a["domain"], "request": inquiry_type, "consent": consent},
                     "2026-01-01T12:00:02Z", a["id"])
    assert seeded.ingest(inquiry, inquiry["observed_at"])["status"] == expected
    assert seeded.ingest(inquiry, inquiry["observed_at"])["status"] == "duplicate"
    assert len(seeded.rows("routes")) == 1


def test_versioned_score_explains_evidence(seeded):
    a = seeded.rows("accounts")[0]["id"]
    score = seeded.score(a, START)
    assert score["fit"] == 100 and score["policy_version"] == "qualification/v1"
    assert all(x["source_key"] for x in score["field_evidence"] + score["signals"])
    updated = copy.deepcopy(seeded.policy)
    updated["version"] = "qualification/v2"
    updated["fit_min"] = 101
    from gtm.engine import Engine
    other = Engine(seeded.path, updated)
    assert not other.score(a, START)["eligible"]
    assert other.policy_hash != seeded.policy_hash
    assert json.loads(seeded.rows("decisions")[0]["body"])["policy_version"] == "qualification/v1"
