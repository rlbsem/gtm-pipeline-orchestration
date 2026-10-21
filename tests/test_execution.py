import copy
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from conftest import mutate
from gtm.contracts import DomainError
from gtm.fixtures import START
from gtm.store import digest
from gtm.worker import EngagementClient, Worker, reconcile

LATER = "2026-01-01T12:00:03Z"


def test_exact_approval_and_no_automatic_effect(seeded):
    account = next(c["account_id"] for c in seeded.rows("cohorts") if c["arm"] == "treatment")
    prepared = seeded.prepare(account, START)
    changed = copy.deepcopy(prepared)
    changed["payload"]["message"] = "Support is available immediately."
    with pytest.raises(DomainError, match="modified"):
        seeded.approve(account, changed, "demo-reviewer", START)
    with pytest.raises(DomainError, match="reviewer"):
        seeded.approve(account, prepared, "model", START)
    assert not seeded.rows("actions")
    holdout = next(c["account_id"] for c in seeded.rows("cohorts") if c["arm"] == "holdout")
    with pytest.raises(DomainError, match="treatment"):
        seeded.prepare(holdout, START)


@pytest.mark.parametrize("kind,data,source", [("owner", {"owner": "atlas-emea"}, "crm"),
    ("consent", {"allowed": False}, "web"), ("account", {"lifecycle": "customer"}, "crm"),
    ("intent", {"signal": "research"}, "web")])
def test_changed_authority_blocks_new_post(ready, kind, data, source):
    engine, destination, client, worker, action = ready
    mutate(engine, action["account_id"], kind, data, source=source)
    result = worker.dispatch(action["action_key"], LATER)
    assert result["status"] == "blocked"
    assert not client.receipts()
    assert destination.request_counts().get("POST", 0) == 0


def test_expired_review_blocks_new_effect(ready):
    _, destination, _, worker, action = ready
    assert worker.dispatch(action["action_key"], "2026-01-02T12:00:01Z")["status"] == "blocked"
    assert destination.request_counts().get("POST", 0) == 0


def test_lost_ack_reconciles_after_optout_without_new_post(ready):
    engine, destination, client, worker, action = ready
    destination.fault = "lost_ack"
    first = worker.dispatch(action["action_key"], START)
    assert first["status"] == "uncertain" and first["reason"] == "acknowledgement_lost"
    assert len(client.receipts()) == 1
    mutate(engine, action["account_id"], "consent", {"allowed": False}, source="web")
    second = Worker(engine, client).dispatch(action["action_key"], LATER)
    assert second["status"] == "reconciled"
    assert destination.request_counts()["POST"] == 1
    assert len(client.receipts()) == 1


def test_exact_content_readback_and_duplicate_enrollment(ready):
    engine, destination, client, worker, action = ready
    result = worker.dispatch(action["action_key"], START)
    assert result["status"] == "delivered"
    assert result["receipt"]["payload"] == json.loads(action["payload"])
    assert digest(result["receipt"]["payload"]) == action["payload_hash"]
    worker.dispatch(action["action_key"], LATER)
    assert destination.request_counts()["POST"] == 1
    changed = json.loads(action["payload"])
    changed["message"] += " Changed."
    assert client.enroll(changed, LATER).status_code == 409
    assert len(client.receipts()) == 1
    assert engine.audit_valid()


def test_rate_limit_backoff_and_exhaustion_survive_worker_restart(ready):
    engine, destination, client, worker, action = ready
    key = action["action_key"]
    for at in (START, "2026-01-01T12:00:03Z", "2026-01-01T12:00:08Z"):
        destination.fault = "rate_limit"
        assert Worker(engine, client).dispatch(key, at)["status"] == "waiting"
    assert worker.dispatch(key, "2026-01-01T12:00:20Z")["status"] == "exhausted"
    assert worker.dispatch(key, "2026-01-01T12:00:25Z")["status"] == "exhausted"
    assert destination.request_counts()["POST"] == 3 and not client.receipts()


