"""Currency identity is pinned per enterprise workspace; no conversion or implicit migration."""
import json
import re

from .contracts import DomainError


def metadata(db):
    profile = db.execute("SELECT value FROM runtime WHERE key='scenario_profile'").fetchone()
    if not profile or profile[0] == "fixture":
        return {"currency": "CAD", "locale": "en-CA"}  # Historical, implicit-CAD fixture contract.
    row = db.execute("SELECT value FROM runtime WHERE key='enterprise_specification'").fetchone()
    if not row:
        raise DomainError("legacy_enterprise_currency_use_fresh_workspace")
    config = json.loads(row[0])
    if (not re.fullmatch(r"[A-Z]{3}", config.get("currency", "")) or
            not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", config.get("locale", ""))):
        raise DomainError("invalid_scenario_currency_metadata")
    return {key: config[key] for key in ("currency", "locale")}


def validate(db, data):
    profile = db.execute("SELECT value FROM runtime WHERE key='scenario_profile'").fetchone()
    expected = metadata(db)["currency"]
    if profile and profile[0] == "enterprise":
        if data.get("currency") != expected:
            raise DomainError("enterprise_outcome_currency_mismatch")
    elif data.get("currency", expected) != expected:
        raise DomainError("fixture_outcome_currency_mismatch")
