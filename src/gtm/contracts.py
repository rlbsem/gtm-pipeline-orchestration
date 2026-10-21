"""Closed source and action contracts. Dates use an explicit UTC experiment clock."""
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DomainError(ValueError):
    pass


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("explicit_utc_required")
    return parsed.astimezone(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["source/v1"] = "source/v1"
    source: Literal["crm", "enrichment", "web", "engagement"]
    source_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    brand: Literal["atlas", "harbor"]
    kind: Literal["account", "contact", "intent", "inbound", "consent", "owner", "outcome"]
    domain: str = Field(pattern=r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:example|test|invalid)$")
    account_id: str | None = None
    observed_at: str
    data: dict

    @field_validator("observed_at")
    @classmethod
    def valid_time(cls, value):
        return stamp(moment(value))


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["action/v1"] = "action/v1"
    action_key: str = Field(pattern=r"^act_[a-f0-9]{24}$")
    account_id: str
    brand: Literal["atlas", "harbor"]
    contact: str
    owner: str
    sequence: Literal["research-review-v1"] = "research-review-v1"
    message: str
    synthetic: Literal[True] = True

    @field_validator("contact")
    @classmethod
    def synthetic_address(cls, value):
        if "@" not in value or not value.rsplit("@", 1)[1].endswith((".example", ".test", ".invalid")):
            raise ValueError("synthetic_contact_required")
        return value


def loopback_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost"):
        raise DomainError("loopback_http_only")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise DomainError("bare_loopback_origin_required")
    return value.rstrip("/")
