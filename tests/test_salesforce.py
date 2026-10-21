"""Software contract tests. These responses are not native Salesforce evidence."""
import json
from dataclasses import replace

import httpx
import pytest

from gtm.salesforce import (IMMUTABLE_FIELDS, OBJECT, Approval, Mapping, NativeDispatcher,
                            ReviewInbox, SalesforceClient, SalesforceError, standard_resolution)
from gtm.store import digest
from gtm.upgrade_scenarios import SCENARIO, cases, fixture, mutate

ORG = "00D" + "0" * 15
WRITER, READER = "005" + "1" * 15, "005" + "2" * 15
REGISTRY, ROW = "a01" + "1" * 15, "a02" + "2" * 15


class Provider:
    def __init__(self):
        self.rows, self.writes = {}, []
        self.drop, self.outage, self.conflict = False, False, False
        self.owner = READER
        self.environment = {"Id": ORG, "IsSandbox": False, "OrganizationType": "Developer Edition"}

    def client(self, role):
        client = SalesforceClient("https://test.my.salesforce.com", "software-test")
        client.client.close()
        client.client = httpx.Client(base_url="https://test.my.salesforce.com",
                                     transport=httpx.MockTransport(lambda r: self.handle(role, r)))
        return client

    def handle(self, role, request):
        path, method = request.url.path, request.method
        if method != "GET":
            self.writes.append((role, method, path))
        data = {}
        code = 200
        if path.endswith("userinfo"):
            data = {"organization_id": ORG, "user_id": WRITER if role == "writer" else READER}
        elif path.endswith("/query"):
            data = {"done": True, "totalSize": 1, "records": [self.environment]}
        elif path.endswith("/describe"):
            fields = [{"name": n, "createable": True, "updateable": False,
                       "unique": n == "Action_Key__c", "externalId": n == "Action_Key__c", "length": 32000}
                      for n in IMMUTABLE_FIELDS]
            fields.append({"name": "Review_Status__c", "updateable": True})
            data = {"name": OBJECT, "createable": role == "writer", "updateable": role == "reader",
                    "queryable": True, "deletable": False, "fields": fields}
        elif "/Synthetic_Account__c/" in path:
            data = {"Id": REGISTRY, "Account_Key__c": "cedar:account-0012", "Brand__c": "cedar",
                    "Approved_Owner__c": self.owner, "Active__c": True, "Synthetic__c": True,
                    "LastModifiedDate": "2026-01-01T00:00:00Z"}
        elif "/User/" in path:
            data = {"Id": READER, "IsActive": True}
        elif method == "POST":
            if self.outage:
                raise httpx.ReadTimeout("software outage")
            body = json.loads(request.content)
            if role != "writer":
                code, data = 400, [{"errorCode": "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"}]
            elif body["Action_Key__c"] in self.rows:
                code, data = 400, [{"errorCode": "DUPLICATE_VALUE"}]
            else:
                self.rows[body["Action_Key__c"]] = {**body, "Id": ROW}
                code, data = 201, {"id": ROW, "success": True}
                if self.drop:
                    self.drop = False
                    raise httpx.ReadTimeout("software lost acknowledgement")
        elif "/Action_Key__c/" in path:
            key = path.rsplit("/", 1)[-1]
            data = dict(self.rows.get(key, {}))
            if not data:
                code = 404
            elif self.conflict:
                data["Draft__c"] = "tampered"
        else:
            code = 404
        return httpx.Response(code, json=data)


@pytest.fixture
def native(engine):
    account, _ = fixture(engine, cases()["cases"][0])
    provider = Provider()
    mapping = Mapping(account["brand"], account["id"], account["owner"], "cedar", "account-0012", "cedar-east", REGISTRY, READER)
    inbox = ReviewInbox(provider.client("writer"), provider.client("reader"), provider.client("admin"),
                        Approval(ORG, "developer_edition", "Developer Edition", True), mapping, WRITER, READER)
    inbox.preflight()
    action = engine.approve(account["id"], engine.prepare(account["id"], SCENARIO), "demo-reviewer", SCENARIO)
    dispatcher = NativeDispatcher(engine, inbox)
    intent = dispatcher.prepare(action["action_key"], "gtm-software-contract", SCENARIO)
    yield engine, provider, inbox, dispatcher, intent, account
    for client in (inbox.writer, inbox.reader, inbox.administrator):
        client.close()


