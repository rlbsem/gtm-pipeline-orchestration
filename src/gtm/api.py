"""Loopback operator interface. It is not a publicly deployable multi-user authorization service."""
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from .advice import research
from .contracts import DomainError, moment, stamp
from .fixtures import FINISH, START, outcome, record
from .measurement import measure
from .worker import reconcile

WEB = Path(__file__).resolve().parents[2] / "web"


def create_app(engine, destination, worker):
    app = FastAPI(title="GTM Pipeline Orchestration · synthetic local demo", docs_url=None, redoc_url=None)
    with engine.transaction() as db:
        db.execute("INSERT OR IGNORE INTO runtime VALUES('operator_clock','2026-01-21T12:00:00Z')")
        app.state.clock = db.execute("SELECT value FROM runtime WHERE key='operator_clock'").fetchone()[0]

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"error": "loopback_host_required"}, status_code=403)
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            if (request.headers.get("x-demo-intent") != "operator" or
                    (origin and urlparse(origin).netloc != request.headers.get("host"))):
                return JSONResponse({"error": "same_origin_operator_intent_required"}, status_code=403)
            try:
                size = int(request.headers.get("content-length", 0))
            except ValueError:
                return JSONResponse({"error": "invalid_body_length"}, status_code=400)
            if size > 32000:
                return JSONResponse({"error": "body_too_large"}, status_code=413)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; " \
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"error": str(error)}, status_code=409)

    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        return JSONResponse({"error": "contract_validation_failed", "details": str(error)}, status_code=422)

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in {"app.js", "style.css"}:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return FileResponse(WEB / name)

    @app.get("/api/state")
    def state():
        accounts = []
        for a in engine.rows("accounts"):
            with engine.connection() as db:
                score = engine._score(db, a["id"], app.state.clock)
            cohort = next((c for c in engine.rows("cohorts") if c["account_id"] == a["id"]), None)
            accounts.append({**a, "score": score, "cohort": cohort})
        return {"clock": app.state.clock, "measurement_clock": FINISH,
                "accounts": accounts, "actions": engine.rows("actions"), "routes": engine.rows("routes"),
                "outcomes": engine.rows("feedback"), "sources": engine.rows("sources"),
                "audit": engine.rows("audit")[-100:], "measurement": measure(engine, FINISH),
                "reconciliation": reconcile(engine, worker.client), "audit_valid": engine.audit_valid(),
                "inference": "not_executed", "native_vendors": "not_executed"}

    @app.get("/api/accounts/{account_id}/research")
    def brief(account_id: str):
        return research(engine, account_id)

    @app.post("/api/accounts/{account_id}/prepare")
    def prepare(account_id: str):
        return engine.prepare(account_id, app.state.clock)

    @app.post("/api/accounts/{account_id}/approve")
    def approve(account_id: str, body: dict):
        if set(body) != {"prepared", "reviewer"}:
            raise DomainError("closed_approval_envelope")
        return engine.approve(account_id, body["prepared"], body["reviewer"], app.state.clock)

    @app.post("/api/actions/{action_key}/dispatch")
    def dispatch(action_key: str):
        return worker.dispatch(action_key, app.state.clock)

    @app.post("/api/ingest")
    def ingest(body: dict):
        return engine.ingest(body, app.state.clock)

    @app.post("/api/clock")
    def clock(body: dict):
        at = stamp(moment(body["at"]))
        with engine.transaction() as db:
            previous = db.execute("SELECT value FROM runtime WHERE key='operator_clock'").fetchone()[0]
            if not START <= at <= FINISH or at < previous:
                raise DomainError("scenario_clock_cannot_regress_or_leave_window")
            db.execute("UPDATE runtime SET value=? WHERE key='operator_clock'", (at,))
            app.state.clock = at
        return {"clock": at}

    @app.post("/api/fault")
    def fault(body: dict):
        if body.get("fault") not in {"none", "lost_ack", "rate_limit"}:
            raise DomainError("unknown_fault")
        with destination.lock:
            destination.fault = body["fault"]
        return {"armed": body["fault"], "scope": "next_local_enrollment_request_only"}

    @app.post("/api/accounts/{account_id}/feedback")
    def feedback(account_id: str, body: dict):
        kind = body.get("kind")
        if kind not in {"reply_positive", "meeting_qualified", "opportunity_accepted"}:
            raise DomainError("unsupported_demo_feedback")
        actions = [a for a in engine.rows("actions") if a["account_id"] == account_id and a["receipt"]]
        if not actions:
            raise DomainError("verified_enrollment_required")
        action = actions[-1]
        known = [f for f in engine.rows("feedback") if f["account_id"] == account_id and f["action_key"] == action["action_key"]]
        parent_kind = {"meeting_qualified": "reply_positive", "opportunity_accepted": "meeting_qualified"}.get(kind)
        parent = next((f["business_id"] for f in known if f["kind"] == parent_kind), None)
        if parent_kind and not parent:
            raise DomainError("record_preceding_feedback_first")
        return outcome(engine, account_id, "interactive-" + kind + "-" + account_id, kind, app.state.clock,
                       1500000 if kind == "opportunity_accepted" else 0, action["action_key"], parent,
                       client=worker.client)

    @app.post("/api/accounts/{account_id}/optout")
    def optout(account_id: str):
        with engine.connection() as db:
            a = engine.account(db, account_id)
        return engine.ingest(record("web", "interactive-optout-" + account_id, a["brand"], "consent", a["domain"],
                             {"allowed": False}, app.state.clock, account_id), app.state.clock)

    return app
