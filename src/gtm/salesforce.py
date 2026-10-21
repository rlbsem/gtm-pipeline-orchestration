"""Pinned test-org, create-only internal reviews. Never a sequence sender or generic CRM writer."""
import json
import re
from dataclasses import asdict, dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import httpx

from .contracts import DomainError, moment, stamp
from .store import canonical, digest
from .worker import bound_approval

API = "/services/data/v65.0"
OBJECT = "Seller_Action__c"
NOTICE = "SYNTHETIC GTM DEMONSTRATION: internal review only; no prospect communication or native pipeline outcome."
IMMUTABLE_FIELDS = {"Action_Key__c", "Payload_Hash__c", "Payload__c", "Brand__c", "Account_Key__c",
                    "Proposed_Owner__c", "Mapping_Hash__c", "Synthetic_Account__c", "Proposed_User__c",
                    "Subject__c", "Proposed_Action__c", "Draft__c", "Review_Notice__c"}


class SalesforceError(DomainError):
    def __init__(self, code, retryable=False):
        super().__init__(code)
        self.retryable = retryable


def identifier(value, prefix=None):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9]{18}", value) or (prefix and not value.startswith(prefix)):
        raise SalesforceError("invalid_pinned_salesforce_id")
    return value


@dataclass(frozen=True)
class Approval:
    org_id: str
    environment: str
    organization_type: str
    approved: bool

    def __post_init__(self):
        identifier(self.org_id, "00D")
        if (self.approved is not True or self.environment not in {"sandbox", "developer_edition"}
                or not self.organization_type or
                (self.environment == "developer_edition" and self.organization_type != "Developer Edition")):
            raise SalesforceError("approved_test_environment_required")

    def verify(self, org):
        if (org.get("Id") != self.org_id or org.get("OrganizationType") != self.organization_type
                or org.get("IsSandbox") is not (self.environment == "sandbox")):
            raise SalesforceError("pinned_test_environment_mismatch")


@dataclass(frozen=True)
class Mapping:
    local_brand: str
    local_account: str
    local_owner: str
    provider_brand: str
    provider_account: str
    provider_owner: str
    registry_id: str
    user_id: str

    def __post_init__(self):
        identifier(self.registry_id)
        identifier(self.user_id, "005")
        if (self.local_brand not in {"atlas", "harbor"} or not self.local_owner.startswith(self.local_brand + "-")
                or not re.fullmatch(r"acc_[a-f0-9]{16}", self.local_account)
                or not re.fullmatch(r"account-[0-9]{4,8}", self.provider_account)
                or not re.fullmatch(r"[a-z][a-z0-9-]{0,79}", self.provider_brand)
                or not self.provider_owner.startswith(self.provider_brand + "-")):
            raise SalesforceError("explicit_brand_alias_mapping_required")

    def match(self, action):
        if (action["brand"], action["account_id"], action["owner"]) != (
                self.local_brand, self.local_account, self.local_owner):
            raise SalesforceError("unapproved_local_account_owner_mapping")


class SalesforceClient:
    """No implicit retries, proxies, redirects, token logging or broad data queries."""
    def __init__(self, origin, token, observer=None, *, read_only=False):
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".my.salesforce.com")
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise SalesforceError("invalid_salesforce_origin")
        if not token or any(x.isspace() for x in token):
            raise SalesforceError("invalid_salesforce_credential")
        self.client = httpx.Client(base_url=origin.rstrip("/"), timeout=15, trust_env=False,
                                   follow_redirects=False, headers={"Authorization": "Bearer " + token, "updateMru": "false"})
        self.observer = observer
        self.read_only = read_only

    def request(self, method, path, **kwargs):
        if self.read_only and method != "GET":
            raise SalesforceError("read_only_identity_write_denied")
        if not path.startswith((API + "/", "/services/oauth2/userinfo")):
            raise SalesforceError("unexpected_salesforce_resource")
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TransportError:
            raise SalesforceError("native_outcome_unknown", True) from None
        if self.observer:
            self.observer(method, path, response)
        return response

    def close(self):
        self.client.close()


def success(response):
    if 200 <= response.status_code < 300:
        return
    if response.status_code == 429 or response.status_code >= 500:
        raise SalesforceError("native_retryable_or_unknown", True)
    raise SalesforceError("native_http_" + str(response.status_code))


def get_json(client, path, **kwargs):
    response = client.request("GET", path, **kwargs)
    success(response)
    try:
        return response.json()
    except ValueError:
        raise SalesforceError("native_invalid_json") from None


