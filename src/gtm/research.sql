CREATE TABLE IF NOT EXISTS research_sources(source_id TEXT PRIMARY KEY, domain TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_runs(run_hash TEXT PRIMARY KEY,domain TEXT NOT NULL,approach TEXT NOT NULL,
 latency REAL NOT NULL,usable INTEGER NOT NULL CHECK(usable IN (0,1)),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_reviews(run_hash TEXT PRIMARY KEY REFERENCES research_runs(run_hash),
 review_hash TEXT UNIQUE NOT NULL,decision TEXT NOT NULL CHECK(decision IN ('approve','dismiss')),
 reviewed_at TEXT NOT NULL,payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_inputs(case_id TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES research_sources(source_id),PRIMARY KEY(case_id,source_id));
CREATE TRIGGER IF NOT EXISTS research_inputs_immutable_update BEFORE UPDATE ON research_inputs BEGIN SELECT RAISE(ABORT,'immutable_research_input'); END;
CREATE TRIGGER IF NOT EXISTS research_inputs_immutable_delete BEFORE DELETE ON research_inputs BEGIN SELECT RAISE(ABORT,'immutable_research_input'); END;
CREATE TRIGGER IF NOT EXISTS research_sources_immutable_update BEFORE UPDATE ON research_sources BEGIN SELECT RAISE(ABORT,'immutable_research_source'); END;
CREATE TRIGGER IF NOT EXISTS research_sources_immutable_delete BEFORE DELETE ON research_sources BEGIN SELECT RAISE(ABORT,'immutable_research_source'); END;
CREATE TRIGGER IF NOT EXISTS research_runs_immutable_update BEFORE UPDATE ON research_runs BEGIN SELECT RAISE(ABORT,'immutable_research_run'); END;
CREATE TRIGGER IF NOT EXISTS research_runs_immutable_delete BEFORE DELETE ON research_runs BEGIN SELECT RAISE(ABORT,'immutable_research_run'); END;
CREATE TRIGGER IF NOT EXISTS research_reviews_immutable_update BEFORE UPDATE ON research_reviews BEGIN SELECT RAISE(ABORT,'immutable_research_review'); END;
CREATE TRIGGER IF NOT EXISTS research_reviews_immutable_delete BEFORE DELETE ON research_reviews BEGIN SELECT RAISE(ABORT,'immutable_research_review'); END;
