"""Local FastAPI server: chat API, SSE event stream, approvals, file browser.
Binds 127.0.0.1 only; rejects non-localhost Host headers (DNS-rebinding guard).
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .approvals import ApprovalBroker
from .config import CONFIG_DIR, PRESETS, load_config, save_config
from .orchestrator import run_turn
from .sessions import SessionStore
from .tools.files import resolve_path

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def create_app(workdir: Path) -> FastAPI:
    app = FastAPI(title="Poseidon", version=__version__)
    store = SessionStore(CONFIG_DIR / "sessions.db")
    broker = ApprovalBroker()
    queues: dict[str, set] = {}
    busy: set[str] = set()
    tasks: set = set()

    def emitter(session_id: str):
        async def emit(ev: dict):
            for q in queues.get(session_id, set()):
                q.put_nowait({**ev, "session_id": session_id})
        return emit

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

    @app.get("/api/state")
    async def state():
        cfg = load_config()
        provider = cfg.get("provider")
        return {
            "version": __version__,
            "workdir": str(workdir),
            "configured": bool(provider and provider.get("base_url")),
            "provider": {
                "base_url": provider.get("base_url", ""),
                "model": provider.get("model", ""),
                "has_key": bool(provider.get("api_key")),
            }
            if provider
            else None,
            "presets": {
                k: {kk: vv for kk, vv in v.items() if kk != "api_key"}
                for k, v in PRESETS.items()
            },
            "approval_rules": cfg.get("approvals", {}).get("rules", []),
            "total_cost": store.total_cost(),
        }

    @app.post("/api/config")
    async def set_config(body: dict):
        base_url = (body.get("base_url") or "").strip()
        model = (body.get("model") or "").strip()
        if not base_url or not model:
            raise HTTPException(422, "base_url and model are required")
        cfg = load_config()
        cfg["provider"] = {
            "base_url": base_url,
            "api_key": (body.get("api_key") or "").strip(),
            "model": model,
        }
        save_config(cfg)
        return {"ok": True}

    @app.post("/api/sessions")
    async def create_session():
        return {"session_id": store.create()}

    @app.get("/api/events")
    async def events(session_id: str):
        q: asyncio.Queue = asyncio.Queue()
        queues.setdefault(session_id, set()).add(q)

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
                queues.get(session_id, set()).discard(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/api/chat")
    async def chat(body: dict):
        sid = body.get("session_id")
        message = (body.get("message") or "").strip()
        if not sid or not store.exists(sid):
            raise HTTPException(404, "unknown session")
        if not message:
            raise HTTPException(422, "empty message")
        if sid in busy:
            raise HTTPException(409, "a turn is already running in this session")
        busy.add(sid)

        async def run():
            try:
                await run_turn(workdir, store, sid, message, emitter(sid), broker)
            finally:
                busy.discard(sid)

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"ok": True}

    @app.post("/api/approvals/{aid}")
    async def approve(aid: str, body: dict):
        ok = broker.resolve(aid, bool(body.get("approved")), bool(body.get("always")))
        if not ok:
            raise HTTPException(404, "no pending approval with that id")
        return {"ok": True}

    @app.get("/api/files")
    async def list_files(path: str = "."):
        try:
            target = resolve_path(workdir, path)
        except ValueError as e:
            raise HTTPException(403, str(e))
        if not target.is_dir():
            raise HTTPException(404, "not a directory")
        entries = [
            {
                "name": c.name,
                "dir": c.is_dir(),
                "size": c.stat().st_size if c.is_file() else None,
            }
            for c in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))
            if not c.name.startswith(".")
        ]
        rel = str(target.relative_to(workdir))
        return {"path": "." if rel == "." else rel, "entries": entries[:1000]}

    @app.get("/api/file")
    async def get_file(path: str):
        try:
            target = resolve_path(workdir, path)
        except ValueError as e:
            raise HTTPException(403, str(e))
        if not target.is_file():
            raise HTTPException(404, "not a file")
        return {"content": target.read_text(errors="replace")[:200_000]}

    return app
