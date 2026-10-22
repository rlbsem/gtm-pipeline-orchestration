"""Operator admission, least-privilege visibility and failure cleanup; no native execution."""
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import connected_prepare
import native_connected
from gtm.salesforce import Approval, SalesforceClient, SalesforceError
from gtm.standard_crm import Scope
from gtm.store import digest
from test_standard_crm import ACCOUNT, CONTACT, ORG, READER, RUN, WRITER


class ReadOnlyContext:
    def __init__(self, fault=None):
        self.requests, self.fault = [], fault

    def handle(self, request):
        assert request.method == "GET"
        self.requests.append(request)
        path = request.url.path
        if path.endswith("userinfo"):
            body = {"organization_id": ORG}
        elif path.endswith("/query"):
            if "Organization" in request.url.params["q"]:
                body = {"records": [{"Id": ORG, "IsSandbox": False, "OrganizationType": "Developer Edition"}]}
            else:
                body = {"done": True, "totalSize": 1 if self.fault == "opportunity" else 0}
        elif path.endswith("/describe"):
            body = {"fields": [{"name": n} for n in ("Id", "LastName", "AccountId", "OwnerId", "Email")]}
        elif "/Account/" in path:
            body = {"Name": "SYNTHETIC GTM retained", "OwnerId": READER, "Website": "https://account-04.example"}
            if self.fault == "name":
                body["Name"] = "Real customer"
        else:
            assert "HasOptedOutOfEmail" not in request.url.params["fields"], "hidden FLS must not be bypassed"
            body = {"LastName": "SYNTHETIC GTM retained", "AccountId": ACCOUNT, "OwnerId": READER,
                    "Email": "review+" + RUN + "@account-04.example"}
            if self.fault == "association":
                body["AccountId"] = "wrong"
        return httpx.Response(200, json=body)


@pytest.mark.parametrize("fault", [None, "name", "association", "opportunity"])
def test_native_preview_uses_only_visible_fields_and_exact_scope(fault):
    provider = ReadOnlyContext(fault)
    client = SalesforceClient("https://test.my.salesforce.com", "software-only", read_only=True)
    client.client.close()
    client.client = httpx.Client(base_url="https://test.my.salesforce.com", transport=httpx.MockTransport(provider.handle))
    scope = Scope(RUN, ACCOUNT, CONTACT, READER, WRITER, READER)
    try:
        if fault:
            with pytest.raises(SalesforceError):
                connected_prepare.read_context(client, Approval(ORG, "developer_edition", "Developer Edition", True), scope)
        else:
            result = connected_prepare.read_context(client, Approval(ORG, "developer_edition", "Developer Edition", True), scope)
            assert result["account_hash"] == result["contact_account_hash"] == digest(ACCOUNT)
            assert result["account_active"] == "custom_field_requires_scoped_setup_permission"
            assert result["contact_opted_out"] == "field_requires_scoped_setup_permission"
            assert len(provider.requests) == 6
    finally:
        client.close()


def test_wrong_review_digest_stops_before_authentication_or_writes(tmp_path, monkeypatch):
    review = {"message": "software-only"}
    (tmp_path / "preview.json").write_text(json.dumps({"status": "awaiting_exact_review", "review": review,
                                                     "review_hash": digest(review)}))
    (tmp_path / "private-scope.json").write_text(json.dumps(asdict(Scope(RUN, ACCOUNT, CONTACT, READER, WRITER, READER))))
    monkeypatch.setattr(native_connected.Run, "__init__", lambda *_: pytest.fail("authentication must not start"))
    with pytest.raises(SalesforceError, match="exact_connected_review_required"):
        native_connected.ConnectedRun(SimpleNamespace(workspace=tmp_path, approved_review_sha256="0" * 64))


def test_no_retained_record_mutation_before_scope_baseline_snapshot():
    run = native_connected.ConnectedRun.__new__(native_connected.ConnectedRun)
    run.state = {"ids": {"account": ACCOUNT}}
    run.write = lambda *_: pytest.fail("no lifecycle change authorized yet")
    assert run.quiesce() == {"activation_not_started": True}


def test_connected_failure_always_runs_cleanup_and_records_failure(tmp_path, monkeypatch):
    cleanup_calls = []
    class Run:
        state, clients, checks, raw = {"baseline": {}}, {}, {}, []
        preview = {"software": "test"}
        def execute_connected(self):
            raise SalesforceError("software_execution_failure")
        def cleanup(self):
            cleanup_calls.append(True)
            return {"original_assignments_restored": True}
        def public(self):
            return []
        def save(self):
            pass
    monkeypatch.setattr(native_connected, "ConnectedRun", lambda _: Run())
    monkeypatch.setattr(native_connected, "execution_sources", lambda: {})
    with pytest.raises(SalesforceError, match="connected_acceptance_incomplete"):
        native_connected.execute(SimpleNamespace(workspace=tmp_path, approved_review_sha256="software"))
    result = json.loads((tmp_path / "acceptance.json").read_text())
    assert result["status"] == "failed" and result["error"] == "software_execution_failure"
    assert cleanup_calls == [True]


def test_connected_cleanup_failure_cannot_be_reported_as_success(tmp_path, monkeypatch):
    class Run:
        state, clients, checks, raw = {"baseline": {}}, {}, {}, []
        preview = {"software": "test"}
        def execute_connected(self):
            pass
        def cleanup(self):
            raise SalesforceError("software_cleanup_failure")
        def public(self):
            return []
        def save(self):
            pass
    run = Run()
    monkeypatch.setattr(native_connected, "ConnectedRun", lambda _: run)
    monkeypatch.setattr(native_connected, "execution_sources", lambda: {})
    with pytest.raises(SalesforceError, match="connected_acceptance_incomplete"):
        native_connected.execute(SimpleNamespace(workspace=tmp_path, approved_review_sha256="software"))
    result = json.loads((tmp_path / "acceptance.json").read_text())
    assert result["status"] == "cleanup_failed" and run.state["phase"] == "cleanup_required"
