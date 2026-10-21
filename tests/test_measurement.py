import copy
import sqlite3

import pytest

from gtm.contracts import DomainError
from gtm.engine import Engine
from gtm.fixtures import FINISH, START, outcome, record
from gtm.measurement import measure


def test_deterministic_account_assignment_ignores_order(seeded, tmp_path):
    expected = {x["account_id"]: x["arm"] for x in seeded.rows("cohorts")}
    assert set(expected.values()) == {"treatment", "holdout"}
    other = Engine(tmp_path / "other.sqlite")
    # Replay raw sources in reverse ACCOUNT order, preserving each account's internal dependencies.
    for a in reversed(seeded.rows("accounts")):
        sources = [s for s in seeded.rows("sources") if s["account_id"] == a["id"]]
        for source in sources:
            import json
            other.ingest(json.loads(source["payload"]), START)
        other.assign(a["id"], START)
    assert {x["account_id"]: x["arm"] for x in other.rows("cohorts")} == expected
    with other.connection() as db, pytest.raises(sqlite3.IntegrityError, match="immutable_cohort"):
        db.execute("UPDATE cohorts SET arm='treatment'")


def test_mature_denominator_and_independent_oracle(seeded):
    accounts = seeded.rows("accounts")
    for i, a in enumerate(accounts[:6]):
        outcome(seeded, a["id"], f"meeting-{i}", "meeting_qualified", "2026-01-05T00:00:00Z")
        outcome(seeded, a["id"], f"opp-{i}", "opportunity_accepted", "2026-01-09T00:00:00Z", (i+1)*10000)
    result = measure(seeded, FINISH)
    # Independent Python traversal of admitted outcomes, not a copy of the SQL query.
    for arm in ("treatment", "holdout"):
        ids = {c["account_id"] for c in seeded.rows("cohorts") if c["arm"] == arm}
        selected = [f for f in seeded.rows("feedback") if f["account_id"] in ids]
        expected_value = sum(f["amount_cents"] for f in selected if f["kind"] == "opportunity_accepted")
        assert result["arms"][arm]["mature_accounts"] == len(ids)
        assert result["arms"][arm]["pipeline_cents"] == expected_value
    immature = measure(seeded, "2026-01-10T00:00:00Z")
    assert all(a["mature_accounts"] == 0 and a["meeting_rate"] is None for a in immature["arms"].values())
    assert immature["meeting_rate_difference"] is None


def test_preexisting_and_out_of_window_pipeline_excluded(seeded):
    a = seeded.rows("accounts")[0]["id"]
    outcome(seeded, a, "preexisting", "opportunity_accepted", "2026-01-10T00:00:00Z", 99999999,
            created_at="2025-12-01T00:00:00Z")
    outcome(seeded, a, "too-late", "opportunity_accepted", "2026-02-01T00:00:00Z", 99999999)
    outcome(seeded, a, "valid", "opportunity_accepted", "2026-01-10T00:00:00Z", 50000)
    assert sum(x["pipeline_cents"] for x in measure(seeded, FINISH)["arms"].values()) == 50000


def test_late_arrival_and_duplicate_business_outcome(seeded):
    a = seeded.rows("accounts")[0]["id"]
    outcome(seeded, a, "late-meeting", "meeting_qualified", "2026-01-10T00:00:00Z", received_at="2026-02-04T00:00:00Z")
    assert sum(x["qualified_meetings"] for x in measure(seeded, FINISH)["arms"].values()) == 0
    assert sum(x["qualified_meetings"] for x in measure(seeded, "2026-02-05T00:00:00Z")["arms"].values()) == 1
    with seeded.connection() as db:
        a = seeded.account(db, a)
    event = record("engagement", "duplicate-event", a["brand"], "outcome", a["domain"],
                   {"kind": "meeting_qualified", "business_id": "late-meeting", "origin": "organic",
                    "created_at": "2026-01-10T00:00:00Z"}, "2026-01-10T00:00:00Z", a["id"])
    assert seeded.ingest(event, "2026-02-05T00:00:00Z")["reason"] == "duplicate_business_outcome"
    assert len(seeded.rows("feedback")) == 1


def test_outcome_requires_actual_enrollment_and_valid_transition(ready):
    engine, _, client, worker, action = ready
    with pytest.raises(DomainError, match="enrollment"):
        outcome(engine, action["account_id"], "reply", "reply_positive", START, action_key=action["action_key"])
    worker.dispatch(action["action_key"], START)
    with pytest.raises(DomainError, match="transition"):
        outcome(engine, action["account_id"], "meeting", "meeting_qualified", START,
                action_key=action["action_key"], parent_id="missing")
    outcome(engine, action["account_id"], "reply", "reply_positive", START, action_key=action["action_key"], client=client)
    outcome(engine, action["account_id"], "meeting", "meeting_qualified", START,
            action_key=action["action_key"], parent_id="reply", client=client)
    assert len(engine.rows("feedback")) == 2


def test_experiments_do_not_mix(seeded):
    p = copy.deepcopy(seeded.policy)
    p["experiment"] = "future-experiment"
    other = Engine(seeded.path, p)
    assert measure(other, FINISH)["accounts"] == []


def test_holdout_leakage_is_reported(ready):
    engine, _, _, worker, action = ready
    worker.dispatch(action["action_key"], START)
    with engine.connection() as db:
        db.execute("DROP TRIGGER cohort_no_update")
        db.execute("UPDATE cohorts SET arm='holdout' WHERE account_id=?", (action["account_id"],))
    result = measure(engine, FINISH)
    assert action["account_id"] in result["leakage_accounts"]
    assert not result["comparison_valid"]
