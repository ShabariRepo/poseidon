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
import asyncio
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


# ---------- browser OAuth (authorization-code + PKCE) ----------
# What `codex login` itself does: open {ISSUER}/oauth/authorize in the
# browser, catch the redirect on a loopback listener (the client's registered
# ports), exchange the code. Needs NO account setting — unlike the device
# flow, which is an OpenAI beta that's off by default. This is the primary
# path; the device flow stays for headless/remote boxes.
AUTHORIZE_URL = f"{ISSUER}/oauth/authorize"
BROWSER_PORTS = (1455, 1457)  # registered loopback redirect ports
BROWSER_TIMEOUT = 600

_browser: dict = {"status": "idle"}  # one flow at a time


def browser_status() -> dict:
    return {"status": _browser.get("status", "idle"),
            "error": _browser.get("error", "")}


async def _browser_close():
    server = _browser.pop("server", None)
    if server:
        server.close()
        try:
            await server.wait_closed()
        except Exception:
            pass


async def browser_start() -> dict:
    import hashlib
    import secrets
    from urllib.parse import urlencode

    await _browser_close()  # drop any previous flow's listener
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

    server = None
    port = None
    for p in BROWSER_PORTS:
        try:
            server = await asyncio.start_server(_browser_callback, "127.0.0.1", p)
            port = p
            break
        except OSError:
            continue
    if server is None:
        raise RuntimeError(
            "ports 1455/1457 are in use (another ChatGPT sign-in running? Codex CLI?) — "
            "close it and retry, or use the device code")

    redirect_uri = f"http://localhost:{port}/auth/callback"
    _browser.clear()
    _browser.update({"status": "waiting", "error": "", "state": state,
                     "verifier": verifier, "redirect_uri": redirect_uri,
                     "server": server})

    async def _expire(expected_state: str):
        await asyncio.sleep(BROWSER_TIMEOUT)
        if _browser.get("state") == expected_state and _browser.get("status") == "waiting":
            _browser["status"] = "error"
            _browser["error"] = "sign-in timed out — try again"
            await _browser_close()

    asyncio.ensure_future(_expire(state))

    qs = urlencode({
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        # the scope set the Codex CLI itself requests for this client
        "scope": "openid profile email offline_access",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "state": state,
        "originator": "codex_cli_rs",
    })
    return {"auth_url": f"{AUTHORIZE_URL}?{qs}", "status": "waiting"}


async def _browser_respond(writer, status: int, message: str):
    body = (f"<!doctype html><meta charset='utf-8'><title>Poseidon</title>"
            f"<body style='font-family:system-ui;display:grid;place-items:center;height:90vh'>"
            f"<div style='text-align:center;max-width:28rem'><div style='font-size:2.4rem'>🔱</div>"
            f"<p>{message}</p></div></body>").encode()
    head = (f"HTTP/1.1 {status} {'OK' if status == 200 else 'Error'}\r\n"
            f"Content-Type: text/html; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n").encode()
    writer.write(head + body)
    try:
        await writer.drain()
    finally:
        writer.close()


async def _browser_callback(reader, writer):
    from urllib.parse import parse_qs, urlparse

    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
    except Exception:
        writer.close()
        return
    try:
        request_line = head.split(b"\r\n", 1)[0].decode(errors="replace")
        parts = request_line.split(" ")
        target = urlparse(parts[1] if len(parts) > 1 else "/")
        if target.path != "/auth/callback":
            await _browser_respond(writer, 404, "Not the sign-in callback.")
            return
        q = parse_qs(target.query)
        if q.get("state", [""])[0] != _browser.get("state"):
            await _browser_respond(
                writer, 400, "State mismatch — start the sign-in again from Poseidon.")
            return
        code = q.get("code", [""])[0]
        if not code:
            err = q.get("error_description", q.get("error", ["sign-in was cancelled"]))[0]
            _browser["status"] = "error"
            _browser["error"] = err
            await _browser_respond(writer, 400, f"Sign-in failed: {err}")
            await _browser_close()
            return
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(TOKEN_URL, data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _browser["redirect_uri"],
                "client_id": CLIENT_ID,
                "code_verifier": _browser["verifier"],
            })
        if r.status_code >= 400:
            _browser["status"] = "error"
            _browser["error"] = f"token exchange failed ({r.status_code})"
            await _browser_respond(
                writer, 502, "Token exchange failed — return to Poseidon and try again.")
            await _browser_close()
            return
        d = r.json()
        _store(d["access_token"], d.get("refresh_token", ""), d.get("id_token", ""))
        _browser["status"] = "authorized"
        await _browser_respond(
            writer, 200, "Signed in — you can close this tab and return to Poseidon.")
        await _browser_close()
    except Exception as e:  # never leave the tab hanging
        _browser["status"] = "error"
        _browser["error"] = str(e)[:200]
        try:
            await _browser_respond(writer, 500, "Something went wrong — return to Poseidon and try again.")
        except Exception:
            pass
        await _browser_close()


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
