import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text())
            db.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def audit(db, at, event, subject, detail):
        row = db.execute("SELECT digest FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row[0] if row else "genesis"
        body = {"at": at, "event": event, "subject": subject, "detail": detail, "previous": previous}
        db.execute("INSERT INTO audit(at,event,subject,detail,previous,digest) VALUES(?,?,?,?,?,?)",
                   (at, event, subject, canonical(detail), previous, digest(body)))

    def audit_valid(self):
        previous = "genesis"
        with self.connection() as db:
            for row in db.execute("SELECT * FROM audit ORDER BY seq"):
                body = {"at": row["at"], "event": row["event"], "subject": row["subject"],
                        "detail": json.loads(row["detail"]), "previous": previous}
                if row["previous"] != previous or row["digest"] != digest(body):
                    return False
                previous = row["digest"]
        return True

    def rows(self, table):
        if table not in {"accounts", "fields", "contacts", "sources", "decisions", "cohorts",
                         "actions", "routes", "feedback", "audit"}:
            raise ValueError("table_not_allowed")
        with self.connection() as db:
            return [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
