"""Vendor-shaped interfaces; mapper tests are NOT native Salesforce/engagement execution."""
from typing import Protocol

from .contracts import Action, DomainError
from .store import digest


class EngagementAdapter(Protocol):
    def receipts(self) -> list[dict]: ...
    def receipt(self, key: str) -> dict | None: ...
    def enroll(self, payload: dict, at: str): ...


def salesforce_task(payload, account_mapping, owner_mapping):
    action = Action.model_validate(payload).model_dump()
    account = account_mapping.get((action["brand"], action["account_id"]))
    owner = owner_mapping.get((action["brand"], action["owner"]))
    if not account or not owner:
        raise DomainError("explicit_vendor_mapping_required")
    return {"WhatId": account, "OwnerId": owner, "Subject": "Synthetic SDR review",
            "Description": action["message"], "Status": "Not Started", "Priority": "Normal",
            "Orchestration_Key__c": action["action_key"], "Payload_SHA256__c": digest(action)}