class ReviewInbox:
    def __init__(self, writer, reader, administrator, approval, mapping, integration_user, reviewer_user):
        if not isinstance(approval, Approval) or not isinstance(mapping, Mapping):
            raise SalesforceError("typed_approval_mapping_required")
        self.writer, self.reader, self.administrator = writer, reader, administrator
        self.approval, self.mapping = approval, mapping
        self.integration_user = identifier(integration_user, "005")
        self.reviewer_user = identifier(reviewer_user, "005")
        if self.integration_user == self.reviewer_user:
            raise SalesforceError("independent_identities_required")
        self.ready = False

    @property
    def pin(self):
        return digest({"approval": asdict(self.approval), "mapping": asdict(self.mapping),
                       "writer": self.integration_user, "reader": self.reviewer_user, "object": OBJECT})

    def preflight(self):
        self.ready = False
        org = get_json(self.administrator, API + "/query", params={
            "q": "SELECT Id,IsSandbox,OrganizationType FROM Organization"})
        if org.get("done") is not True or org.get("totalSize") != 1 or len(org.get("records", [])) != 1:
            raise SalesforceError("organization_cardinality_invalid")
        self.approval.verify(org["records"][0])
        for client, expected in ((self.writer, self.integration_user), (self.reader, self.reviewer_user)):
            who = get_json(client, "/services/oauth2/userinfo")
            if who.get("organization_id") != self.approval.org_id or who.get("user_id") != expected:
                raise SalesforceError("pinned_identity_mismatch")
        schema = get_json(self.writer, API + "/sobjects/" + OBJECT + "/describe")
        if (schema.get("name") != OBJECT or schema.get("createable") is not True
                or schema.get("queryable") is not True or schema.get("updateable") is not False
                or schema.get("deletable") is not False):
            raise SalesforceError("create_only_integration_required")
        fields = {f["name"]: f for f in schema.get("fields", [])}
        for name in IMMUTABLE_FIELDS:
            if fields.get(name, {}).get("createable") is not True:
                raise SalesforceError("native_create_field_denied")
        if not fields["Action_Key__c"].get("unique") or not fields["Action_Key__c"].get("externalId"):
            raise SalesforceError("native_unique_external_id_required")
        if fields["Payload__c"].get("length", 0) < 16000:
            raise SalesforceError("native_payload_capacity_insufficient")
        review = get_json(self.reader, API + "/sobjects/" + OBJECT + "/describe")
        review_fields = {f["name"]: f for f in review.get("fields", [])}
        if (review.get("createable") is not False or review.get("queryable") is not True
                or review.get("deletable") is not False or any(n not in review_fields for n in IMMUTABLE_FIELDS)
                or any(review_fields[n].get("updateable") is not False for n in IMMUTABLE_FIELDS)
                or review_fields.get("Review_Status__c", {}).get("updateable") is not True):
            raise SalesforceError("restricted_independent_reviewer_required")
        self.validate_source()
        self.ready = True
        self._preflight_pin = self.pin
        return {"environment": self.approval.environment, "organization_type": self.approval.organization_type,
                "org_sha256": digest(self.approval.org_id), "destination_pin": self.pin,
                "create_only": True, "independent_reader": True, "unique_external_key": True,
                "schema_sha256": digest(schema), "reviewer_schema_sha256": digest(review)}

    def validate_source(self):
        m = self.mapping
        row = get_json(self.writer, API + "/sobjects/Synthetic_Account__c/" + m.registry_id,
                       params={"fields": "Id,Account_Key__c,Brand__c,Approved_Owner__c,Active__c,Synthetic__c,LastModifiedDate"})
        expected = {"Id": m.registry_id, "Account_Key__c": m.provider_brand + ":" + m.provider_account,
                    "Brand__c": m.provider_brand, "Approved_Owner__c": m.user_id,
                    "Active__c": True, "Synthetic__c": True}
        if any(row.get(k) != value for k, value in expected.items()):
            raise SalesforceError("native_synthetic_mapping_or_ownership_changed")
        user = get_json(self.writer, API + "/sobjects/User/" + m.user_id, params={"fields": "Id,IsActive"})
        if user.get("Id") != m.user_id or user.get("IsActive") is not True:
            raise SalesforceError("native_owner_inactive")
        return {k: row[k] for k in (*expected, "LastModifiedDate") if k in row}

    def body(self, native_key, envelope):
        m = self.mapping
        action = envelope["action"]
        m.match(action)
        if envelope.get("version") != "gtm-crm-review/v1" or envelope.get("destination_pin") != self.pin:
            raise SalesforceError("native_envelope_pin_mismatch")
        if not re.fullmatch(r"[a-f0-9]{64}", native_key):
            raise SalesforceError("invalid_native_key")
        content = canonical(envelope)
        if len(content.encode("utf-16-le")) // 2 > 16000:
            raise SalesforceError("native_envelope_too_large")
        return {"Action_Key__c": native_key, "Payload_Hash__c": digest(envelope), "Payload__c": content,
                "Brand__c": m.provider_brand, "Account_Key__c": m.provider_account,
                "Proposed_Owner__c": m.provider_owner, "Mapping_Hash__c": digest(asdict(m)),
                "Synthetic_Account__c": m.registry_id, "Proposed_User__c": m.user_id,
                "Subject__c": "Synthetic GTM internal review", "Proposed_Action__c": "schedule_discovery",
                "Draft__c": action["message"], "Review_Notice__c": NOTICE}

    def receipt(self, key, envelope, independent=False):
        if not self.ready or self._preflight_pin != self.pin:
            raise SalesforceError("native_preflight_required")
        expected = self.body(key, envelope)
        client = self.reader if independent else self.writer
        response = client.request("GET", API + f"/sobjects/{OBJECT}/Action_Key__c/" + key)
        if response.status_code == 404:
            return None
        success(response)
        row = response.json()
        if any(row.get(k) != value for k, value in expected.items()):
            raise SalesforceError("native_readback_content_conflict")
        identifier(row.get("Id"))
        return {"record_id": row["Id"], "native_key": key, "envelope_hash": digest(envelope),
                "review_status": row.get("Review_Status__c"), "exact_content_verified": True,
                "observer": "independent_reviewer" if independent else "integration"}

    def create(self, key, envelope):
        if not self.ready or self._preflight_pin != self.pin:
            raise SalesforceError("native_preflight_required")
        self.validate_source()
        response = self.writer.request("POST", API + "/sobjects/" + OBJECT + "/",
                                       json={**self.body(key, envelope), "Review_Status__c": "Pending"})
        if response.status_code == 400:
            errors = response.json()
            if isinstance(errors, list) and errors and all(e.get("errorCode") == "DUPLICATE_VALUE" for e in errors):
                return
        success(response)


