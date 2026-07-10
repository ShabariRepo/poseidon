"""The agent loop: OpenAI-compatible chat completions with tools, run until
no more tool calls. Every tool result carries its tool_call_id — orphaned
results make upstreams return empty completions.
"""
import json
from pathlib import Path

import httpx

from .config import load_config
from .costs import compute_cost
from .tools import TOOLS, tool_schemas

MAX_ITERATIONS = 25
MAX_TOOL_RESULT = 12_000

SYSTEM_PROMPT = """You are Poseidon, an AI agent working on the user's machine in {workdir}.
Be warm, direct, and first-person. Say briefly what you're about to do, then use tools to do it.
Reads are instant; file writes and shell commands ask the user for approval — that's normal, don't apologize for it.
When you finish, summarize what changed in plain language."""


async def _chat_completion(provider: dict, messages: list, tools: list) -> dict:
    headers = {}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    body = {
        "model": provider["model"],
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            provider["base_url"].rstrip("/") + "/chat/completions",
            json=body,
            headers=headers,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"provider returned {r.status_code}: {r.text[:500]}")
    return r.json()


def _build_system_prompt(workdir: Path) -> str:
    prompt = SYSTEM_PROMPT.format(workdir=workdir)
    agents_md = workdir / "AGENTS.md"
    if agents_md.is_file():
        prompt += "\n\nProject instructions (AGENTS.md):\n" + agents_md.read_text(
            errors="replace"
        )[:6000]
    return prompt


async def run_turn(workdir, store, session_id, user_message, emit, broker):
    cfg = load_config()
    provider = cfg.get("provider")
    if not provider or not provider.get("base_url"):
        await emit({"type": "error", "message": "No provider configured — open Settings."})
        return

    ctx = {"workdir": workdir}
    messages = store.get_messages(session_id)
    if not messages:
        messages.append({"role": "system", "content": _build_system_prompt(workdir)})
    messages.append({"role": "user", "content": user_message})
    await emit({"type": "turn_started"})

    try:
        for _ in range(MAX_ITERATIONS):
            data = await _chat_completion(provider, messages, tool_schemas())
            usd, priced = compute_cost(provider["model"], data.get("usage"))
            store.add_usage(session_id, usd, priced, data.get("usage"))
            await emit({"type": "cost_update", **store.get_cost(session_id)})

            msg = data["choices"][0]["message"]
            messages.append(msg)
            if msg.get("content"):
                await emit({"type": "assistant_message", "content": msg["content"]})

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                break

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                await emit({"type": "tool_call", "name": name, "args": args})
                result = await _execute_tool(name, args, ctx, emit, broker)
                await emit(
                    {
                        "type": "tool_result",
                        "name": name,
                        "ok": "error" not in result,
                        "summary": _summarize(result),
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result)[:MAX_TOOL_RESULT],
                    }
                )
        else:
            await emit({"type": "error", "message": f"Stopped after {MAX_ITERATIONS} steps."})
    except Exception as e:  # surface, don't swallow
        await emit({"type": "error", "message": str(e)[:800]})
    finally:
        store.save_messages(session_id, messages)
        await emit({"type": "turn_complete"})


async def _execute_tool(name, args, ctx, emit, broker) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"unknown tool: {name}"}
    if spec["needs_approval"]:
        subject, detail = spec["subject"](args)
        decision = await broker.request(emit, name, subject, detail)
        if not decision["approved"]:
            reason = "timed out" if decision.get("timeout") else "denied by user"
            return {"error": f"approval {reason}"}
    try:
        return await spec["handler"](args, ctx)
    except Exception as e:
        return {"error": str(e)[:500]}


def _summarize(result: dict) -> str:
    if "error" in result:
        return result["error"][:200]
    if "content" in result:
        return f"{len(result['content'])} chars"
    if "entries" in result:
        return f"{len(result['entries'])} entries"
    if "exit_code" in result:
        return f"exit {result['exit_code']}"
    return "ok"
