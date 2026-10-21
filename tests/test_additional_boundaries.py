import json

import pytest

from conftest import mutate
from gtm.contracts import DomainError
from gtm.fixtures import FINISH, START, outcome, record
from gtm.measurement import measure
from gtm.worker import verify_receipt


def test_shared_domain_assignment_never_splits_operating_units(engine):
    ids = []
    for brand in ("atlas", "harbor"):
        a = engine.ingest(record("crm", "source-account", brand, "account", "shared.example",
                          {"name": brand, "employees": 300, "industry": "software", "territory": "NA",
                           "owner": brand+"-na", "lifecycle": "prospect"}), START)["account_id"]
        engine.ingest(record("crm", "contact", brand, "contact", "shared.example",
                             {"email": "review@shared.example", "consent": True}, account_id=a), START)
        engine.ingest(record("web", "signal", brand, "intent", "shared.example", {"signal": "pricing"}, account_id=a), START)
        ids.append(engine.assign(a, START))
    assert ids[0]["arm"] == ids[1]["arm"]
    assert ids[0]["account_id"] != ids[1]["account_id"]


def test_enrichment_cannot_refresh_stale_crm_owner(seeded):
    a = seeded.rows("accounts")[0]["id"]
    mutate(seeded, a, "account", {"employees": 500, "industry": "software"}, at="2027-02-01T12:00:00Z", source="enrichment")
    mutate(seeded, a, "intent", {"signal": "pricing"}, at="2027-02-01T12:00:00Z", source="web", source_id="fresh-intent")
    score = seeded.score(a, "2027-02-01T12:00:00Z")
    assert not score["eligible"] and "owner_authority_stale" in score["reasons"]


@pytest.mark.parametrize("change", [{"payload_hash": "bad"},{"accepted_at": None},{"receipt_id": "wrong"},{"unexpected": True}])
def test_malformed_receipts_never_establish_effect(ready, change):
    _, _, _, _, action = ready
    receipt = {"action_key": action["action_key"], "payload_hash": action["payload_hash"],
               "payload": json.loads(action["payload"]), "accepted_at": START,
               "receipt_id": "rcpt_"+action["payload_hash"][:24]}
    receipt.update(change)
    with pytest.raises(DomainError):
        verify_receipt(action, receipt)


def test_outcome_origin_and_creation_contracts(seeded):
    a = seeded.rows("accounts")[0]
    bad = record("crm", "bad-opportunity", a["brand"], "outcome", a["domain"],
                 {"kind": "opportunity_accepted", "business_id": "opp", "origin": "organic", "amount_cents": 5000},
                 "2026-01-05T00:00:00Z", a["id"])
    with pytest.raises(DomainError, match="creation_time"):
        seeded.ingest(bad, "2026-01-05T00:00:00Z")
    bad["data"]["created_at"] = "2026-01-06T00:00:00Z"
    with pytest.raises(DomainError, match="before_creation"):
        seeded.ingest(bad, "2026-01-05T00:00:00Z")
    assert not seeded.rows("feedback")


def test_pipeline_multiple_opportunities_no_meeting_fanout(seeded):
    a = seeded.rows("accounts")[0]["id"]
    for i in range(3):
        outcome(seeded, a, f"meeting-{i}", "meeting_qualified", "2026-01-05T00:00:00Z")
    for i in range(2):
        outcome(seeded, a, f"opportunity-{i}", "opportunity_accepted", "2026-01-09T00:00:00Z", (i+1)*10000)
    result = measure(seeded, FINISH)
    assert sum(x["pipeline_cents"] for x in result["arms"].values()) == 30000
    assert sum(x["accounts_with_meetings"] for x in result["arms"].values()) == 1
    assert sum(x["qualified_meetings"] for x in result["arms"].values()) == 3
