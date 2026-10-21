"""Synthetic Account/Contact resolution and receipt-first native SDR Tasks. No sending API."""
import json
import re
from dataclasses import asdict, dataclass
from urllib.parse import quote

from .salesforce import API, Approval, SalesforceError, get_json, identifier, success
from .store import canonical, digest
from .worker import bound_approval

RECEIPT = "GTM_Task_Receipt__c"
SUBJECT = "SYNTHETIC GTM SDR handoff - no prospect communication"
NOTICE = "Synthetic internal handoff only. No outbound communication."
MESSAGE = "Review the synthetic account evidence before any seller action."


@dataclass(frozen=True)
class Scope:
    run_id: str
    account: str
    contact: str
    owner: str
    writer: str
    reader: str

    def __post_init__(self):
        if not re.fullmatch(r"gtm-standard-[a-z0-9-]{8,60}", self.run_id):
            raise SalesforceError("invalid_synthetic_run")
        for name, prefix in (("account", "001"), ("contact", "003"), ("owner", "005"),
                             ("writer", "005"), ("reader", "005")):
            identifier(getattr(self, name), prefix)
        if self.writer == self.reader or self.owner != self.reader:
            raise SalesforceError("independent_owner_reader_required")


class StandardCRM:
    def __init__(self, writer, reader, administrator, approval, scope):
        if not isinstance(approval, Approval) or not isinstance(scope, Scope):
            raise SalesforceError("typed_test_scope_required")
        self.writer, self.reader, self.administrator = writer, reader, administrator
        self.approval, self.scope, self.ready = approval, scope, False

    @property
    def pin(self):
        return digest({"approval": asdict(self.approval), "scope": asdict(self.scope)})

    def preflight(self):
        self.ready = False
        org = get_json(self.administrator, API + "/query", params={
            "q": "SELECT Id,IsSandbox,OrganizationType FROM Organization"})
        self.approval.verify(org["records"][0])
        for client, user in ((self.writer, self.scope.writer), (self.reader, self.scope.reader)):
            who = get_json(client, "/services/oauth2/userinfo")
            if who.get("organization_id") != self.approval.org_id or who.get("user_id") != user:
                raise SalesforceError("standard_identity_mismatch")
            for obj in ("Account", "Contact", "Opportunity", "Task", RECEIPT):
                desc = get_json(client, API + "/sobjects/" + obj + "/describe")
                if not desc.get("queryable"):
                    raise SalesforceError("standard_read_access_required")
                if obj in {"Account", "Contact", "Opportunity", RECEIPT} and any(
                        desc.get(f) for f in ("createable", "updateable", "deletable")):
                    raise SalesforceError("unexpected_source_or_receipt_write_access")
                if obj == "Task" and bool(desc.get("createable")) is not (client is self.writer):
                    raise SalesforceError("task_create_boundary_mismatch")
        receipt = get_json(self.reader, API + "/sobjects/" + RECEIPT + "/describe")
        key = next(f for f in receipt["fields"] if f["name"] == "Action_Key__c")
        if not key.get("unique") or not key.get("externalId"):
            raise SalesforceError("atomic_unique_receipt_required")
        self.ready, self._pin = True, self.pin

    def guard(self):
        if not self.ready or self.pin != self._pin:
            raise SalesforceError("standard_preflight_required")

    def resolve(self):
        self.guard()
        s = self.scope
        records = []
        for obj, tail, fields in (("Account", "account-a", "Id,OwnerId,Website,GTM_Test_Key__c,GTM_Test_Active__c"),
                                  ("Contact", "contact-a", "Id,AccountId,OwnerId,Email,HasOptedOutOfEmail,GTM_Test_Key__c")):
            records.append(get_json(self.writer, API + "/sobjects/" + obj + "/GTM_Test_Key__c/" +
                                    quote(s.run_id + "/" + tail, safe=""), params={"fields": fields}))
        a, c = records
        if (a.get("Id") != s.account or c.get("Id") != s.contact or c.get("AccountId") != s.account
                or a.get("OwnerId") != s.owner or c.get("OwnerId") != s.owner
                or a.get("Website") != "https://account-04.example" or c.get("Email") != "review+" + s.run_id + "@account-04.example"
                or a.get("GTM_Test_Key__c") != s.run_id + "/account-a"
                or c.get("GTM_Test_Key__c") != s.run_id + "/contact-a"):
            raise SalesforceError("standard_identity_or_owner_mismatch")
        if not a.get("GTM_Test_Active__c") or c.get("HasOptedOutOfEmail") is not False:
            raise SalesforceError("standard_consent_or_scope_revoked")
        owner = get_json(self.writer, API + "/sobjects/User/" + s.owner, params={"fields": "Id,IsActive"})
        if owner.get("IsActive") is not True:
            raise SalesforceError("standard_owner_inactive")
        opportunities = get_json(self.writer, API + "/query", params={
            "q": "SELECT Id FROM Opportunity WHERE AccountId='" + s.account + "' AND IsClosed=false LIMIT 1"})
        if opportunities.get("totalSize") != 0 or not opportunities.get("done"):
            raise SalesforceError("standard_active_opportunity")
        return {"account": a, "contact": c}

    def envelope(self, key):
        return {"version": "gtm-standard-v1", "run_id": self.scope.run_id, "action_key": key,
                "account_id": self.scope.account, "contact_id": self.scope.contact, "owner_id": self.scope.owner,
                "notice": NOTICE, "message": MESSAGE}

    def body(self, key):
        return {"WhatId": self.scope.account, "WhoId": self.scope.contact, "OwnerId": self.scope.owner,
                "Subject": SUBJECT, "Status": "Not Started", "Priority": "Normal", "IsReminderSet": False,
                "GTM_Action_Key__c": key, "Description": canonical(self.envelope(key))}

    def receipt(self, key):
        self.guard()
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise SalesforceError("invalid_task_key")
        response = self.reader.request("GET", API + "/sobjects/" + RECEIPT + "/Action_Key__c/" + key)
        if response.status_code == 404:
            # A missing object is NOT evidence of a missing effect.
            get_json(self.reader, API + "/sobjects/" + RECEIPT + "/describe")
            return None
        success(response)
        row = response.json()
        expected = canonical(self.envelope(key))
        if (row.get("Action_Key__c") != key or row.get("Payload__c") != expected
                or row.get("Payload_Hash__c") != digest(self.envelope(key))):
            raise SalesforceError("task_receipt_content_mismatch")
        task_id = identifier(row.get("Task_Id__c"), "00T")
        task = get_json(self.reader, API + "/sobjects/Task/" + task_id, params={
            "fields": "Id,WhatId,WhoId,OwnerId,CreatedById,Subject,Description,GTM_Action_Key__c,Status,Priority,IsReminderSet"})
        for field, value in self.body(key).items():
            if field != "Status" and task.get(field) != value:
                raise SalesforceError("task_independent_readback_mismatch")
        if task.get("CreatedById") != self.scope.writer:
            raise SalesforceError("task_creator_mismatch")
        inventory = get_json(self.reader, API + "/query", params={
            "q": "SELECT Id FROM Task WHERE GTM_Action_Key__c='" + key + "'"})
        if (not inventory.get("done") or inventory.get("totalSize") != 1 or
                inventory["records"][0]["Id"] != task_id):
            raise SalesforceError("task_duplicate_or_inventory_mismatch")
        return {"task_id_hash": digest(task_id), "receipt_id_hash": digest(row["Id"]),
                "payload_hash": digest(self.envelope(key)), "exact_content": True, "task_count": 1}


