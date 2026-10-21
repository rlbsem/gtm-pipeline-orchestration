"""Intent-to-treat account comparison; synthetic arithmetic is never commercial uplift."""
from pathlib import Path

from .contracts import moment, stamp
from .currency import metadata


def measure(engine, as_of):
    as_of = stamp(moment(as_of))
    with engine.connection() as db:
        profile = db.execute("SELECT value FROM runtime WHERE key='scenario_profile'").fetchone()
        enterprise = profile is not None and profile[0] == "enterprise"
        currency = metadata(db)["currency"] if enterprise else None
        if enterprise and db.execute("SELECT count(*) FROM feedback f LEFT JOIN sources s ON s.source_key=f.source_key "
                                     "WHERE json_extract(s.payload,'$.data.currency') IS NOT ?", (currency,)).fetchone()[0]:
            raise ValueError("measurement_source_currency_mismatch")
        rows = [dict(x) for x in db.execute(Path(__file__).with_name("pipeline.sql").read_text(),
                {"as_of": as_of, "experiment": engine.policy["experiment"], "currency": currency})]
    if not enterprise:
        for row in rows:
            row.pop("currency")  # Preserve the original fixture's complete exported oracle.
    arms = {}
    for arm in ("treatment", "holdout"):
        cohort = [r for r in rows if r["arm"] == arm]
        mature = [r for r in cohort if r["mature"]]
        n = len(mature)
        arms[arm] = {"assigned": len(cohort), "mature_accounts": n,
                     "qualified_meetings": sum(r["meetings"] for r in mature),
                     "accounts_with_meetings": sum(r["meetings"] > 0 for r in mature),
                     "accepted_opportunities": sum(r["opportunities"] for r in mature),
                     "pipeline_cents": sum(r["pipeline_cents"] for r in mature),
                     "exposed_accounts": sum(r["exposures"] > 0 for r in mature)}
        arms[arm]["meeting_rate"] = sum(r["meetings"] > 0 for r in mature) / n if n else None
        arms[arm]["opportunities_per_account"] = arms[arm]["accepted_opportunities"] / n if n else None
        arms[arm]["pipeline_per_account_cents"] = arms[arm]["pipeline_cents"] / n if n else None
    leakage = [r["account_id"] for r in rows if r["arm"] == "holdout" and r["exposures"]]
    t, h = arms["treatment"], arms["holdout"]
    delta = (t["meeting_rate"] - h["meeting_rate"]) if t["mature_accounts"] and h["mature_accounts"] else None
    return {**({"currency": currency} if enterprise else {}),
            "version": "pipeline-measurement/v1", "experiment": engine.policy["experiment"], "as_of": as_of, "arms": arms,
            "meeting_rate_difference": delta, "leakage_accounts": leakage,
            "comparison_valid": not leakage and delta is not None, "accounts": rows,
            "interpretation": "Synthetic intent-to-treat arithmetic; not observed commercial uplift or causal proof. "
                              "No significance claim. Full assigned-account denominator; mature windows only. "
                              "Unobserved cross-channel exposure and source completeness are not established."}
