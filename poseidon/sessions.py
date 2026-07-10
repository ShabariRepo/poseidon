"""SQLite-backed session store: message history + running cost per session."""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class SessionStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created REAL,
                title TEXT DEFAULT '',
                messages TEXT DEFAULT '[]',
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                cost REAL DEFAULT 0,
                priced INTEGER DEFAULT 1
            )"""
        )
        self._db.commit()

    def create(self) -> str:
        sid = uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (id, created) VALUES (?, ?)", (sid, time.time())
            )
            self._db.commit()
        return sid

    def exists(self, sid: str) -> bool:
        row = self._db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone()
        return row is not None

    def get_messages(self, sid: str) -> list:
        row = self._db.execute(
            "SELECT messages FROM sessions WHERE id=?", (sid,)
        ).fetchone()
        return json.loads(row[0]) if row else []

    def save_messages(self, sid: str, messages: list) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE sessions SET messages=? WHERE id=?", (json.dumps(messages), sid)
            )
            self._db.commit()

    def add_usage(self, sid: str, usd: float, priced: bool, usage: dict) -> None:
        with self._lock:
            self._db.execute(
                """UPDATE sessions SET cost = cost + ?,
                       tokens_in = tokens_in + ?,
                       tokens_out = tokens_out + ?,
                       priced = priced & ?
                   WHERE id=?""",
                (
                    usd,
                    (usage or {}).get("prompt_tokens", 0),
                    (usage or {}).get("completion_tokens", 0),
                    1 if priced else 0,
                    sid,
                ),
            )
            self._db.commit()

    def get_cost(self, sid: str) -> dict:
        row = self._db.execute(
            "SELECT cost, tokens_in, tokens_out, priced FROM sessions WHERE id=?", (sid,)
        ).fetchone()
        if not row:
            return {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "priced": True}
        return {
            "cost": row[0],
            "tokens_in": row[1],
            "tokens_out": row[2],
            "priced": bool(row[3]),
        }

    def total_cost(self) -> float:
        row = self._db.execute("SELECT COALESCE(SUM(cost), 0) FROM sessions").fetchone()
        return row[0] or 0.0
