PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(
 id TEXT PRIMARY KEY, brand TEXT NOT NULL, domain TEXT NOT NULL, name TEXT NOT NULL,
 territory TEXT NOT NULL, lifecycle TEXT NOT NULL, owner TEXT NOT NULL,
 owner_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 suppressed INTEGER NOT NULL DEFAULT 0 CHECK(suppressed IN(0,1)));
CREATE TABLE IF NOT EXISTS fields(
 account_id TEXT NOT NULL REFERENCES accounts(id), name TEXT NOT NULL, value TEXT NOT NULL,
 source TEXT NOT NULL, observed_at TEXT NOT NULL, source_key TEXT NOT NULL,
 PRIMARY KEY(account_id,name));
CREATE TABLE IF NOT EXISTS contacts(
 account_id TEXT PRIMARY KEY REFERENCES accounts(id), email TEXT NOT NULL,
 consent INTEGER NOT NULL DEFAULT 0 CHECK(consent IN(0,1)), consent_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(
 source_key TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL, brand TEXT NOT NULL,
 kind TEXT NOT NULL, account_id TEXT, observed_at TEXT NOT NULL, received_at TEXT NOT NULL,
 payload TEXT NOT NULL, payload_hash TEXT NOT NULL, disposition TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS source_no_update BEFORE UPDATE ON sources BEGIN SELECT RAISE(ABORT,'immutable_source'); END;
CREATE TRIGGER IF NOT EXISTS source_no_delete BEFORE DELETE ON sources BEGIN SELECT RAISE(ABORT,'immutable_source'); END;
CREATE TABLE IF NOT EXISTS decisions(
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), at TEXT NOT NULL,
 policy_hash TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cohorts(
 experiment TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES accounts(id), arm TEXT NOT NULL,
 assigned_at TEXT NOT NULL, window_end TEXT NOT NULL, eligibility_decision TEXT NOT NULL,
 PRIMARY KEY(experiment,account_id));
CREATE TRIGGER IF NOT EXISTS cohort_no_update BEFORE UPDATE ON cohorts BEGIN SELECT RAISE(ABORT,'immutable_cohort'); END;
CREATE TRIGGER IF NOT EXISTS cohort_no_delete BEFORE DELETE ON cohorts BEGIN SELECT RAISE(ABORT,'immutable_cohort'); END;
CREATE TABLE IF NOT EXISTS actions(
 action_key TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 experiment TEXT NOT NULL, decision_id TEXT NOT NULL, approved_at TEXT NOT NULL,
 owner_revision INTEGER NOT NULL, context_hash TEXT NOT NULL, payload TEXT NOT NULL,
 payload_hash TEXT NOT NULL, reviewer TEXT NOT NULL, status TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt TEXT, receipt TEXT, last_error TEXT);
CREATE TRIGGER IF NOT EXISTS action_content_immutable BEFORE UPDATE OF
 account_id,experiment,decision_id,approved_at,owner_revision,context_hash,payload,payload_hash,reviewer ON actions
 BEGIN SELECT RAISE(ABORT,'immutable_approval'); END;
CREATE TABLE IF NOT EXISTS feedback(
 event_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 kind TEXT NOT NULL, business_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
 received_at TEXT NOT NULL, amount_cents INTEGER NOT NULL DEFAULT 0,
 action_key TEXT, origin TEXT NOT NULL, source_key TEXT NOT NULL, created_at TEXT NOT NULL, parent_id TEXT);
CREATE TABLE IF NOT EXISTS routes(
 source_key TEXT PRIMARY KEY, account_id TEXT, at TEXT NOT NULL,
 owner TEXT, status TEXT NOT NULL, reason TEXT NOT NULL, action_key TEXT);
CREATE TABLE IF NOT EXISTS audit(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, event TEXT NOT NULL,
 subject TEXT NOT NULL, detail TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'immutable_audit'); END;
