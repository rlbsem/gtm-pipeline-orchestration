"""Larger commercial fixture using the unchanged authority, execution and measurement engines."""
import json
from pathlib import Path

from .fixtures import START, record
from .store import canonical, digest
from .currency import metadata


def specification():
    return json.loads(Path(__file__).with_name("enterprise-scenario.json").read_text())


def pin_specification(engine):
    config = specification()
    with engine.transaction() as db:
        prior = db.execute("SELECT value FROM runtime WHERE key='enterprise_specification'").fetchone()
        if prior and json.loads(prior[0]) != config:
            raise ValueError("enterprise_specification_changed_use_fresh_workspace")
        if not prior:
            if db.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
                raise ValueError("legacy_enterprise_currency_use_fresh_workspace")
            db.execute("INSERT INTO runtime VALUES('enterprise_specification',?)", (canonical(config),))
        db.execute("INSERT OR IGNORE INTO runtime VALUES('scenario_profile','enterprise')")
        metadata(db)
    return config


def pinned_specification(engine):
    with engine.connection() as db:
        metadata(db)
        row = db.execute("SELECT value FROM runtime WHERE key='enterprise_specification'").fetchone()
    if not row:
        raise ValueError("enterprise_specification_required")
    return json.loads(row[0])


def enterprise_outcome(engine, account, suffix, kind, at, amount=0, action_key=None, parent_id=None,
                       received_at=None, client=None, created_at=None):
    with engine.connection() as db:
        a, money = engine.account(db, account), metadata(db)
    event = record("crm" if kind == "opportunity_accepted" else "engagement", suffix, a["brand"], "outcome", a["domain"],
                   {"kind": kind, "business_id": suffix, "origin": "sequence" if action_key else "organic",
                    "action_key": action_key, "parent_id": parent_id, "amount_cents": amount,
                    "currency": money["currency"], "created_at": created_at or at}, at, account)
    if client:
        event = client.emit_feedback(event)
    return engine.ingest(event, received_at or at)


def segment(employees):
    if employees is None:
        return "unverified"
    return "strategic" if employees >= 10000 else "enterprise" if employees >= 1000 else "mid_market"


def account_segment(engine, account_id):
    with engine.connection() as db:
        row = db.execute("SELECT value FROM fields WHERE account_id=? AND name='employees' AND source='crm'",
                         (account_id,)).fetchone()
    return segment(json.loads(row[0]) if row else None)


def interactive_value(engine, account_id):
    config = pinned_specification(engine)["segments"][account_segment(engine, account_id)]
    return config["interactive_sites"] * config["annual_site_value_cents"]


