"""Software failure contracts, separate from the recorded native REST/Apex execution."""
import json
from dataclasses import replace

import httpx
import pytest

from gtm.salesforce import Approval, SalesforceClient, SalesforceError
from gtm.standard_crm import RECEIPT, Scope, StandardCRM, TaskDispatcher
from gtm.store import canonical, digest
from gtm.upgrade_scenarios import SCENARIO, cases, fixture

ORG = "00D" + "0" * 15
WRITER, READER = "005" + "1" * 15, "005" + "2" * 15
ACCOUNT, CONTACT, TASK, ROW = "001" + "1" * 15, "003" + "1" * 15, "00T" + "1" * 15, "a09" + "1" * 15
RUN = "gtm-standard-software-test"


class Provider:
    def __init__(self):
        self.rows, self.posts, self.drop, self.outage = {}, 0, False, False
        self.owner, self.consent, self.open, self.conflict = READER, True, False, False
        self.unique, self.readable, self.org = True, True, ORG

    def client(self, role):
        c = SalesforceClient("https://test.my.salesforce.com", "software-test")
        c.client.close()
        c.client = httpx.Client(base_url="https://test.my.salesforce.com",
                              transport=httpx.MockTransport(lambda r: self.handle(role, r)))
        return c

    def handle(self, role, request):
        path = request.url.path
        if path.endswith("userinfo"):
            body = {"organization_id": self.org, "user_id": WRITER if role == "writer" else READER}
        elif path.endswith("/describe"):
            obj = path.split("/")[-2]
            if obj == RECEIPT and not self.readable:
                return httpx.Response(404, json=[{"errorCode": "NOT_FOUND"}])
            body = {"queryable": True, "createable": obj == "Task" and role == "writer",
                    "updateable": False, "deletable": False,
                    "fields": [{"name": "Action_Key__c", "unique": self.unique, "externalId": True}]}
        elif path.endswith("/query"):
            q = request.url.params["q"]
            rows = ([{"Id": self.org, "IsSandbox": False, "OrganizationType": "Developer Edition"}] if "Organization" in q
                    else ([{"Id": TASK}] if "FROM Task" in q and self.rows else
                          [{"Id": "opp"}] if "Opportunity" in q and self.open else []))
            body = {"records": rows, "totalSize": len(rows), "done": True}
        elif "/Account/GTM_Test_Key__c/" in path:
            body = {"Id": ACCOUNT, "OwnerId": self.owner, "Website": "https://account-04.example",
                    "GTM_Test_Key__c": RUN + "/account-a", "GTM_Test_Active__c": True}
        elif "/Contact/GTM_Test_Key__c/" in path:
            body = {"Id": CONTACT, "AccountId": ACCOUNT, "OwnerId": READER, "Email": "review+" + RUN + "@account-04.example",
                    "HasOptedOutOfEmail": not self.consent, "GTM_Test_Key__c": RUN + "/contact-a"}
        elif "/User/" in path:
            body = {"Id": READER, "IsActive": True}
        elif request.method == "POST":
            self.posts += 1
            if self.outage:
                raise httpx.ReadTimeout("software outage")
            payload = json.loads(request.content)
            self.rows[payload["GTM_Action_Key__c"]] = payload
            if self.drop:
                self.drop = False
                raise httpx.ReadTimeout("software lost acknowledgement")
            return httpx.Response(201, json={"id": TASK})
        elif "/Action_Key__c/" in path:
            if not self.readable:
                return httpx.Response(404, json=[{"errorCode": "NOT_FOUND"}])
            key = path.rsplit("/", 1)[-1]
            if key not in self.rows:
                return httpx.Response(404, json=[{"errorCode": "NOT_FOUND"}])
            payload = self.rows[key]
            body = {"Id": ROW, "Task_Id__c": TASK, "Action_Key__c": key, "Payload__c": payload["Description"],
                    "Payload_Hash__c": digest(json.loads(payload["Description"]))}
            if self.conflict:
                body["Payload__c"] = "tampered"
        elif "/Task/" in path:
            body = next(iter(self.rows.values())) | {"Id": TASK, "CreatedById": WRITER}
        else:
            return httpx.Response(404, json=[])
        return httpx.Response(200, json=body)


