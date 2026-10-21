"""Independent synthetic engagement service: its own database, request log and HTTP receipts."""
import json
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .contracts import Action, moment, stamp
from .store import canonical, digest


class Destination:
    def __init__(self, path, token=None, port=0):
        self.path = str(path)
        self.token = token or secrets.token_urlsafe(32)
        self.fault = "none"
        self.lock = threading.Lock()
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS receipts(action_key TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,
                  payload TEXT NOT NULL,accepted_at TEXT NOT NULL,receipt_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(seq INTEGER PRIMARY KEY,method TEXT,path TEXT,status INTEGER);
                CREATE TABLE IF NOT EXISTS feedback(event_key TEXT PRIMARY KEY,body TEXT NOT NULL);
            """)
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_json(self, status, body):
                with sqlite3.connect(parent.path) as db:
                    db.execute("INSERT INTO requests(method,path,status) VALUES(?,?,?)", (self.command, self.path, status))
                encoded = canonical(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def authorized(self):
                return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + parent.token)

            def do_GET(self):
                if not self.authorized():
                    return self.send_json(401, {"error": "unauthorized"})
                with sqlite3.connect(parent.path) as db:
                    db.row_factory = sqlite3.Row
                    rows = [dict(x) for x in db.execute("SELECT * FROM receipts ORDER BY action_key")]
                for row in rows:
                    row["payload"] = json.loads(row["payload"])
                if self.path == "/receipts":
                    return self.send_json(200, rows)
                if self.path == "/feedback":
                    with sqlite3.connect(parent.path) as db:
                        feedback = [json.loads(x[0]) for x in db.execute("SELECT body FROM feedback ORDER BY event_key")]
                    return self.send_json(200, feedback)
                if self.path.startswith("/receipts/"):
                    key = self.path.rsplit("/", 1)[1]
                    found = next((r for r in rows if r["action_key"] == key), None)
                    return self.send_json(200 if found else 404, found or {"error": "not_found"})
                return self.send_json(404, {"error": "not_found"})

            def do_POST(self):
                if not self.authorized():
                    return self.send_json(401, {"error": "unauthorized"})
                if self.path == "/feedback":
                    from .contracts import Record
                    try:
                        size = int(self.headers.get("Content-Length", 0))
                        if not 0 < size <= 16000:
                            raise ValueError("body_size")
                        event = Record.model_validate(json.loads(self.rfile.read(size)))
                        if event.kind != "outcome":
                            raise ValueError("outcome_required")
                        event_key = f"{event.source}:{event.brand}:{event.source_id}"
                        body_text = canonical(event.model_dump())
                        conflict = False
                        with sqlite3.connect(parent.path) as db:
                            old = db.execute("SELECT body FROM feedback WHERE event_key=?", (event_key,)).fetchone()
                            if old and old[0] != body_text:
                                conflict = True
                            elif not old:
                                db.execute("INSERT INTO feedback VALUES(?,?)", (event_key, body_text))
                        return self.send_json(409 if conflict else 200, {"event_key": event_key})
                    except (ValueError, TypeError):
                        return self.send_json(422, {"error": "invalid_feedback"})
                if self.path != "/enrollments":
                    return self.send_json(404, {"error": "not_found"})
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 16000:
                        raise ValueError("body_size")
                    body = json.loads(self.rfile.read(size))
                    if set(body) != {"payload", "payload_hash", "at"}:
                        raise ValueError("envelope")
                    payload = Action.model_validate(body["payload"]).model_dump()
                    if stamp(moment(body["at"])) != body["at"]:
                        raise ValueError("noncanonical_timestamp")
                    if digest(payload) != body["payload_hash"]:
                        raise ValueError("hash")
                except (ValueError, TypeError):
                    return self.send_json(422, {"error": "invalid_content"})
                with parent.lock:
                    fault, parent.fault = parent.fault, "none"
                if fault == "rate_limit":
                    return self.send_json(429, {"error": "synthetic_rate_limit", "retry_after_seconds": 2})
                conflict = False
                with sqlite3.connect(parent.path) as db:
                    db.row_factory = sqlite3.Row
                    db.execute("BEGIN IMMEDIATE")
                    old = db.execute("SELECT * FROM receipts WHERE action_key=?", (payload["action_key"],)).fetchone()
                    if old and (old["payload_hash"] != body["payload_hash"] or old["payload"] != canonical(payload)):
                        conflict = True
                    elif not old:
                        db.execute("INSERT INTO receipts VALUES(?,?,?,?,?)", (payload["action_key"], body["payload_hash"],
                                   canonical(payload), body["at"], "rcpt_" + digest(payload)[:24]))
                    db.commit()
                if conflict:
                    return self.send_json(409, {"error": "idempotency_content_collision"})
                if fault == "lost_ack":
                    # Real HTTP connection closes AFTER durable commit, before status/headers.
                    with sqlite3.connect(parent.path) as db:
                        db.execute("INSERT INTO requests(method,path,status) VALUES(?,?,0)", ("POST", self.path))
                    self.close_connection = True
                    return
                return self.send_json(200, {"accepted": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request_counts(self):
        with sqlite3.connect(self.path) as db:
            return dict(db.execute("SELECT method,count(*) FROM requests GROUP BY method"))

    def request_log(self):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(x) for x in db.execute("SELECT * FROM requests ORDER BY seq")]
