"""Local operator safety regressions; no Salesforce credentials or API execution."""
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from gtm.salesforce import SalesforceError
from gtm.standard_crm import REQUIRED_FIELDS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("native_standard", ROOT / "scripts/native_standard.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_quiescence_failure_still_retires_temporary_access():
    run = module.Run.__new__(module.Run)
    retired = []
    def broken():
        raise SalesforceError("software_lifecycle_patch_failed")
    run.quiesce = broken
    run.retire = lambda: retired.append(True)
    with pytest.raises(SalesforceError, match="software_lifecycle_patch_failed"):
        run.cleanup()
    assert retired == [True] and run.cleaning


def test_one_retirement_failure_cannot_skip_remaining_assignments():
    run = module.Run.__new__(module.Run)
    run.state = {"assignments": [{"id": str(i), "object": "PermissionSetAssignment"} for i in range(4)]}
    requests = []
    class Client:
        def request(self, method, path):
            requests.append((method, path))
            return httpx.Response(403 if len(requests) == 1 else 204)
    run.clients = {"administrator": Client()}
    with pytest.raises(SalesforceError, match="temporary_grant_retirement_incomplete"):
        run.retire()
    assert len(requests) == 4 and all(method == "DELETE" for method, _ in requests)


def test_actual_recorded_native_fields_support_stricter_current_preflight():
    details = json.loads((ROOT / "docs/evidence/salesforce-standard/native-details.json").read_text())
    for role in ("integration", "reviewer"):
        for obj, required in REQUIRED_FIELDS.items():
            assert required <= details["effective_permissions"][role][obj]["fields"].keys()
    task = details["effective_permissions"]["integration"]["Task"]["fields"]
    assert all(task[n]["createable"] for n in ("WhatId", "WhoId", "Description", "GTM_Action_Key__c"))


def test_failed_cleanup_is_recorded_and_cli_cannot_report_success(tmp_path, monkeypatch):
    class FakeRun:
        def __init__(self, args):
            self.state, self.checks, self.raw, self.clients = {"baseline": {}}, {}, [], {}
        def pin(self):
            pass
        def setup(self):
            pass
        def execute(self):
            pass
        def cleanup(self):
            raise SalesforceError("software_cleanup_failure")
        def public(self):
            return []
        def save(self):
            pass
    run = FakeRun(None)
    monkeypatch.setattr(module, "Run", lambda args: run)
    monkeypatch.setattr(module, "source_hashes", lambda: {})
    monkeypatch.setattr(sys, "argv", ["native_standard.py", "--config", "unused", "--workspace", str(tmp_path),
                                     "--run-id", "gtm-standard-software-cleanup", "--cli", "unused", "--approved-isolated-writes"])
    with pytest.raises(SalesforceError, match="native_acceptance_incomplete"):
        module.main()
    report = json.loads((tmp_path / "verification.json").read_text())
    assert report["status"] == "cleanup_failed"
    assert report["cleanup"]["original_assignments_restored"] is False
    assert report["cleanup"]["requires_investigation"] and run.state["phase"] == "cleanup_required"


def test_setup_cannot_adopt_and_later_mutate_unjournaled_existing_records():
    run = module.Run.__new__(module.Run)
    run.config = {"integration_user_id": "writer", "reviewer_user_id": "reader"}
    run.admin_id = "administrator"
    run.state = {"baseline": {}, "baseline_psl": ["entitlement"], "run_id": "gtm-standard-software-existing",
                 "ids": {}, "assignments": []}
    run.save = lambda: None
    run.assign = lambda *args: None
    run.query = lambda q: [{"Id": "entitlement" if "PermissionSetLicense WHERE" in q else "permission"}]
    class ExistingProvider:
        def request(self, method, path):
            assert method == "GET", "setup must not mutate an untracked existing row"
            return httpx.Response(200, json={"queryable": True} if path.endswith("/describe") else {"Id": "existing-record"})
    run.clients = {name: ExistingProvider() for name in ("administrator", "integration", "reviewer")}
    run.write = lambda *args: pytest.fail("unexpected setup write")
    with pytest.raises(SalesforceError, match="unmanifested_synthetic_record_requires_reconciliation"):
        run.setup()
    assert run.state["ids"] == {}
