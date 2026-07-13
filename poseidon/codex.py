"""ChatGPT-subscription (Codex OAuth) provider for Poseidon.

Lets a user sign in with their ChatGPT Plus/Pro account (browser device code,
no API key) and use it as a model provider. The subscription token only works
against https://chatgpt.com/backend-api/codex using OpenAI's Responses API, so
this module is a second request pipeline alongside the OpenAI-compatible one.

Reverse-engineered from a working Hermes install — see docs/CODEX-OAUTH-PLAN.md.
Auth is OpenAI's own device flow (NOT RFC 8628). v1 handles text + tool calls;
images/reasoning-replay are intentionally out of scope. Needs a live login to
validate end-to-end.
"""
import base64
import json
import time
import uuid
from pathlib import Path

import httpx

from .config import CONFIG_DIR

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
TOKEN_URL = f"{ISSUER}/oauth/token"
USERCODE_URL = f"{ISSUER}/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = f"{ISSUER}/api/accounts/deviceauth/token"
VERIFY_URL = f"{ISSUER}/codex/device"
BACKEND = "https://chatgpt.com/backend-api/codex"
RESPONSES_URL = f"{BACKEND}/responses"

AUTH_PATH = CONFIG_DIR / "codex_auth.json"
CODEX_CLI_AUTH = Path.home() / ".codex" / "auth.json"
EXPIRY_SKEW = 120  # refresh this many seconds before expiry


# ---------- jwt (read-only claim decode, no verification) ----------
def _jwt_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _account_id_from_id_token(id_token: str) -> str:
    c = _jwt_claims(id_token)
    auth = c.get("https://api.openai.com/auth") or {}
    return (auth.get("chatgpt_account_id") or c.get("chatgpt_account_id")
            or auth.get("account_id") or c.get("account_id") or "")


def _access_token_expiring(access_token: str) -> bool:
    exp = _jwt_claims(access_token).get("exp")
    if not isinstance(exp, (int, float)):
        return True  # unknown → refresh to be safe
    return time.time() >= (exp - EXPIRY_SKEW)


# ---------- token store ----------
def load_tokens() -> dict | None:
    if AUTH_PATH.exists():
        try:
            return json.loads(AUTH_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_tokens(tokens: dict) -> None:
    AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_PATH.write_text(json.dumps(tokens, indent=2))
    try:
        AUTH_PATH.chmod(0o600)
    except OSError:
        pass


def _store(access_token, refresh_token, id_token) -> dict:
    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "account_id": _account_id_from_id_token(id_token),
        "saved_at": time.time(),
    }
    _save_tokens(tokens)
    return tokens


def is_linked() -> bool:
    t = load_tokens()
    return bool(t and t.get("access_token"))


def status() -> dict:
    t = load_tokens()
    if not t or not t.get("access_token"):
        return {"linked": False}
    return {"linked": True, "account_id": t.get("account_id", ""),
            "expiring": _access_token_expiring(t["access_token"])}


def logout() -> None:
    if AUTH_PATH.exists():
        AUTH_PATH.unlink()


# ---------- device-code login (server drives this: start, then poll) ----------
async def device_start() -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(USERCODE_URL, json={"client_id": CLIENT_ID})
    r.raise_for_status()
    d = r.json()
    if not d.get("user_code") or not d.get("device_auth_id"):
        raise RuntimeError("device code request incomplete")
    return {
        "user_code": d["user_code"],
        "device_auth_id": d["device_auth_id"],
        "interval": max(3, int(d.get("interval", 5))),
        "verify_url": VERIFY_URL,
    }