def seed_enterprise(engine):
    if engine.rows("accounts"):
        raise ValueError("fixture_workspace_must_be_empty")
    config = pin_specification(engine)
    accounts = []
    for index in range(config["population"]):
        segment_config = config["segments"][config["segment_cycle"][index % 5]]
        employees = segment_config["employees"][(index // 5) % 4]
        brand = "atlas" if index < 80 else "harbor"
        territory = "NA" if (index // 3) % 2 == 0 else "EMEA"
        industry = ["software", "manufacturing", "financial_services"][index % 3]
        domain = f"enterprise-{index + 1:03}.example"
        name = ["Aster", "Cobalt", "Meridian", "Juniper", "Solstice", "Arbor"][index % 6]
        account = engine.ingest(record("crm", f"enterprise-account-{index:03}", brand, "account", domain,
            {"name": f"{name} {industry.replace('_', ' ').title()} {index + 1:03}", "employees": employees,
             "industry": industry, "territory": territory, "owner": brand + "-" + territory.lower(),
             "lifecycle": "prospect"}), START)["account_id"]
        engine.ingest(record("crm", f"enterprise-contact-{index:03}", brand, "contact", domain,
                             {"email": "review@" + domain, "consent": True}, account_id=account), START)
        engine.ingest(record("web", f"enterprise-intent-{index:03}", brand, "intent", domain,
                             {"signal": "pricing"}, account_id=account), START)
        engine.assign(account, START)
        accounts.append(account)
    return accounts


def replay_enterprise(engine, destination, worker):
    accounts = seed_enterprise(engine)
    config = pinned_specification(engine)
    cohorts = {row["account_id"]: row for row in engine.rows("cohorts")}
    treatment = [a for a in accounts if cohorts[a]["arm"] == "treatment"]
    # Outcome indices/scopes are immutable fixture inputs, never selected to favor an arm.
    outcome_accounts = {accounts[i] for i in config["meetings"]}
    operational = [a for a in treatment if a not in outcome_accounts]
    pending, owner_change, optout, lost_ack, rate_limit = operational[-1], *operational[:4]
    with engine.connection() as db:
        routing = [engine.account(db, accounts[i]) for i in (5, 12, 28, 59, 83, 114)]
    for index, account in enumerate(routing):
        engine.ingest(record("web", f"enterprise-inquiry-{index}", account["brand"], "inbound", account["domain"],
            {"email": "review@" + account["domain"], "request": "pricing", "consent": True}, account_id=account["id"]), START)
    for account_id in treatment:
        if account_id == pending:
            continue
        prepared = engine.prepare(account_id, START)
        action = engine.approve(account_id, prepared, "demo-reviewer", START)
        with engine.connection() as db:
            account = engine.account(db, account_id)
        if account_id == owner_change:
            alternative = account["brand"] + ("-emea" if account["territory"] == "NA" else "-na")
            engine.ingest(record("crm", "enterprise-owner-change", account["brand"], "owner", account["domain"],
                                 {"owner": alternative}, "2026-01-01T12:00:01Z", account_id), "2026-01-01T12:00:01Z")
        if account_id == optout:
            engine.ingest(record("web", "enterprise-optout", account["brand"], "consent", account["domain"],
                                 {"allowed": False}, "2026-01-01T12:00:01Z", account_id), "2026-01-01T12:00:01Z")
        destination.fault = "lost_ack" if account_id == lost_ack else "rate_limit" if account_id == rate_limit else "none"
        state = worker.dispatch(action["action_key"], "2026-01-01T12:00:02Z")
        if state["status"] in {"uncertain", "waiting"}:
            worker.dispatch(action["action_key"], "2026-01-01T12:00:05Z")
    actions = {a["account_id"]: a for a in engine.rows("actions")}
    opportunities = {row["account_index"]: row for row in config["opportunities"]}
    quotes = []
    for index in config["meetings"]:
        account_id = accounts[index]
        action_key = actions[account_id]["action_key"] if account_id in actions else None
        reply, meeting = f"enterprise-reply-{index:03}", f"enterprise-meeting-{index:03}"
        enterprise_outcome(engine, account_id, reply, "reply_positive", "2026-01-04T12:00:00Z", action_key=action_key, client=worker.client)
        enterprise_outcome(engine, account_id, meeting, "meeting_qualified", "2026-01-07T12:00:00Z",
                action_key=action_key, parent_id=reply if action_key else None, client=worker.client)
        if index in opportunities:
            quote = opportunities[index]
            label = config["segment_cycle"][index % 5]
            unit = config["segments"][label]["annual_site_value_cents"]
            business_id = f"enterprise-opportunity-{index:03}"
            enterprise_outcome(engine, account_id, business_id, "opportunity_accepted", "2026-01-15T12:00:00Z",
                    amount=quote["sites"] * unit, action_key=action_key, parent_id=meeting if action_key else None,
                    client=worker.client)
            quotes.append({**quote, "business_id": business_id, "account_id": account_id, "segment": label,
                           "annual_site_value_cents": unit, "amount_cents": quote["sites"] * unit, "currency": config["currency"],
                           "specification_sha256": digest(config)})
    # Keep an eligible unactivated account for browser approval and recovery exercises.
    with engine.connection() as db:
        account = engine.account(db, pending)
    engine.ingest(record("web", "enterprise-current-signal", account["brand"], "intent", account["domain"],
                         {"signal": "pricing"}, "2026-01-21T12:00:00Z", pending), "2026-01-21T12:00:00Z")
    with engine.transaction() as db:
        db.execute("INSERT INTO runtime VALUES('enterprise_scope_quotes',?)", (json.dumps(quotes, sort_keys=True),))
    return quotes


def describe(engine):
    with engine.connection() as db:
        profile = db.execute("SELECT value FROM runtime WHERE key='scenario_profile'").fetchone()
        quotes = db.execute("SELECT value FROM runtime WHERE key='enterprise_scope_quotes'").fetchone()
    profile = profile[0] if profile else "fixture"
    config = pinned_specification(engine) if profile == "enterprise" else None
    with engine.connection() as db:
        money = metadata(db)
    return {"profile": profile, "synthetic": True, **money,
            "value_basis": config["value_basis"] if config else "Historical CAD regression fixture values",
            "denomination": config["denomination"] if config else "Original implicit-CAD fixture; no conversion.",
            "specification_sha256": digest(config) if config else None,
            "scope_quotes": json.loads(quotes[0]) if quotes else []}
