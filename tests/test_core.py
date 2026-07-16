"""Pre-launch core tests: the path jail, the approval broker (trust dial),
always-allow pattern derivation, config migration, and the compact threshold.

Everything that reads/writes config is pointed at a temp dir — the real
~/.poseidon is never touched.
"""

import asyncio
import json
from pathlib import Path

import pytest

from poseidon import config as config_mod
from poseidon.approvals import ApprovalBroker, derive_pattern
from poseidon.tools.files import resolve_path


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """Isolated config file; returns a writer for seeding state."""
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)

    def write(data):
        path.write_text(json.dumps(data))

    return write


# ── path jail ──────────────────────────────────────────────────────

def test_jail_allows_inside(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert resolve_path(tmp_path, "a.txt") == (tmp_path / "a.txt").resolve()
    assert resolve_path(tmp_path, "sub/../a.txt") == (tmp_path / "a.txt").resolve()


def test_jail_blocks_escape(tmp_path):
    with pytest.raises(ValueError):
        resolve_path(tmp_path, "../outside.txt")
    with pytest.raises(ValueError):
        resolve_path(tmp_path, "/etc/passwd")
    with pytest.raises(ValueError):
        resolve_path(tmp_path, "sub/../../outside.txt")


# ── approval broker (the trust dial) ───────────────────────────────

def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_broker_asks_then_always_allow_persists(cfg):
    cfg({})
    broker = ApprovalBroker()
    emitted = []

    async def emit(ev):
        emitted.append(ev)

    async def flow():
        task = asyncio.create_task(
            broker.request(emit, "run_command", "git push", "git push"))
        await asyncio.sleep(0.01)  # let the request emit its card
        assert emitted and emitted[0]["type"] == "approval_required"
        assert broker.resolve(emitted[0]["id"], approved=True, always=True)
        return await task

    result = _run(flow())
    assert result["approved"] and result["always"]
    # the rule persisted: "git push" generalized to "git *"
    rules = config_mod.load_config()["approvals"]["rules"]
    assert {"tool": "run_command", "pattern": "git *"} in rules
    # and a second matching request auto-approves without asking
    result2 = _run(broker.request(emit, "run_command", "git pull", "git pull"))
    assert result2 == {"approved": True, "always": False, "auto": True}


def test_broker_unattended_denies_without_rule(cfg):
    cfg({})
    broker = ApprovalBroker()

    async def emit(ev):
        raise AssertionError("unattended runs must never emit approval cards")

    result = _run(broker.request(emit, "write_file", "x.txt", "", unattended=True))
    assert result["approved"] is False and result.get("unattended")


def test_broker_balanced_mode_auto_approves_edits(cfg):
    cfg({"approvals": {"mode": "balanced", "rules": []}})
    broker = ApprovalBroker()

    async def emit(ev):
        raise AssertionError("balanced mode should not ask for file edits")

    result = _run(broker.request(emit, "write_file", "notes.md", ""))
    assert result["approved"] and result["auto"]
    # outward sends still ask even in autonomous mode
    cfg({"approvals": {"mode": "autonomous", "rules": []}})
    asked = []

    async def emit2(ev):
        asked.append(ev)

    async def flow():
        task = asyncio.create_task(
            broker.request(emit2, "send_email", "jo@acme.com", "hi"))
        await asyncio.sleep(0.01)
        assert asked, "outward sends must ask"
        broker.resolve(asked[0]["id"], approved=False, always=False)
        return await task

    assert _run(flow())["approved"] is False


def test_derive_pattern_shapes():
    assert derive_pattern("run_command", "git push origin main") == "git *"
    assert derive_pattern("run_command", "ls") == "ls"
    assert derive_pattern("write_file", "src/app/main.py") == "src/app/*"
    assert derive_pattern("send_email", "jo@acme.com") == "jo@acme.com"


# ── config migration + compact threshold ───────────────────────────

def test_old_default_compact_tokens_migrates(cfg):
    cfg({"engine": {"compact_tokens": 24000}})
    assert config_mod.load_config()["engine"]["compact_tokens"] == 198000


def test_custom_compact_tokens_survives(cfg):
    cfg({"engine": {"compact_tokens": 120000}})
    assert config_mod.load_config()["engine"]["compact_tokens"] == 120000


def test_compact_threshold_respects_context_window(cfg):
    from poseidon.orchestrator import compact_threshold

    cfg({"provider": {"base_url": "x", "model": "m", "context_window": 131072}})
    assert compact_threshold({"compact_tokens": 198000}) == 129072
    cfg({"provider": {"base_url": "x", "model": "m"}})  # no window -> 200k default
    assert compact_threshold({"compact_tokens": 198000}) == 198000