@pytest.mark.parametrize("environment,sandbox,edition,passes", [
    ("developer_edition", False, "Developer Edition", True),
    ("sandbox", True, "Enterprise Edition", True),
    ("sandbox", False, "Enterprise Edition", False),
    ("developer_edition", False, "Enterprise Edition", False),
    ("developer_edition", True, "Developer Edition", False)])
def test_positive_and_negative_environment_pins(environment, sandbox, edition, passes):
    approval = Approval(ORG, environment, "Developer Edition" if environment == "developer_edition" else edition, True)
    org = {"Id": ORG, "IsSandbox": sandbox, "OrganizationType": edition}
    if passes:
        approval.verify(org)
    else:
        with pytest.raises(SalesforceError):
            approval.verify(org)


@pytest.mark.parametrize("kwargs", [{"approved": False}, {"environment": "production"}, {"org_id": "bad"}])
def test_explicit_approval_required(kwargs):
    with pytest.raises(SalesforceError):
        Approval(**({"org_id": ORG, "environment": "developer_edition", "organization_type": "Developer Edition",
                     "approved": True} | kwargs))


@pytest.mark.parametrize("origin", ["http://test.my.salesforce.com", "https://evil.example", "https://test.my.salesforce.com/x",
                                     "https://secret@test.my.salesforce.com", "https://test.my.salesforce.com?x=1"])
def test_transport_origin_boundaries(origin):
    with pytest.raises(SalesforceError):
        SalesforceClient(origin, "test")


def test_actual_wire_software_lost_ack_restart_and_receipt_before_revocation(native):
    engine, provider, inbox, dispatcher, intent, account = native
    provider.drop = True
    assert dispatcher.dispatch(intent["native_key"], SCENARIO)["status"] == "uncertain"
    mutate(engine, account, "consent", {"allowed": False}, source="web", at="2026-01-21T12:00:01Z")
    assert NativeDispatcher(engine, inbox).dispatch(intent["native_key"], "2026-01-21T12:00:03Z")["status"] == "reconciled"
    assert len(provider.writes) == len(provider.rows) == 1
    assert engine.audit_valid()


@pytest.mark.parametrize("mutation", ["owner", "consent", "native_owner"])
def test_new_write_fails_closed_when_authority_changes(native, mutation):
    engine, provider, _, dispatcher, intent, account = native
    if mutation == "native_owner":
        provider.owner = WRITER
    else:
        mutate(engine, account, mutation, {"owner": "atlas-emea"} if mutation == "owner" else {"allowed": False},
               at="2026-01-21T12:00:01Z")
    assert dispatcher.dispatch(intent["native_key"], "2026-01-21T12:00:02Z")["status"] == "blocked"
    assert provider.writes == []


def test_budget_backoff_survives_restart(native):
    engine, provider, inbox, dispatcher, intent, _ = native
    provider.outage = True
    key = intent["native_key"]
    assert dispatcher.dispatch(key, SCENARIO)["status"] == "uncertain"
    assert dispatcher.dispatch(key, "2026-01-21T12:00:01Z")["status"] == "waiting"
    for second in (3, 8):
        assert NativeDispatcher(engine, inbox).dispatch(key, f"2026-01-21T12:00:{second:02d}Z")["status"] == "uncertain"
    assert dispatcher.dispatch(key, "2026-01-21T12:00:20Z")["status"] == "exhausted"
    assert len(provider.writes) == 3


def test_duplicate_and_full_content_conflict(native):
    _, provider, inbox, dispatcher, intent, _ = native
    key, envelope = intent["native_key"], json.loads(intent["envelope"])
    assert dispatcher.dispatch(key, SCENARIO)["status"] == "delivered"
    inbox.create(key, envelope)
    assert len(provider.rows) == 1
    provider.conflict = True
    assert dispatcher.dispatch(key, "2026-01-21T12:00:01Z")["status"] == "blocked"


def test_mapping_and_preflight_changes_require_new_approval(native):
    _, _, inbox, dispatcher, intent, _ = native
    inbox.mapping = replace(inbox.mapping, provider_owner="cedar-west")
    with pytest.raises(SalesforceError, match="durable_intent"):
        dispatcher.dispatch(intent["native_key"], SCENARIO)
    with pytest.raises(SalesforceError, match="preflight"):
        inbox.receipt(intent["native_key"], json.loads(intent["envelope"]))