@pytest.fixture
def standard(engine):
    provider = Provider()
    crm = StandardCRM(provider.client("writer"), provider.client("reader"), provider.client("admin"),
                      Approval(ORG, "developer_edition", "Developer Edition", True),
                      Scope(RUN, ACCOUNT, CONTACT, READER, WRITER, READER))
    crm.preflight()
    account, _ = fixture(engine, cases()["cases"][0])
    action = engine.approve(account["id"], engine.prepare(account["id"], SCENARIO), "demo-reviewer", SCENARIO)
    dispatcher = TaskDispatcher(engine, crm)
    key = dispatcher.prepare(action["action_key"], SCENARIO)
    yield provider, crm, dispatcher, key
    for client in (crm.writer, crm.reader, crm.administrator):
        client.close()


def test_native_task_exact_readback_and_duplicate_recovery(standard):
    p, crm, d, key = standard
    assert d.dispatch(key, SCENARIO)["status"] == "delivered"
    assert TaskDispatcher(d.engine, crm).dispatch(key, SCENARIO)["status"] == "reconciled"
    assert p.posts == 1


def test_lost_ack_restart_reconciles_before_revoked_new_action(standard):
    p, crm, d, key = standard
    p.drop = True
    assert d.dispatch(key, SCENARIO)["status"] == "uncertain"
    p.consent = False
    assert TaskDispatcher(d.engine, crm).dispatch(key, SCENARIO)["status"] == "reconciled"
    assert p.posts == 1


@pytest.mark.parametrize("fault,reason", [("owner", "standard_identity_or_owner_mismatch"),
                         ("consent", "standard_consent_or_scope_revoked"), ("open", "standard_active_opportunity")])
def test_current_crm_authority_blocks_new_task(standard, fault, reason):
    p, _, d, key = standard
    setattr(p, fault, "005" + "3" * 15 if fault == "owner" else fault == "open")
    result = d.dispatch(key, SCENARIO)
    assert result["status"] == "blocked" and result["error"] == reason
    assert p.posts == 0


def test_tampered_independent_receipt_never_reposts(standard):
    p, _, d, key = standard
    d.dispatch(key, SCENARIO)
    p.conflict = True
    assert d.dispatch(key, SCENARIO)["error"] == "task_receipt_content_mismatch"
    assert p.posts == 1


def test_missing_receipt_object_is_not_absent_effect(standard):
    p, _, d, key = standard
    p.readable = False
    assert d.dispatch(key, SCENARIO)["status"] == "blocked"
    assert p.posts == 0


def test_disappeared_historical_receipt_cannot_create_replacement(standard):
    p, _, d, key = standard
    d.dispatch(key, SCENARIO)
    p.rows.clear()
    assert d.dispatch(key, SCENARIO)["error"] == "previously_verified_task_receipt_missing"
    assert p.posts == 1


def test_retry_exhaustion_and_backoff(standard):
    p, _, d, key = standard
    p.outage = True
    assert d.dispatch(key, SCENARIO)["status"] == "uncertain"
    assert d.dispatch(key, SCENARIO)["status"] == "waiting"
    for at in ("2026-01-21T12:00:05Z", "2026-01-21T12:00:10Z"):
        assert d.dispatch(key, at)["status"] == "uncertain"
    assert d.dispatch(key, "2026-01-21T12:00:20Z")["status"] == "exhausted"
    assert p.posts == 3


def test_pinned_scope_cannot_change_after_preflight(standard):
    _, crm, _, _ = standard
    crm.scope = replace(crm.scope, account="001" + "2" * 15)
    with pytest.raises(SalesforceError, match="standard_preflight_required"):
        crm.resolve()


@pytest.mark.parametrize("fault", ["unique", "org"])
def test_preflight_rejects_missing_unique_key_or_wrong_org(standard, fault):
    p, crm, _, _ = standard
    setattr(p, fault, False if fault == "unique" else "00D" + "9" * 15)
    with pytest.raises(SalesforceError):
        crm.preflight()
    assert not crm.ready


def test_tampered_durable_intent_blocks(standard):
    _, _, d, key = standard
    with d.engine.connection() as db:
        db.execute("UPDATE crm_tasks SET payload=? WHERE native_key=?", (canonical({"changed": True}), key))
    with pytest.raises(SalesforceError, match="standard_durable_intent_required"):
        d.dispatch(key, SCENARIO)


@pytest.mark.parametrize("run", ["production", "gtm-standard-../../bad", "gtm-standard-short", "gtm-standard-ABC12345"])
def test_scope_rejects_unbounded_namespace(run):
    with pytest.raises(SalesforceError):
        Scope(run, ACCOUNT, CONTACT, READER, WRITER, READER)


def test_same_identity_cannot_verify_own_receipt():
    with pytest.raises(SalesforceError, match="independent_owner_reader_required"):
        Scope(RUN, ACCOUNT, CONTACT, WRITER, WRITER, WRITER)