async def device_poll(device_auth_id: str, user_code: str) -> dict:
    """One poll. Returns {'status': 'pending'|'authorized', ...}."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(DEVICE_TOKEN_URL,
                         json={"device_auth_id": device_auth_id, "user_code": user_code})
    if r.status_code in (202, 428) or (r.status_code == 400 and "pending" in r.text.lower()):
        return {"status": "pending"}
    r.raise_for_status()
    d = r.json()
    if not d.get("access_token"):
        return {"status": "pending"}
    _store(d["access_token"], d.get("refresh_token", ""), d.get("id_token", ""))
    return {"status": "authorized", "account_id": _account_id_from_id_token(d.get("id_token", ""))}


def import_codex_cli() -> bool:
    """Reuse an existing `codex login` from ~/.codex/auth.json, if present."""
    if not CODEX_CLI_AUTH.exists():
        return False
    try:
        d = json.loads(CODEX_CLI_AUTH.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    tok = d.get("tokens") or d
    at = tok.get("access_token")
    if not at:
        return False
    _store(at, tok.get("refresh_token", ""), tok.get("id_token", ""))
    return True


async def _refresh(tokens: dict) -> dict:
    rt = tokens.get("refresh_token")
    if not rt:
        raise RuntimeError("codex: no refresh token — sign in again")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, json={
            "grant_type": "refresh_token", "refresh_token": rt, "client_id": CLIENT_ID})
    if r.status_code >= 400:
        raise RuntimeError(f"codex refresh failed ({r.status_code}) — sign in again")
    d = r.json()
    return _store(d["access_token"], d.get("refresh_token", rt),
                  d.get("id_token", tokens.get("id_token", "")))


async def _valid_tokens() -> dict:
    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError("codex: not signed in")
    if _access_token_expiring(tokens["access_token"]):
        tokens = await _refresh(tokens)
    return tokens


# ---------- chat-completions <-> Responses translation ----------
def _to_responses(messages: list) -> tuple[str, list]:
    """Return (instructions, input_items). System messages become instructions."""
    instructions, items = [], []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if isinstance(m.get("content"), str):
                instructions.append(m["content"])
            continue
        if role == "tool":
            items.append({"type": "function_call_output",
                          "call_id": m.get("tool_call_id", ""),
                          "output": m.get("content", "")})
            continue
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                items.append({"type": "function_call", "call_id": tc.get("id", ""),
                              "name": fn.get("name", ""), "arguments": fn.get("arguments", "")})
            if m.get("content"):
                items.append({"type": "message", "role": "assistant",
                              "content": [{"type": "output_text", "text": m["content"]}]})
            continue
        text = m.get("content")
        if isinstance(text, str) and text:
            tt = "output_text" if role == "assistant" else "input_text"
            items.append({"type": "message", "role": role,
                          "content": [{"type": tt, "text": text}]})
    return "\n\n".join(instructions), items


def _responses_tools(tools: list | None) -> list | None:
    if not tools:
        return None
    out = []
    for t in tools:
        fn = t.get("function", {})
        out.append({"type": "function", "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {})})
    return out


def _headers(tokens: dict) -> dict:
    return {
        "Authorization": f"Bearer {tokens['access_token']}",
        "chatgpt-account-id": tokens.get("account_id", ""),
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "session_id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }


async def responses_request(model: str, messages: list, tools: list | None,
                            on_delta=None) -> dict:
    """Make a Codex Responses call, return the OpenAI chat-completions shape
    {choices:[{message}], usage} so the orchestrator loop is unchanged."""
    tokens = await _valid_tokens()
    instructions, items = _to_responses(messages)
    body = {"model": model, "instructions": instructions, "input": items, "stream": True}
    rtools = _responses_tools(tools)
    if rtools:
        body["tools"] = rtools
        body["tool_choice"] = "auto"

    content, tool_calls, usage = "", {}, None
    async with httpx.AsyncClient(timeout=300) as c:
        async with c.stream("POST", RESPONSES_URL, json=body, headers=_headers(tokens)) as r:
            if r.status_code >= 400:
                text = (await r.aread()).decode(errors="replace")[:400]
                raise RuntimeError(f"codex responses {r.status_code}: {text}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                etype = ev.get("type", "")
                if etype == "response.output_text.delta":
                    piece = ev.get("delta", "")
                    content += piece
                    if on_delta and piece:
                        await on_delta(piece)
                elif etype == "response.output_item.added" and ev.get("item", {}).get("type") == "function_call":
                    it = ev["item"]
                    tool_calls[it.get("id", it.get("call_id", ""))] = {
                        "id": it.get("call_id", it.get("id", "")), "type": "function",
                        "function": {"name": it.get("name", ""), "arguments": ""}}
                elif etype == "response.function_call_arguments.delta":
                    tc = _find_tc(tool_calls, ev.get("item_id"))
                    if tc:
                        tc["function"]["arguments"] += ev.get("delta", "")
                elif etype == "response.completed":
                    u = ev.get("response", {}).get("usage")
                    if u:
                        usage = {"prompt_tokens": u.get("input_tokens", 0),
                                 "completion_tokens": u.get("output_tokens", 0)}
    msg = {"role": "assistant", "content": content or None}
    calls = list(tool_calls.values())
    if calls:
        msg["tool_calls"] = calls
    return {"choices": [{"message": msg}], "usage": usage}


def _find_tc(tool_calls: dict, item_id):
    if item_id in tool_calls:
        return tool_calls[item_id]
    return next(iter(tool_calls.values()), None) if tool_calls else None
