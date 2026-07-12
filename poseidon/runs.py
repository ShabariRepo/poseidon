"""RunManager: run lifecycle + the event bus.

Channels: every event is published to its session channel (chat view) AND its
project channel (pipeline view), and persisted as a RunEvent for drill-down.
"""
import asyncio


class RunManager:
    def __init__(self, store):
        self.store = store
        self._channels: dict[str, set[asyncio.Queue]] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---- event bus ----
    def subscribe(self, keys: list[str]) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for k in keys:
            self._channels.setdefault(k, set()).add(q)
        return q

    def unsubscribe(self, keys: list[str], q: asyncio.Queue):
        for k in keys:
            self._channels.get(k, set()).discard(q)

    def publish(self, ev: dict):
        seen = set()
        for key in (f"s:{ev.get('session_id')}", f"p:{ev.get('project_id')}"):
            for q in self._channels.get(key, set()):
                if id(q) not in seen:
                    q.put_nowait(ev)
                    seen.add(id(q))

    def emitter(self, project_id: str, session_id: str | None, run_id: str | None):
        """Returns an async emit(ev) bound to a run context."""
        async def emit(ev: dict):
            ev = {**ev, "project_id": project_id, "session_id": session_id, "run_id": run_id}
            self.publish(ev)
            if run_id and ev.get("type") not in ("cost_update", "assistant_delta"):
                payload = {k: v for k, v in ev.items()
                           if k not in ("project_id", "session_id", "run_id")}
                self.store.add_run_event(run_id, ev["type"], payload)
        return emit

    # ---- run lifecycle ----
    def start(self, project_id, session_id, parent_run_id, kind, label) -> str:
        rid = self.store.create_run(project_id, session_id, parent_run_id, kind, label)
        self.publish({
            "type": "run_started", "project_id": project_id, "session_id": session_id,
            "run_id": rid, "kind": kind, "label": label, "parent_run_id": parent_run_id,
        })
        return rid

    def finish(self, project_id, session_id, rid, status, result=""):
        self.store.finish_run(rid, status, result)
        self.publish({
            "type": "run_finished", "project_id": project_id, "session_id": session_id,
            "run_id": rid, "status": status,
        })

    # ---- detached work (background tasks, scheduled fires) ----
    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