class TaskDispatcher:
    """Durable reservation, three attempts, receipt before current authorization. No implicit retries."""
    def __init__(self, engine, crm):
        self.engine, self.crm = engine, crm
        with engine.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS crm_tasks (native_key TEXT PRIMARY KEY, action_key TEXT NOT NULL, "
                       "pin TEXT NOT NULL, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, "
                       "status TEXT NOT NULL DEFAULT 'approved', next_attempt TEXT, last_error TEXT, receipt TEXT)")

    def prepare(self, action_key, now):
        if not self.engine.audit_valid():
            raise SalesforceError("local_audit_integrity_failed")
        self.crm.guard()
        with self.engine.transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_key=?", (action_key,)).fetchone()
            if not row:
                raise SalesforceError("local_exact_approval_required")
            self.engine.authorize(db, dict(row), now)
            action = bound_approval(db, row)
            if action["contact"] != "review@account-04.example":
                raise SalesforceError("synthetic_local_contact_mapping_required")
            key = digest(["gtm-standard-v1", self.crm.pin, action_key])
            payload = canonical(self.crm.envelope(key))
            prior = db.execute("SELECT * FROM crm_tasks WHERE native_key=?", (key,)).fetchone()
            if prior and prior["payload"] != payload:
                raise SalesforceError("standard_intent_conflict")
            db.execute("INSERT OR IGNORE INTO crm_tasks(native_key,action_key,pin,payload) VALUES(?,?,?,?)",
                       (key, action_key, self.crm.pin, payload))
            self.engine.audit(db, now, "standard_task_intent", key, {"pin": self.crm.pin, "payload_hash": digest(json.loads(payload))})
        return key

    def dispatch(self, key, now):
        from datetime import timedelta
        from .contracts import DomainError, moment, stamp
        if not self.engine.audit_valid():
            raise SalesforceError("local_audit_integrity_failed")
        with self.engine.connection() as db:
            row = db.execute("SELECT * FROM crm_tasks WHERE native_key=?", (key,)).fetchone()
            if not row or row["pin"] != self.crm.pin or row["payload"] != canonical(self.crm.envelope(key)):
                raise SalesforceError("standard_durable_intent_required")
            action = db.execute("SELECT * FROM actions WHERE action_key=?", (row["action_key"],)).fetchone()
            bound_approval(db, action)
        try:
            receipt = self.crm.receipt(key)
            if receipt:
                return self.save(key, now, "reconciled", receipt=receipt)
            if row["receipt"]:
                raise SalesforceError("previously_verified_task_receipt_missing")
            if row["status"] == "blocked":
                return {"status": "blocked", "error": row["last_error"]}
            if row["attempts"] >= 3:
                return self.save(key, now, "exhausted", "native_write_budget_exhausted")
            if row["next_attempt"] and now < row["next_attempt"]:
                return {"status": "waiting"}
            with self.engine.transaction() as db:
                reserved = db.execute("UPDATE crm_tasks SET attempts=attempts+1,status='uncertain' "
                                      "WHERE native_key=? AND attempts=?", (key, row["attempts"]))
                if reserved.rowcount != 1:
                    return {"status": "busy"}
                self.engine.authorize(db, dict(action), now)
                self.crm.resolve()
                self.engine.audit(db, now, "standard_task_attempt", key, {"attempt": row["attempts"] + 1})
            # Reservation committed before external request; server uniqueness covers competing writers.
            response = self.crm.writer.request("POST", API + "/sobjects/Task", json=self.crm.body(key),
                                               headers={"Sforce-Email-Header": "triggerUserEmail=false"})
            success(response)
            receipt = self.crm.receipt(key)
            if not receipt:
                raise SalesforceError("task_not_independently_visible", True)
            return self.save(key, now, "delivered", receipt=receipt)
        except DomainError as error:
            retryable = getattr(error, "retryable", False)
            due = stamp(moment(now) + timedelta(seconds=2 ** min(row["attempts"] + 1, 3))) if retryable else None
            return self.save(key, now, "uncertain" if retryable else "blocked", str(error), due=due)

    def save(self, key, now, status, error=None, receipt=None, due=None):
        with self.engine.transaction() as db:
            db.execute("UPDATE crm_tasks SET status=?,last_error=?,next_attempt=?,receipt=coalesce(?,receipt) WHERE native_key=?",
                       (status, error, due, canonical(receipt) if receipt else None, key))
            self.engine.audit(db, now, "standard_task_observation", key,
                              {"status": status, "error": error, "receipt_hash": digest(receipt) if receipt else None})
        return {"status": status, "error": error, "receipt": receipt}
