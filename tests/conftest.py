import pytest

from gtm.destination import Destination
from gtm.engine import Engine
from gtm.fixtures import START, record, seed
from gtm.worker import EngagementClient, Worker


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path / "control.sqlite")


@pytest.fixture
def seeded(engine):
    seed(engine)
    return engine


@pytest.fixture
def ready(seeded, tmp_path):
    destination = Destination(tmp_path / "engagement.sqlite").start()
    client = EngagementClient(destination.url, destination.token)
    worker = Worker(seeded, client)
    account = next(c["account_id"] for c in seeded.rows("cohorts") if c["arm"] == "treatment")
    prepared = seeded.prepare(account, START)
    action = seeded.approve(account, prepared, "demo-reviewer", START)
    try:
        yield seeded, destination, client, worker, action
    finally:
        destination.close()


def mutate(engine, account_id, kind, data, at="2026-01-01T12:00:01Z", source="crm", source_id=None):
    with engine.connection() as db:
        a = engine.account(db, account_id)
    return engine.ingest(record(source, source_id or "mutation-" + kind, a["brand"], kind, a["domain"],
                         data, at, account_id), at)