class NativeDispatcher:
    """Separate durable CRM-review journal; never labels an internal review as sequence delivery."""
    def __init__(self, engine, inbox):
        self.engine, self.inbox = engine, inbox
        with engine.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS crm_reviews(
                 native_key TEXT PRIMARY KEY,action_key TEXT NOT NULL,run_id TEXT NOT NULL,destination_pin TEXT NOT NULL,
                 envelope TEXT NOT NULL,envelope_hash TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
                 next_attempt TEXT,receipt TEXT,last_error TEXT,UNIQUE(run_id,action_key,destination_pin));
                CREATE TRIGGER IF NOT EXISTS crm_intent_immutable BEFORE UPDATE OF
                 action_key,run_id,destination_pin,envelope,envelope_hash ON crm_reviews
                 BEGIN SELECT RAISE(ABORT,'immutable_crm_intent'); END;
            """)

    def prepare(self, action_key, run_id, now, advice=None):
        now = stamp(moment(now))
        if not self.engine.audit_valid():
            raise SalesforceError("local_audit_integrity_failed")
        if not re.fullmatch(r"gtm-[a-zA-Z0-9-]{6,70}", run_id):
            raise SalesforceError("scoped_native_run_id_required")
        with self.engine.transaction() as db:
            row = db.execute("SELECT * FROM actions WHERE action_key=?", (action_key,)).fetchone()
            if not row:
                raise SalesforceError("local_exact_approval_required")
            self.engine.authorize(db, dict(row), now)
            action = bound_approval(db, row)
            self.inbox.mapping.match(action)
            prior = db.execute("SELECT * FROM crm_reviews WHERE run_id=? AND action_key=? AND destination_pin=?",
                               (run_id, action_key, self.inbox.pin)).fetchone()
            if prior:
                return dict(prior)
            envelope = {"version": "gtm-crm-review/v1", "destination_pin": self.inbox.pin,
                        "action": action, "context_hash": row["context_hash"], "run_id": run_id,
                        "advisory_reference": advice, "boundary": "internal review; local engagement and synthetic outcomes are separate"}
            key = digest(["gtm-crm-review/v1", run_id, action_key, self.inbox.pin])
            db.execute("INSERT INTO crm_reviews(native_key,action_key,run_id,destination_pin,envelope,envelope_hash,status) "
                       "VALUES(?,?,?,?,?,?,'approved')", (key, action_key, run_id, self.inbox.pin, canonical(envelope), digest(envelope)))
            self.engine.audit(db, now, "native_review_intent", key,
                              {"action_key": action_key, "envelope_hash": digest(envelope), "destination_pin": self.inbox.pin})
            return dict(db.execute("SELECT * FROM crm_reviews WHERE native_key=?", (key,)).fetchone())

    def dispatch(self, key, now):
        now = stamp(moment(now))
        if not self.engine.audit_valid():
            raise SalesforceError("local_audit_integrity_failed")
        with self.engine.connection() as db:
            row = db.execute("SELECT * FROM crm_reviews WHERE native_key=?", (key,)).fetchone()
            if not row or row["destination_pin"] != self.inbox.pin:
                raise SalesforceError("native_durable_intent_required")
            intent = dict(row)
            action = db.execute("SELECT * FROM actions WHERE action_key=?", (intent["action_key"],)).fetchone()
            if not action:
                raise SalesforceError("native_local_intent_missing")
            bound_approval(db, action)
        envelope = json.loads(intent["envelope"])
        if digest(envelope) != intent["envelope_hash"] or envelope["action"] != json.loads(action["payload"]):
            raise SalesforceError("native_intent_tampered")
        # Existing native effects reconcile even when NEW action authorization has since expired/revoked.
        try:
            receipt = self.inbox.receipt(key, envelope, independent=True)
            if receipt:
                return self._save(key, now, "reconciled", None, receipt)
        except SalesforceError as error:
            return self._save(key, now, "uncertain" if error.retryable else "blocked", str(error))
        if intent["status"] == "blocked":
            return {"status": "blocked", "error": intent["last_error"]}
        if intent["attempts"] >= 3:
            return self._save(key, now, "exhausted", "native_write_budget_exhausted")
        if intent["next_attempt"] and now < intent["next_attempt"]:
            return {"status": "waiting", "next_attempt": intent["next_attempt"]}
        with self.engine.transaction() as db:
            current = db.execute("SELECT * FROM crm_reviews WHERE native_key=?", (key,)).fetchone()
            if current["attempts"] != intent["attempts"] or current["receipt"]:
                return {"status": "busy"}
            db.execute("UPDATE crm_reviews SET attempts=attempts+1,status='uncertain' WHERE native_key=?", (key,))
            self.engine.audit(db, now, "native_attempt_reserved", key, {"attempt": current["attempts"] + 1})
        try:
            with self.engine.transaction() as db:
                current_action = dict(db.execute("SELECT * FROM actions WHERE action_key=?", (intent["action_key"],)).fetchone())
                self.engine.authorize(db, current_action, now)
                self.inbox.create(key, envelope)
            receipt = self.inbox.receipt(key, envelope, independent=True)
            if not receipt:
                raise SalesforceError("native_create_not_independently_visible", True)
            return self._save(key, now, "delivered", None, receipt)
        except DomainError as error:
            retryable = getattr(error, "retryable", False)
            return self._save(key, now, "uncertain" if retryable else "blocked", str(error))

    def _save(self, key, now, status, error, receipt=None):
        with self.engine.transaction() as db:
            row = db.execute("SELECT attempts FROM crm_reviews WHERE native_key=?", (key,)).fetchone()
            due = stamp(moment(now) + timedelta(seconds=2 ** row[0])) if status == "uncertain" else None
            db.execute("UPDATE crm_reviews SET status=?,last_error=?,next_attempt=?,receipt=coalesce(?,receipt) WHERE native_key=?",
                       (status, error, due, canonical(receipt) if receipt else None, key))
            self.engine.audit(db, now, "native_review_observation", key,
                              {"status": status, "error": error, "receipt_hash": digest(receipt) if receipt else None})
        return {"status": status, "error": error, "receipt": receipt}


def standard_resolution(inbox, account_id, contact_id, expected_owner, marker):
    """Optional exact-ID synthetic standard-object read. No unscoped discovery or writes."""
    if not isinstance(inbox, ReviewInbox) or not inbox.ready or inbox._preflight_pin != inbox.pin:
        raise SalesforceError("native_preflight_required")
    client = inbox.writer
    identifier(account_id, "001")
    identifier(contact_id, "003")
    identifier(expected_owner, "005")
    if not re.fullmatch(r"GTM-SYNTHETIC-[a-zA-Z0-9-]{6,60}", marker):
        raise SalesforceError("approved_synthetic_marker_required")
    account = get_json(client, API + "/sobjects/Account/" + account_id,
                       params={"fields": "Id,OwnerId,Description,Website"})
    contact = get_json(client, API + "/sobjects/Contact/" + contact_id,
                       params={"fields": "Id,AccountId,OwnerId,Email,Description"})
    website = urlsplit(account.get("Website", ""))
    email = contact.get("Email", "")
    if (account.get("Id") != account_id or contact.get("Id") != contact_id
            or contact.get("AccountId") != account_id or account.get("OwnerId") != expected_owner
            or contact.get("OwnerId") != expected_owner or account.get("Description") != marker
            or contact.get("Description") != marker or not website.hostname
            or not website.hostname.endswith((".example", ".test", ".invalid"))
            or email.rsplit("@", 1)[-1] != website.hostname):
        raise SalesforceError("standard_synthetic_identity_or_owner_mismatch")
    return {"account": account, "contact": contact}
