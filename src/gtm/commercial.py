"""Independent source-event traversal: no SQL mart aggregates or frontend totals are inputs."""
import json
from collections import Counter

import httpx

from .enterprise import account_segment
from .store import digest


def financial_audit(engine, measurement, client):
    cohorts = {row["account_id"]: row for row in engine.rows("cohorts") if row["experiment"] == measurement["experiment"]}
    remote = httpx.get(client.url + "/feedback", headers=client.headers, timeout=5, follow_redirects=False)
    remote.raise_for_status()
    actual = {f'{r["source"]}:{r["brand"]}:{r["source_id"]}': r for r in remote.json()}
    values = {arm: 0 for arm in ("treatment", "holdout")}
    counts, seen, ledger = Counter(), set(), []
    names = {a["id"]: a["name"] for a in engine.rows("accounts")}
    for source in engine.rows("sources"):
        record = json.loads(source["payload"])
        if record["kind"] != "outcome" or record["source"] != "crm" or source["disposition"] != "accepted":
            continue
        data, account = record["data"], source["account_id"]
        if data["kind"] != "opportunity_accepted" or account not in cohorts:
            continue
        cohort, cutoff = cohorts[account], measurement["as_of"]
        if not (cohort["window_end"] <= cutoff and cohort["assigned_at"] <= data["created_at"] <= record["observed_at"]
                and cohort["assigned_at"] <= record["observed_at"] < cohort["window_end"]
                and record["observed_at"] <= cutoff and source["received_at"] <= cutoff):
            continue
        key = (account, data["business_id"])
        if key in seen:
            continue
        seen.add(key)
        if actual.get(source["source_key"]) != record:
            raise ValueError("crm_outcome_independent_http_readback_mismatch")
        arm = cohort["arm"]
        values[arm] += data["amount_cents"]
        counts[arm] += 1
        ledger.append({"account_id": account, "account_name": names[account], "business_id": data["business_id"],
                       "source_key": source["source_key"], "source_record_sha256": digest(record),
                       "segment": account_segment(engine, account), "arm": arm, "origin": data["origin"],
                       "amount_cents": data["amount_cents"], "action_key": data["action_key"],
                       "created_at": data["created_at"], "occurred_at": record["observed_at"],
                       "received_at": source["received_at"]})
    for arm in values:
        if (measurement["arms"][arm]["pipeline_cents"] != values[arm]
                or measurement["arms"][arm]["accepted_opportunities"] != counts[arm]):
            raise ValueError("source_to_measurement_financial_mismatch")
    return {"method": "Independent Python traversal of admitted CRM source events plus fresh HTTP feedback readback",
            "source_to_sql_parity": True, "currency": "CAD", "synthetic": True,
            "pipeline_cents": sum(values.values()), "pipeline_by_arm_cents": values,
            "opportunities": ledger, "opportunity_count": sum(counts.values()),
            "assigned_segment_counts": dict(Counter(account_segment(engine, account) for account in cohorts))}
