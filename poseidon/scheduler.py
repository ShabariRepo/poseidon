"""Scheduled autonomous runs. SQLite-backed; a background loop fires due
prompts as fresh sessions. Unattended runs can only take approval-gated
actions covered by an existing "always allow" rule — trust is earned first.
"""
import asyncio
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

POLL_SECS = 20


class Scheduler:
    def __init__(self, db_path: Path, runner):
        """runner: async fn(prompt) -> (session_id, final_text)"""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._runner = runner
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                prompt TEXT,
                kind TEXT,
                value TEXT,
                next_run REAL,
                last_run REAL,
                last_result TEXT DEFAULT '',
                last_session TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created REAL
            )"""
        )
        self._db.commit()

    # ---- schedule math ----
    @staticmethod
    def _compute_next(kind: str, value: str, after: float) -> float:
        if kind == "every":
            return after + max(1.0, float(value)) * 60
        if kind == "daily":
            hh, mm = value.split(":")
            candidate = datetime.fromtimestamp(after).replace(
                hour=int(hh), minute=int(mm), second=0, microsecond=0
            )
            if candidate.timestamp() <= after:
                candidate += timedelta(days=1)
            return candidate.timestamp()
        if kind == "once":
            return datetime.fromisoformat(value).timestamp()
        raise ValueError(f"unknown schedule kind: {kind}")

    # ---- CRUD ----
    def add(self, prompt: str, every_minutes=None, daily_at=None, once_at=None) -> dict:
        given = [x for x in (every_minutes, daily_at, once_at) if x]
        if len(given) != 1:
            raise ValueError("provide exactly one of every_minutes, daily_at, once_at")
        if every_minutes:
            kind, value = "every", str(float(every_minutes))
        elif daily_at:
            datetime.strptime(daily_at, "%H:%M")  # validate
            kind, value = "daily", daily_at
        else:
            kind, value = "once", once_at
        next_run = self._compute_next(kind, value, time.time())
        if kind == "once" and next_run <= time.time():
            raise ValueError("once_at is in the past")
        sid = uuid.uuid4().hex[:10]
        with self._lock:
            self._db.execute(
                "INSERT INTO schedules (id, prompt, kind, value, next_run, created) VALUES (?,?,?,?,?,?)",
                (sid, prompt, kind, value, next_run, time.time()),
            )
            self._db.commit()
        return {"id": sid, "next_run": datetime.fromtimestamp(next_run).isoformat(timespec="minutes")}

    def list(self) -> list:
        rows = self._db.execute(
            """SELECT id, prompt, kind, value, next_run, last_run, last_result, last_session
               FROM schedules WHERE enabled=1 ORDER BY next_run"""
        ).fetchall()
        fmt = lambda ts: datetime.fromtimestamp(ts).isoformat(timespec="minutes") if ts else None
        return [
            {
                "id": r[0],
                "prompt": r[1],
                "kind": r[2],
                "value": r[3],
                "next_run": fmt(r[4]),
                "last_run": fmt(r[5]),
                "last_result": (r[6] or "")[:300],
                "last_session": r[7],
            }
            for r in rows
        ]

    def cancel(self, sid: str) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE schedules SET enabled=0 WHERE id=? AND enabled=1", (sid,))
            self._db.commit()
        return cur.rowcount > 0

    # ---- firing ----
    async def loop(self):
        while True:
            await asyncio.sleep(POLL_SECS)
            now = time.time()
            due = self._db.execute(
                "SELECT id, prompt, kind, value FROM schedules WHERE enabled=1 AND next_run <= ?",
                (now,),
            ).fetchall()
            for row in due:
                self._advance(row)  # reschedule BEFORE running: no double-fire
                asyncio.ensure_future(self._fire(row[0], row[1]))

    def _advance(self, row):
        sid, _, kind, value = row
        with self._lock:
            if kind == "once":
                self._db.execute("UPDATE schedules SET enabled=0 WHERE id=?", (sid,))
            else:
                self._db.execute(
                    "UPDATE schedules SET next_run=? WHERE id=?",
                    (self._compute_next(kind, value, time.time()), sid),
                )
            self._db.commit()

    async def _fire(self, sid: str, prompt: str):
        try:
            session_id, text = await self._runner(prompt)
            result = text or "(no output)"
        except Exception as e:
            session_id, result = "", f"error: {str(e)[:200]}"
        with self._lock:
            self._db.execute(
                "UPDATE schedules SET last_run=?, last_result=?, last_session=? WHERE id=?",
                (time.time(), result[:1000], session_id, sid),
            )
            self._db.commit()