def test_backoff_does_not_write_early(ready):
    engine, destination, client, worker, action = ready
    destination.fault = "rate_limit"
    worker.dispatch(action["action_key"], START)
    assert worker.dispatch(action["action_key"], "2026-01-01T12:00:01Z")["status"] == "waiting"
    assert destination.request_counts()["POST"] == 1


def test_receiver_requires_authentication(ready):
    engine, destination, _, _, action = ready
    bad = EngagementClient(destination.url, "wrong")
    with pytest.raises(httpx.HTTPStatusError):
        bad.receipts()
    assert Worker(engine, bad).dispatch(action["action_key"], START)["status"] == "uncertain"
    assert destination.request_counts().get("POST", 0) == 0


def test_remote_ahead_restore_fails_closed(ready, tmp_path):
    engine, destination, client, worker, action = ready
    # Real independent SQLite backup/restore; explicitly not a native cloud PITR experiment.
    snapshot = tmp_path / "snapshot.sqlite"
    with engine.connection() as db, sqlite3.connect(snapshot) as saved:
        db.backup(saved)
    assert worker.dispatch(action["action_key"], START)["status"] == "delivered"
    with sqlite3.connect(snapshot) as saved, engine.connection() as db:
        # Remove only from a disposable restoration copy to emulate a backup older than approval.
        saved.execute("DROP TRIGGER action_content_immutable")
        saved.execute("DELETE FROM actions")
        saved.commit()
        saved.backup(db)
    result = reconcile(engine, client)
    assert not result["safe_to_resume"]
    assert result["discrepancies"][0]["reason"] == "remote_ahead_missing_intent"
    assert len(client.receipts()) == 1


def test_receipt_tampering_blocks_recovery(ready):
    engine, destination, client, worker, action = ready
    worker.dispatch(action["action_key"], START)
    with sqlite3.connect(destination.path) as db:
        db.execute("UPDATE receipts SET payload_hash='wrong'")
    assert not reconcile(engine, client)["safe_to_resume"]
    assert worker.dispatch(action["action_key"], LATER)["status"] == "blocked"
    assert destination.request_counts()["POST"] == 1


def test_process_death_after_remote_commit_recovers(ready):
    engine, destination, client, worker, action = ready
    child_code = """
import os
from gtm.engine import Engine
from gtm.worker import EngagementClient,Worker
class DyingClient(EngagementClient):
    def enroll(self,payload,at):
        response=super().enroll(payload,at)
        if response.status_code==200: os._exit(73)
        return response
e=Engine(os.environ['TEST_CONTROL'])
c=DyingClient(os.environ['TEST_RECEIVER'],os.environ['TEST_EPHEMERAL_TOKEN'])
Worker(e,c).dispatch(os.environ['TEST_ACTION'],'2026-01-01T12:00:00Z')
"""
    env = dict(os.environ, TEST_CONTROL=str(engine.path), TEST_RECEIVER=destination.url,
               TEST_EPHEMERAL_TOKEN=destination.token, TEST_ACTION=action["action_key"])
    process = subprocess.run([sys.executable, "-c", child_code], env=env, timeout=20, capture_output=True)
    assert process.returncode == 73, process.stderr.decode()
    assert engine.rows("actions")[0]["attempts"] == 1
    assert worker.dispatch(action["action_key"], LATER)["status"] == "reconciled"
    assert destination.request_counts()["POST"] == 1


def test_concurrent_workers_create_one_effect(ready):
    engine, destination, client, worker, action = ready
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Worker(engine, client).dispatch(action["action_key"], START), range(2)))
    assert len(client.receipts()) == 1
    assert any(x["status"] in {"delivered", "reconciled"} for x in results)


def test_immutable_approval_and_audit(ready):
    engine, _, _, _, action = ready
    with engine.connection() as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable_approval"):
            db.execute("UPDATE actions SET payload='{}' WHERE action_key=?", (action["action_key"],))
        with pytest.raises(sqlite3.IntegrityError, match="immutable_audit"):
            db.execute("DELETE FROM audit")
    assert engine.audit_valid()
