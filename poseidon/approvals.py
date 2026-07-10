"""The trust dial. Writes and commands pause the turn and ask in chat;
"always allow" saves a pattern rule so trust accumulates over time.
"""
import asyncio
import fnmatch
import uuid
from pathlib import PurePath

from .config import load_config, save_config

APPROVAL_TIMEOUT_SECS = 600


def derive_pattern(tool: str, subject: str) -> str:
    """What 'always allow' generalizes to: same command word, or same directory."""
    if tool == "run_command":
        head = subject.split()[0] if subject.split() else subject
        return f"{head} *" if " " in subject else head
    return str(PurePath(subject).parent / "*")


class ApprovalBroker:
    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}

    def _rule_allows(self, tool: str, subject: str) -> bool:
        rules = load_config().get("approvals", {}).get("rules", [])
        return any(
            r.get("tool") == tool and fnmatch.fnmatch(subject, r.get("pattern", ""))
            for r in rules
        )

    async def request(self, emit, tool: str, subject: str, detail: str) -> dict:
        """Returns {"approved": bool, "always": bool, "auto": bool}."""
        if self._rule_allows(tool, subject):
            return {"approved": True, "always": False, "auto": True}

        aid = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[aid] = fut
        await emit(
            {
                "type": "approval_required",
                "id": aid,
                "tool": tool,
                "subject": subject,
                "detail": detail[:4000],
            }
        )
        try:
            result = await asyncio.wait_for(fut, timeout=APPROVAL_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            result = {"approved": False, "always": False, "timeout": True}
        finally:
            self._pending.pop(aid, None)

        if result.get("approved") and result.get("always"):
            cfg = load_config()
            cfg.setdefault("approvals", {}).setdefault("rules", []).append(
                {"tool": tool, "pattern": derive_pattern(tool, subject)}
            )
            save_config(cfg)
        result["auto"] = False
        return result

    def resolve(self, aid: str, approved: bool, always: bool) -> bool:
        fut = self._pending.get(aid)
        if fut and not fut.done():
            fut.set_result({"approved": approved, "always": always})
            return True
        return False
