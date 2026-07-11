"""Local FastAPI server: projects/members, sessions, chat, runs, checkpoints,
schedules, memory, settings, SSE. Binds 127.0.0.1 only; rejects non-localhost
Host headers (DNS-rebinding guard).
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import memory as memory_store
from .approvals import ApprovalBroker
from .config import CONFIG_DIR, PRESETS, load_config, save_config
from .orchestrator import engine_settings, run_turn
from .runs import RunManager
from .scheduler import Scheduler
from .store import Store
from .tools.files import resolve_path

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def create_app(workdir: Path) -> FastAPI:
    app = FastAPI(title="Poseidon", version=__version__)
    store = Store(CONFIG_DIR / "sessions.db", workdir)
    runmgr = RunManager(store)
    broker = ApprovalBroker()
    busy: set[str] = set()

    def project_or_404(pid: str) -> dict:
        p = store.get_project(pid)
        if not p:
            raise HTTPException(404, "unknown project")
        return p

    async def scheduled_runner(project_id: str, prompt: str):
        project = store.get_project(project_id) or store.get_project("default")
        sid = store.create_session(project["id"], "scheduler")
        await run_turn(project, store, runmgr, broker, scheduler, sid, "scheduler",
                       f"[scheduled run] {prompt}", kind="scheduled", unattended=True)
        msgs = store.get_messages(sid)
        text = next((m.get("content") for m in reversed(msgs)
                     if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")), "")
        return sid, text

    scheduler = Scheduler(CONFIG_DIR / "sessions.db", scheduled_runner)

    @app.on_event("startup")
    async def _start_scheduler():
        runmgr.spawn(scheduler.loop())

    @app.middleware("http")
    async def localhost_only(request: Request, call_next):
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return await call_next(request)

    @app.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ---------- state & settings ----------
    @app.get("/api/state")
    async def state():
        cfg = load_config()
        provider = cfg.get("provider")
        return {
            "version": __version__,
            "workdir": str(workdir),
            "configured": bool(provider and provider.get("base_url")),
            "provider": ({"base_url": provider.get("base_url", ""), "model": provider.get("model", ""),
                          "has_key": bool(provider.get("api_key"))} if provider else None),
            "presets": {k: {kk: vv for kk, vv in v.items() if kk != "api_key"} for k, v in PRESETS.items()},
            "approval_rules": cfg.get("approvals", {}).get("rules", []),
            "engine": engine_settings(),
            "projects": store.list_projects(),
            "members": store.list_members(),
            "total_cost": store.total_cost(),
        }

    @app.post("/api/config")
    async def set_provider(body: dict):
        base_url = (body.get("base_url") or "").strip()
        model = (body.get("model") or "").strip()
        if not base_url or not model:
            raise HTTPException(422, "base_url and model are required")
        cfg = load_config()
        cfg["provider"] = {"base_url": base_url, "api_key": (body.get("api_key") or "").strip(), "model": model}
        save_config(cfg)
        return {"ok": True}

    @app.post("/api/settings/engine")
    async def set_engine(body: dict):
        cfg = load_config()
        eng = cfg.setdefault("engine", {})
        for key, lo, hi in [("compact_tokens", 4000, 200000), ("keep_recent", 2, 40),
                            ("max_iterations", 5, 60)]:
            if key in body:
                eng[key] = max(lo, min(hi, int(body[key])))
        if "auto_checkpoint" in body:
            eng["auto_checkpoint"] = bool(body["auto_checkpoint"])
        save_config(cfg)
        return {"ok": True, "engine": engine_settings()}

    @app.delete("/api/settings/rules/{idx}")
    async def delete_rule(idx: int):
        cfg = load_config()
        rules = cfg.get("approvals", {}).get("rules", [])
        if not (0 <= idx < len(rules)):
            raise HTTPException(404, "no such rule")
        rules.pop(idx)
        save_config(cfg)
        return {"ok": True, "rules": rules}

    # ---------- projects & members ----------
    @app.post("/api/projects")
    async def create_project(body: dict):
        name = (body.get("name") or "").strip()
        wd = (body.get("workdir") or "").strip()
        member_id = body.get("member_id") or "owner"
        if not name:
            raise HTTPException(422, "name required")
        path = Path(wd).expanduser() if wd else workdir
        if not path.is_dir():
            raise HTTPException(422, f"not a directory: {path}")
        return store.create_project(name, str(path.resolve()), member_id)

    @app.post("/api/members")
    async def create_member(body: dict):
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "name required")
        color = body.get("color") or "#0f7fa8"
        try:
            m = store.create_member(name, color)
        except Exception:
            raise HTTPException(409, "member name already exists")
        for p in store.list_projects():
            store.add_membership(p["id"], m["id"])
        return m

    @app.post("/api/projects/{pid}/members")
    async def add_member(pid: str, body: dict):
        project_or_404(pid)
        store.add_membership(pid, body.get("member_id", ""), body.get("role", "member"))
        return {"ok": True}

    @app.get("/api/projects/{pid}/status")
    async def project_status(pid: str):
        project_or_404(pid)
        return {
            "sessions": store.list_sessions(pid, limit=10),
            "active_runs": store.active_runs(pid),
            "schedules": scheduler.list(pid),
        }

    # ---------- sessions ----------
    @app.get("/api/sessions")
    async def list_sessions(project_id: str = "default"):
        return {"sessions": store.list_sessions(project_id)}

    @app.post("/api/sessions")
    async def create_session(body: dict):
        pid = body.get("project_id", "default")
        project_or_404(pid)
        return {"session_id": store.create_session(pid, body.get("member_id", "owner"))}

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str):
        meta = store.session_meta(sid)
        if not meta:
            raise HTTPException(404, "unknown session")
        msgs = [m for m in store.get_messages(sid)
                if isinstance(m, dict) and (
                    (m.get("role") == "user" and isinstance(m.get("content"), str) and not m["content"].startswith("[scheduled run]"))
                    or (m.get("role") == "assistant" and m.get("content")))]
        return {**meta, "messages": [{"role": m["role"], "content": m["content"]} for m in msgs]}

    # ---------- chat ----------
    @app.post("/api/chat")
    async def chat(body: dict):
        sid = body.get("session_id")
        message = (body.get("message") or "").strip()
        meta = store.session_meta(sid) if sid else None
        if not meta:
            raise HTTPException(404, "unknown session")
        if not message:
            raise HTTPException(422, "empty message")
        if sid in busy:
            raise HTTPException(409, "a turn is already running in this session")
        project = project_or_404(meta["project_id"])
        member_id = body.get("member_id") or meta["member_id"] or "owner"
        busy.add(sid)

        async def run():
            try:
                await run_turn(project, store, runmgr, broker, scheduler, sid, member_id, message)
            finally:
                busy.discard(sid)

        runmgr.spawn(run())
        return {"ok": True}

    # ---------- events (SSE) ----------
    @app.get("/api/events")
    async def events(session_id: str = "", project_id: str = ""):
        keys = [k for k in (f"s:{session_id}" if session_id else "", f"p:{project_id}" if project_id else "") if k]
        if not keys:
            raise HTTPException(422, "session_id or project_id required")
        q = runmgr.subscribe(keys)

        async def gen():
            try:
                yield 'data: {"type":"connected"}\n\n'
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                        yield f"data: {json.dumps(ev)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                runmgr.unsubscribe(keys, q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---------- approvals ----------
    @app.post("/api/approvals/{aid}")
    async def approve(aid: str, body: dict):
        if not broker.resolve(aid, bool(body.get("approved")), bool(body.get("always"))):
            raise HTTPException(404, "no pending approval with that id")
        return {"ok": True}

    # ---------- runs ----------
    @app.get("/api/runs")
    async def list_runs(project_id: str = "default"):
        return {"runs": store.list_runs(project_id)}

    @app.get("/api/runs/{rid}")
    async def get_run(rid: str):
        run = store.get_run(rid)
        if not run:
            raise HTTPException(404, "unknown run")
        return {**run, "events": store.run_events(rid)}

    # ---------- checkpoints ----------
    @app.get("/api/checkpoints")
    async def list_checkpoints(project_id: str = "default", session_id: str = ""):
        return {"checkpoints": store.list_checkpoints(project_id, session_id or None)}

    @app.get("/api/checkpoints/{cid}")
    async def get_checkpoint(cid: str):
        c = store.get_checkpoint(cid)
        if not c:
            raise HTTPException(404, "unknown checkpoint")
        c["message_count"] = len(c["messages"])
        c["files"] = {k: v[:4000] for k, v in c["files"].items()}
        del c["messages"]
        return c

    @app.post("/api/checkpoints/{cid}/restore")
    async def restore_checkpoint(cid: str):
        c = store.get_checkpoint(cid)
        if not c:
            raise HTTPException(404, "unknown checkpoint")
        if c["session_id"] in busy:
            raise HTTPException(409, "session is busy")
        store.save_messages(c["session_id"], c["messages"])
        store.set_progress(c["session_id"], f"[restored checkpoint: {c['label']}] {c['progress']}")
        return {"ok": True, "session_id": c["session_id"]}

    # ---------- schedules ----------
    @app.get("/api/schedules")
    async def get_schedules(project_id: str = "default"):
        return {"schedules": scheduler.list(project_id)}

    @app.delete("/api/schedules/{sid}")
    async def delete_schedule(sid: str):
        if not scheduler.cancel(sid):
            raise HTTPException(404, "no schedule with that id")
        return {"ok": True}

    # ---------- memory ----------
    @app.get("/api/memory")
    async def get_memory(project_id: str = "default"):
        return {"entries": memory_store.list_entries(project_id)}

    # ---------- files ----------
    def _project_workdir(project_id: str) -> Path:
        return Path(project_or_404(project_id)["workdir"])

    @app.get("/api/files")
    async def list_files(path: str = ".", project_id: str = "default"):
        wd = _project_workdir(project_id)
        try:
            target = resolve_path(wd, path)
        except ValueError as e:
            raise HTTPException(403, str(e))
        if not target.is_dir():
            raise HTTPException(404, "not a directory")
        entries = [
            {"name": c.name, "dir": c.is_dir(), "size": c.stat().st_size if c.is_file() else None}
            for c in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
            if not c.name.startswith(".")
        ]
        rel = str(target.relative_to(wd))
        return {"path": "." if rel == "." else rel, "entries": entries[:1000]}

    @app.get("/api/file")
    async def get_file(path: str, project_id: str = "default"):
        wd = _project_workdir(project_id)
        try:
            target = resolve_path(wd, path)
        except ValueError as e:
            raise HTTPException(403, str(e))
        if not target.is_file():
            raise HTTPException(404, "not a file")
        return {"content": target.read_text(errors="replace")[:200_000]}

    return app
