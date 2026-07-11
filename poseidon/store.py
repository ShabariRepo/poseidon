"""All persistence: projects, members, sessions, runs, run events, checkpoints.
Single SQLite file, single connection, coarse lock. Migrations run on init.
"""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

MAX_RUN_EVENTS = 500


def _now() -> float:
    return time.time()


def _id() -> str:
    return uuid.uuid4().hex[:12]


class Store:
    def __init__(self, db_path: Path, default_workdir: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._migrate(default_workdir)

    # ---------- schema ----------
    def _migrate(self, default_workdir: Path):
        c = self._db
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT, workdir TEXT,
                created REAL, settings TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS members (
                id TEXT PRIMARY KEY, name TEXT UNIQUE, color TEXT, created REAL
            );
            CREATE TABLE IF NOT EXISTS memberships (
                project_id TEXT, member_id TEXT, role TEXT DEFAULT 'member',
                PRIMARY KEY (project_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, created REAL, title TEXT DEFAULT '',
                messages TEXT DEFAULT '[]',
                tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0,
                cost REAL DEFAULT 0, priced INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, project_id TEXT, session_id TEXT,
                parent_run_id TEXT, kind TEXT, label TEXT, status TEXT,
                started REAL, finished REAL, cost REAL DEFAULT 0,
                result TEXT DEFAULT '', meta TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_runs_project ON runs (project_id, started);
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts REAL,
                type TEXT, payload TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_run ON run_events (run_id, id);
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY, session_id TEXT, project_id TEXT,
                member_id TEXT, ts REAL, label TEXT, progress TEXT DEFAULT '',
                messages TEXT, files TEXT DEFAULT '{}', auto INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_ckpt_session ON checkpoints (session_id, ts);
            """
        )
        # sessions table upgrades (pre-0.5 databases)
        cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)")}
        for col, decl in [
            ("project_id", "TEXT"), ("member_id", "TEXT"),
            ("progress", "TEXT DEFAULT ''"), ("updated", "REAL"),
        ]:
            if col not in cols:
                c.execute(f"ALTER TABLE sessions ADD COLUMN {col} {decl}")
        scols = {r[1] for r in c.execute("PRAGMA table_info(schedules)")}
        if scols and "project_id" not in scols:
            c.execute("ALTER TABLE schedules ADD COLUMN project_id TEXT")
        # bootstrap defaults
        if not c.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
            c.execute(
                "INSERT INTO projects (id, name, workdir, created) VALUES (?,?,?,?)",
                ("default", "Default", str(default_workdir), _now()),
            )
        if not c.execute("SELECT 1 FROM members LIMIT 1").fetchone():
            c.execute(
                "INSERT INTO members (id, name, color, created) VALUES (?,?,?,?)",
                ("owner", "Owner", "#0f7fa8", _now()),
            )
        c.execute(
            "INSERT OR IGNORE INTO memberships (project_id, member_id, role) VALUES ('default','owner','admin')"
        )
        c.execute("UPDATE sessions SET project_id='default' WHERE project_id IS NULL")
        c.execute("UPDATE sessions SET member_id='owner' WHERE member_id IS NULL")
        if scols:
            c.execute("UPDATE schedules SET project_id='default' WHERE project_id IS NULL")
        c.commit()

    def _exec(self, sql, params=()):
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    # ---------- projects & members ----------
    def create_project(self, name: str, workdir: str, member_id: str) -> dict:
        pid = _id()
        self._exec(
            "INSERT INTO projects (id, name, workdir, created) VALUES (?,?,?,?)",
            (pid, name, workdir, _now()),
        )
        self._exec(
            "INSERT INTO memberships (project_id, member_id, role) VALUES (?,?,'admin')",
            (pid, member_id),
        )
        return self.get_project(pid)

    def get_project(self, pid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None

    def list_projects(self) -> list:
        rows = self._db.execute("SELECT * FROM projects ORDER BY created").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["members"] = [
                dict(m)
                for m in self._db.execute(
                    """SELECT m.id, m.name, m.color, ms.role FROM members m
                       JOIN memberships ms ON ms.member_id=m.id WHERE ms.project_id=?""",
                    (r["id"],),
                )
            ]
            out.append(d)
        return out

    def create_member(self, name: str, color: str) -> dict:
        mid = _id()
        self._exec(
            "INSERT INTO members (id, name, color, created) VALUES (?,?,?,?)",
            (mid, name.strip(), color, _now()),
        )
        return {"id": mid, "name": name.strip(), "color": color}

    def list_members(self) -> list:
        return [dict(r) for r in self._db.execute("SELECT * FROM members ORDER BY created")]

    def add_membership(self, project_id: str, member_id: str, role: str = "member"):
        self._exec(
            "INSERT OR REPLACE INTO memberships (project_id, member_id, role) VALUES (?,?,?)",
            (project_id, member_id, role),
        )

    # ---------- sessions ----------
    def create_session(self, project_id: str, member_id: str) -> str:
        sid = _id()
        self._exec(
            "INSERT INTO sessions (id, created, updated, project_id, member_id) VALUES (?,?,?,?,?)",
            (sid, _now(), _now(), project_id, member_id),
        )
        return sid

    def session_meta(self, sid: str) -> dict | None:
        r = self._db.execute(
            """SELECT id, created, updated, title, progress, project_id, member_id,
                      tokens_in, tokens_out, cost, priced FROM sessions WHERE id=?""",
            (sid,),
        ).fetchone()
        return dict(r) if r else None

    def exists(self, sid: str) -> bool:
        return self.session_meta(sid) is not None

    def list_sessions(self, project_id: str, limit: int = 30) -> list:
        rows = self._db.execute(
            """SELECT s.id, s.created, s.updated, s.title, s.progress, s.member_id,
                      s.cost, m.name AS member_name, m.color AS member_color
               FROM sessions s LEFT JOIN members m ON m.id=s.member_id
               WHERE s.project_id=? ORDER BY s.updated DESC LIMIT ?""",
            (project_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_messages(self, sid: str) -> list:
        r = self._db.execute("SELECT messages FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(r[0]) if r else []

    def save_messages(self, sid: str, messages: list):
        self._exec(
            "UPDATE sessions SET messages=?, updated=? WHERE id=?",
            (json.dumps(messages), _now(), sid),
        )

    def set_title(self, sid: str, title: str):
        self._exec("UPDATE sessions SET title=? WHERE id=? AND title=''", (title[:80], sid))

    def set_progress(self, sid: str, progress: str):
        self._exec(
            "UPDATE sessions SET progress=?, updated=? WHERE id=?",
            (progress[:600], _now(), sid),
        )

    def add_usage(self, sid: str, usd: float, priced: bool, usage: dict):
        self._exec(
            """UPDATE sessions SET cost=cost+?, tokens_in=tokens_in+?,
               tokens_out=tokens_out+?, priced=priced & ?, updated=? WHERE id=?""",
            (
                usd,
                (usage or {}).get("prompt_tokens", 0),
                (usage or {}).get("completion_tokens", 0),
                1 if priced else 0,
                _now(),
                sid,
            ),
        )

    def get_cost(self, sid: str) -> dict:
        r = self._db.execute(
            "SELECT cost, tokens_in, tokens_out, priced FROM sessions WHERE id=?", (sid,)
        ).fetchone()
        if not r:
            return {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "priced": True}
        return {
            "cost": r[0], "tokens_in": r[1], "tokens_out": r[2], "priced": bool(r[3]),
        }

    # ---------- runs ----------
    def create_run(self, project_id, session_id, parent_run_id, kind, label) -> str:
        rid = _id()
        self._exec(
            """INSERT INTO runs (id, project_id, session_id, parent_run_id, kind,
               label, status, started) VALUES (?,?,?,?,?,?,?,?)""",
            (rid, project_id, session_id, parent_run_id, kind, label[:160], "running", _now()),
        )
        return rid

    def finish_run(self, rid: str, status: str, result: str = ""):
        self._exec(
            "UPDATE runs SET status=?, finished=?, result=? WHERE id=?",
            (status, _now(), result[:2000], rid),
        )

    def add_run_cost(self, rid: str, usd: float):
        self._exec("UPDATE runs SET cost=cost+? WHERE id=?", (usd, rid))

    def get_run(self, rid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def run_status_line(self, rid: str) -> dict | None:
        r = self.get_run(rid)
        if not r:
            return None
        return {k: r[k] for k in ("id", "kind", "label", "status", "started", "finished", "cost", "result")}

    def list_runs(self, project_id: str, limit: int = 60) -> list:
        rows = self._db.execute(
            "SELECT * FROM runs WHERE project_id=? ORDER BY started DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def active_runs(self, project_id: str) -> list:
        rows = self._db.execute(
            "SELECT * FROM runs WHERE project_id=? AND status='running' ORDER BY started",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_run_event(self, rid: str, ev_type: str, payload: dict):
        with self._lock:
            n = self._db.execute(
                "SELECT COUNT(*) FROM run_events WHERE run_id=?", (rid,)
            ).fetchone()[0]
            if n >= MAX_RUN_EVENTS:
                return
            self._db.execute(
                "INSERT INTO run_events (run_id, ts, type, payload) VALUES (?,?,?,?)",
                (rid, _now(), ev_type, json.dumps(payload)[:4000]),
            )
            self._db.commit()

    def run_events(self, rid: str) -> list:
        rows = self._db.execute(
            "SELECT ts, type, payload FROM run_events WHERE run_id=? ORDER BY id", (rid,)
        ).fetchall()
        return [
            {"ts": r[0], "type": r[1], "payload": json.loads(r[2])} for r in rows
        ]

    # ---------- checkpoints ----------
    def create_checkpoint(self, session_id, project_id, member_id, label, progress,
                          messages, files: dict, auto: bool) -> str:
        cid = _id()
        self._exec(
            """INSERT INTO checkpoints (id, session_id, project_id, member_id, ts,
               label, progress, messages, files, auto) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, session_id, project_id, member_id, _now(), label[:120], progress[:600],
             json.dumps(messages), json.dumps(files), 1 if auto else 0),
        )
        return cid

    def list_checkpoints(self, project_id: str, session_id: str | None = None) -> list:
        q = """SELECT c.id, c.session_id, c.ts, c.label, c.progress, c.auto, c.member_id,
                      m.name AS member_name, s.title AS session_title
               FROM checkpoints c LEFT JOIN members m ON m.id=c.member_id
               LEFT JOIN sessions s ON s.id=c.session_id WHERE c.project_id=?"""
        params: list = [project_id]
        if session_id:
            q += " AND c.session_id=?"
            params.append(session_id)
        q += " ORDER BY c.ts DESC LIMIT 60"
        return [dict(r) for r in self._db.execute(q, params)]

    def get_checkpoint(self, cid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM checkpoints WHERE id=?", (cid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["messages"] = json.loads(d["messages"])
        d["files"] = json.loads(d["files"])
        return d

    def total_cost(self) -> float:
        r = self._db.execute("SELECT COALESCE(SUM(cost),0) FROM sessions").fetchone()
        return r[0] or 0.0
