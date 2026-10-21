"""Deterministic fictional accounts. No fixture values are claimed as customer outcomes."""
from .engine import Engine

START = "2026-01-01T12:00:00Z"
FINISH = "2026-02-02T12:00:00Z"


def record(source, source_id, brand, kind, domain, data, at=START, account_id=None):
    return {"version": "source/v1", "source": source, "source_id": source_id, "brand": brand,
            "kind": kind, "domain": domain, "account_id": account_id, "observed_at": at, "data": data}


def seed(engine: Engine):
    if engine.rows("accounts"):
        raise ValueError("fixture_workspace_must_be_empty")
    accounts = []
    for index in range(24):
        brand = "atlas" if index < 16 else "harbor"
        domain = f"account-{index + 1:02}.example"
        name = ["Meridian", "Cobalt", "Summit", "Juniper", "Arbor", "Solstice"][index % 6] + f" Labs {index + 1:02}"
        item = record("crm", f"account-{index}", brand, "account", domain,
                      {"name": name, "employees": 150 + index * 30, "industry": "software",
                       "territory": "NA", "owner": brand + "-na", "lifecycle": "prospect"})
        account_id = engine.ingest(item, START)["account_id"]
        engine.ingest(record("crm", f"contact-{index}", brand, "contact", domain,
                             {"email": "review@" + domain, "consent": True}, account_id=account_id), START)
        engine.ingest(record("web", f"intent-{index}", brand, "intent", domain,
                             {"signal": "pricing"}, account_id=account_id), START)
        engine.assign(account_id, START)
        accounts.append(account_id)
    return accounts


def outcome(engine, account, suffix, kind, at, amount=0, action_key=None, parent_id=None, received_at=None, client=None, created_at=None):
    with engine.connection() as db:
        a = engine.account(db, account)
    event = record("crm" if kind == "opportunity_accepted" else "engagement", suffix,
                         a["brand"], "outcome", a["domain"], {"kind": kind, "business_id": suffix,
                         "origin": "sequence" if action_key else "organic", "action_key": action_key,
                         "parent_id": parent_id, "amount_cents": amount, "created_at": created_at or at}, at, account)
    if client:
        event = client.emit_feedback(event)
    return engine.ingest(event, received_at or at)


def replay(engine, destination, worker):
    accounts = seed(engine)
    results = []
    treatment = [r for r in engine.rows("cohorts") if r["arm"] == "treatment"]
    with engine.connection() as db:
        a = engine.account(db, treatment[0]["account_id"])
    inbound = record("web", "pricing-form-001", a["brand"], "inbound", a["domain"],
                     {"email": "review@" + a["domain"], "request": "pricing", "consent": True}, START, a["id"])
    route = engine.ingest(inbound, START)
    duplicate = engine.ingest(inbound, START)
    for index, cohort in enumerate(treatment):
        if index == len(treatment) - 1:
            # Leave one eligible treatment account untouched for an interactive reviewer.
            continue
        account_id = cohort["account_id"]
        prepared = engine.prepare(account_id, START)
        action = engine.approve(account_id, prepared, "demo-reviewer", START)
        if index == 0:
            destination.fault = "lost_ack"
        elif index == 1:
            destination.fault = "rate_limit"
        elif index == 2:
            with engine.connection() as db:
                a = engine.account(db, account_id)
            engine.ingest(record("crm", "owner-change-demo", a["brand"], "owner", a["domain"],
                                 {"owner": a["brand"] + "-emea"}, "2026-01-01T12:00:01Z", account_id),
                          "2026-01-01T12:00:01Z")
        elif index == 3:
            with engine.connection() as db:
                a = engine.account(db, account_id)
            engine.ingest(record("web", "optout-demo", a["brand"], "consent", a["domain"],
                                 {"allowed": False}, "2026-01-01T12:00:01Z", account_id),
                          "2026-01-01T12:00:01Z")
        result = worker.dispatch(action["action_key"], "2026-01-01T12:00:02Z")
        if result["status"] == "waiting":
            result = worker.dispatch(action["action_key"], "2026-01-01T12:00:05Z")
        if result["status"] == "uncertain":
            result = worker.dispatch(action["action_key"], "2026-01-01T12:00:05Z")
        results.append(result)
        if index % 3 == 0 and result["receipt"]:
            reply = f"reply-{index}"
            meeting = f"meeting-{index}"
            outcome(engine, account_id, reply, "reply_positive", "2026-01-04T12:00:00Z", action_key=action["action_key"], client=worker.client)
            outcome(engine, account_id, meeting, "meeting_qualified", "2026-01-07T12:00:00Z",
                    action_key=action["action_key"], parent_id=reply, client=worker.client)
            outcome(engine, account_id, f"opportunity-{index}", "opportunity_accepted", "2026-01-12T12:00:00Z",
                    amount=(index + 2) * 100000, action_key=action["action_key"], parent_id=meeting, client=worker.client)
    holdout = [r for r in engine.rows("cohorts") if r["arm"] == "holdout"]
    for index, cohort in enumerate(holdout):
        if index % 5 == 0:
            outcome(engine, cohort["account_id"], f"organic-meeting-{index}", "meeting_qualified", "2026-01-09T12:00:00Z", client=worker.client)
            outcome(engine, cohort["account_id"], f"organic-opportunity-{index}", "opportunity_accepted",
                    "2026-01-20T12:00:00Z", (index + 1) * 100000, client=worker.client)
    route = next(x for x in engine.rows("routes") if x["source_key"] == route["source_key"])
    # Visible operator exceptions outside the eligible experiment denominator.
    customer = engine.ingest(record("crm", "existing-customer", "atlas", "account", "existing.example",
                             {"name": "Existing Customer · Service", "employees": 400, "industry": "software",
                              "territory": "NA", "owner": "atlas-na", "lifecycle": "customer"}), START)["account_id"]
    engine.ingest(record("crm", "existing-contact", "atlas", "contact", "existing.example",
                         {"email": "review@existing.example", "consent": True}, account_id=customer), START)
    engine.ingest(record("web", "existing-service-inquiry", "atlas", "inbound", "existing.example",
                         {"email": "review@existing.example", "request": "support", "consent": True}, account_id=customer), START)
    engine.ingest(record("enrichment", "stale-discovery", "harbor", "account", "unverified.example",
                         {"name": "Unverified Discovery", "employees": 1000, "industry": "software", "territory": "NA"},
                         "2025-11-01T00:00:00Z"), START)
    for suffix in ("a", "b"):
        engine.ingest(record("crm", "shared-crm-" + suffix, "atlas", "account", "shared.example",
                             {"name": "Shared Domain · " + suffix.upper(), "employees": 200, "industry": "software",
                              "territory": "NA", "owner": "atlas-na", "lifecycle": "prospect"}), START)
    engine.ingest(record("web", "ambiguous-inquiry", "atlas", "inbound", "shared.example",
                         {"email": "review@shared.example", "request": "pricing", "consent": True}), START)
    with engine.connection() as db:
        pending = engine.account(db, treatment[-1]["account_id"])
    engine.ingest(record("web", "current-review-signal", pending["brand"], "intent", pending["domain"],
                         {"signal": "pricing"}, "2026-01-21T12:00:00Z", pending["id"]), "2026-01-21T12:00:00Z")
    return {"accounts": len(accounts), "treatment": len(treatment), "holdout": len(holdout),
            "deliveries": results, "inbound": route, "duplicate_inbound": duplicate}
