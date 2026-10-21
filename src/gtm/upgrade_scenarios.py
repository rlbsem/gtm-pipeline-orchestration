import json
from pathlib import Path

from .fixtures import record, seed

SCENARIO = "2026-01-21T12:00:00Z"


def cases():
    return json.loads(Path(__file__).with_name("upgrade_cases.json").read_text())


def mutate(engine, account, kind, data, *, source="crm", source_id="upgrade-mutation", at=SCENARIO):
    return engine.ingest(record(source, source_id, account["brand"], kind, account["domain"], data, at, account["id"]), at)


def fixture(engine, case):
    seed(engine)
    cohort = next(c for c in engine.rows("cohorts") if c["arm"] == "treatment")
    with engine.connection() as db:
        account = engine.account(db, cohort["account_id"])
    if case["mutation"] != "stale":
        mutate(engine, account, "intent", {"signal": "pricing"}, source="web", source_id="upgrade-pricing")
    if case["id"] == "fresh_inbound":
        mutate(engine, account, "inbound", {"email": "review@" + account["domain"], "request": "pricing", "consent": True},
               source="web", source_id="upgrade-inquiry")
    if case["mutation"] == "optout":
        mutate(engine, account, "consent", {"allowed": False}, source="web")
    if case["mutation"] == "enrichment":
        mutate(engine, account, "account", {"employees": 25000, "owner": "harbor-emea"}, source="enrichment")
    documents = ([{"source_key": "untrusted-doc:" + case["id"], "observed_at": SCENARIO, "content": case["document"]}]
                 if case.get("document") else [])
    return account, documents