def test_audit_tampering_denies_native_write(native):
    engine, provider, _, dispatcher, intent, _ = native
    with engine.connection() as db:
        db.execute("DROP TRIGGER audit_no_update")
        db.execute("UPDATE audit SET detail='{}' WHERE seq=1")
    with pytest.raises(SalesforceError, match="audit_integrity"):
        dispatcher.dispatch(intent["native_key"], SCENARIO)
    assert not provider.writes


def test_standard_resolution_never_bypasses_preflight(native):
    _, _, inbox, _, _, _ = native
    inbox.ready = False
    with pytest.raises(SalesforceError, match="preflight"):
        standard_resolution(inbox, "001" + "1" * 15, "003" + "1" * 15, READER, "GTM-SYNTHETIC-software")


def test_immutable_native_journal_and_exact_key_binding(native):
    engine, _, _, dispatcher, intent, _ = native
    import sqlite3
    with engine.connection() as db, pytest.raises(sqlite3.IntegrityError, match="immutable_crm_intent"):
        db.execute("UPDATE crm_reviews SET envelope_hash=?", (digest("different"),))
    assert dispatcher.prepare(intent["action_key"], "gtm-software-contract", SCENARIO)["native_key"] == intent["native_key"]


@pytest.mark.parametrize("defect", ["wrong_org", "ordinary_production", "missing_unique", "reviewer_can_create", "writer_can_update"])
def test_preflight_contract_defects_fail_before_any_write(native, defect):
    _, provider, inbox, _, _, _ = native
    if defect in {"wrong_org", "ordinary_production"}:
        provider.environment["Id" if defect == "wrong_org" else "OrganizationType"] = (
            "00D" + "9" * 15 if defect == "wrong_org" else "Enterprise Edition")
    else:
        client = inbox.reader if defect == "reviewer_can_create" else inbox.writer
        original = client.request
        def faulty(method, path, **kwargs):
            response = original(method, path, **kwargs)
            if path.endswith("/describe"):
                schema = response.json()
                if defect == "missing_unique":
                    next(f for f in schema["fields"] if f["name"] == "Action_Key__c")["unique"] = False
                else:
                    schema["createable" if defect == "reviewer_can_create" else "updateable"] = True
                return httpx.Response(200, json=schema)
            return response
        client.request = faulty
    with pytest.raises(SalesforceError):
        inbox.preflight()
    assert not inbox.ready and not provider.writes


def test_admin_transport_enforces_read_only():
    client = SalesforceClient("https://test.my.salesforce.com", "software-test", read_only=True)
    try:
        with pytest.raises(SalesforceError, match="read_only"):
            client.request("POST", "/services/data/v65.0/sobjects/Seller_Action__c/", json={})
    finally:
        client.close()


def test_unexpected_trigger_error_is_not_duplicate_or_success(native):
    _, _, inbox, _, intent, _ = native
    original = inbox.writer.request
    def denied(method, path, **kwargs):
        if method == "POST":
            return httpx.Response(400, json=[{"errorCode": "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY"}])
        return original(method, path, **kwargs)
    inbox.writer.request = denied
    with pytest.raises(SalesforceError, match="native_http_400"):
        inbox.create(intent["native_key"], json.loads(intent["envelope"]))


@pytest.mark.parametrize("wrong_owner", [False, True])
def test_exact_standard_resolution_is_read_only_and_synthetic(native, wrong_owner):
    _, _, inbox, _, _, _ = native
    account, contact, marker = "001" + "3" * 15, "003" + "4" * 15, "GTM-SYNTHETIC-contract"
    calls = []
    def read(method, path, **kwargs):
        calls.append(method)
        row = ({"Id": account, "OwnerId": WRITER if wrong_owner else READER, "Description": marker,
                "Website": "https://fixture.example"} if "/Account/" in path else
               {"Id": contact, "AccountId": account, "OwnerId": READER, "Description": marker,
                "Email": "contact@fixture.example"})
        return httpx.Response(200, json=row)
    inbox.writer.request = read
    if wrong_owner:
        with pytest.raises(SalesforceError, match="owner_mismatch"):
            standard_resolution(inbox, account, contact, READER, marker)
    else:
        assert standard_resolution(inbox, account, contact, READER, marker)["account"]["Id"] == account
    assert calls == ["GET", "GET"]
