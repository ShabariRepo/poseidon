"""The agent loop: OpenAI-compatible chat completions with tools, run until
no more tool calls. Every tool result carries its tool_call_id — orphaned
results make upstreams return empty completions.

The loop is shared by the main agent and subagents. Meta-tools (subagents,
scheduling, task lists) are main-agent-only and handled here, not in the
tool registry, because they need the run context.
"""
import asyncio
import json
import uuid
from pathlib import Path

import httpx

from . import memory as memory_store
from .config import load_config
from .costs import compute_cost
from .tools import TOOLS, tool_schemas

MAX_ITERATIONS = 25
SUB_MAX_ITERATIONS = 15
MAX_TOOL_RESULT = 12_000

SYSTEM_PROMPT = """You are Poseidon, an AI agent working on the user's machine in {workdir}.
Be warm, direct, and first-person. Understand what the user actually wants — if a request is ambiguous, ask one clarifying question instead of guessing.
For multi-step work, call set_tasks first with a short checklist and update statuses as you go.
Delegate big self-contained chunks with run_subagent; several run_subagent calls in one reply run in parallel.
Use schedule_task for anything recurring or "later". Unattended runs can only write/run what an "always allow" rule already covers.
You have persistent memory across sessions: save durable facts (who the user is, their preferences, ongoing projects) with save_memory; check your memory index before asking things you should already know; read_memory for details, forget_memory for stale facts.
Reads are instant; writes and commands ask for approval — that's normal, don't apologize for it.
When you finish, summarize what changed in plain language."""

SUBAGENT_PROMPT = """You are a Poseidon subagent working in {workdir}, delegated one task by the main agent.
Complete the task with tools, then reply with a concise result — your final message is returned to the main agent.
Writes and commands may require user approval; if denied, work around it or report it."""

META_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_tasks",
            "description": "Show/update your working checklist in the UI. Call with the full list each time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                            },
                            "required": ["title", "status"],
                        },
                    }
                },
                "required": ["tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_subagent",
            "description": "Delegate a self-contained task to a subagent with its own context. Multiple calls in one reply run in parallel. Returns the subagent's final report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Complete, self-contained instructions"},
                    "context": {"type": "string", "description": "Optional extra context the subagent needs"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": "Schedule a prompt to run automatically later. Provide exactly one of: every_minutes (recurring interval), daily_at (recurring, 'HH:MM' 24h local), once_at (one-shot, ISO datetime).",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the scheduled run should do"},
                    "every_minutes": {"type": "number"},
                    "daily_at": {"type": "string"},
                    "once_at": {"type": "string"},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_schedules",
            "description": "List all scheduled tasks with their next/last run times.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_schedule",
            "description": "Cancel a scheduled task by id.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
    },
]
META_NAMES = {s["function"]["name"] for s in META_SCHEMAS}


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
    index = memory_store.load_index()
    if index:
        prompt += "\n\nYour memory index (one line per saved memory):\n" + index
    return prompt


async def run_turn(
    workdir, store, session_id, user_message, emit, broker, scheduler=None, unattended=False
):
    cfg = load_config()
    provider = cfg.get("provider")
    if not provider or not provider.get("base_url"):
        await emit({"type": "error", "message": "No provider configured — open Settings."})
        return

    run = {
        "provider": provider,
        "workdir": workdir,
        "store": store,
        "session_id": session_id,
        "emit": emit,
        "broker": broker,
        "scheduler": scheduler,
        "unattended": unattended,
    }
    messages = store.get_messages(session_id)
    if not messages:
        messages.append({"role": "system", "content": _build_system_prompt(workdir)})
    messages.append({"role": "user", "content": user_message})
    await emit({"type": "turn_started"})
    try:
        await _agent_loop(run, messages, MAX_ITERATIONS, agent=None, allow_meta=True)
    except Exception as e:  # surface, don't swallow
        await emit({"type": "error", "message": str(e)[:800]})
    finally:
        store.save_messages(session_id, messages)
        await emit({"type": "turn_complete"})


async def _agent_loop(run, messages, max_iter, agent, allow_meta) -> str:
    emit = run["emit"]
    schemas = tool_schemas() + (META_SCHEMAS if allow_meta else [])
    last_content = ""
    for _ in range(max_iter):
        data = await _chat_completion(run["provider"], messages, schemas)
        usd, priced = compute_cost(run["provider"]["model"], data.get("usage"))
        run["store"].add_usage(run["session_id"], usd, priced, data.get("usage"))
        await emit({"type": "cost_update", **run["store"].get_cost(run["session_id"])})

        msg = data["choices"][0]["message"]
        messages.append(msg)
        if msg.get("content"):
            last_content = msg["content"]
            await emit({"type": "assistant_message", "content": msg["content"], "agent": agent})

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            break

        # parallel fan-out when the model delegates several subagents at once
        if allow_meta and len(tool_calls) > 1 and all(
            tc["function"]["name"] == "run_subagent" for tc in tool_calls
        ):
            results = await asyncio.gather(
                *(_dispatch(run, tc, agent, allow_meta) for tc in tool_calls)
            )
        else:
            results = [await _dispatch(run, tc, agent, allow_meta) for tc in tool_calls]

        for tc, result in zip(tool_calls, results):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result)[:MAX_TOOL_RESULT],
                }
            )
    else:
        await emit({"type": "error", "message": f"Stopped after {max_iter} steps.", "agent": agent})
    return last_content


async def _dispatch(run, tc, agent, allow_meta) -> dict:
    name = tc["function"]["name"]
    try:
        args = json.loads(tc["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}
    await run["emit"]({"type": "tool_call", "name": name, "args": args, "agent": agent})
    if name in META_NAMES:
        result = await _exec_meta(run, name, args) if allow_meta else {
            "error": "meta tools are main-agent only"
        }
    else:
        result = await _execute_tool(run, name, args)
    await run["emit"](
        {
            "type": "tool_result",
            "name": name,
            "ok": "error" not in result,
            "summary": _summarize(result),
            "agent": agent,
        }
    )
    return result


async def _execute_tool(run, name, args) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"unknown tool: {name}"}
    if spec["needs_approval"]:
        subject, detail = spec["subject"](args)
        decision = await run["broker"].request(
            run["emit"], name, subject, detail, unattended=run["unattended"]
        )
        if not decision["approved"]:
            if decision.get("unattended"):
                reason = "denied (unattended run, no matching 'always allow' rule)"
            elif decision.get("timeout"):
                reason = "timed out"
            else:
                reason = "denied by user"
            return {"error": f"approval {reason}"}
    try:
        return await spec["handler"](args, {"workdir": run["workdir"]})
    except Exception as e:
        return {"error": str(e)[:500]}


async def _exec_meta(run, name, args) -> dict:
    if name == "set_tasks":
        tasks = args.get("tasks") or []
        await run["emit"]({"type": "tasks_update", "tasks": tasks})
        return {"ok": True, "count": len(tasks)}

    if name == "run_subagent":
        return await _run_subagent(run, args)

    scheduler = run["scheduler"]
    if scheduler is None:
        return {"error": "scheduler unavailable in this context"}

    if name == "schedule_task":
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return {"error": "prompt is required"}
        when = (
            f"every {args['every_minutes']} min"
            if args.get("every_minutes")
            else f"daily at {args['daily_at']}"
            if args.get("daily_at")
            else f"once at {args.get('once_at')}"
        )
        decision = await run["broker"].request(
            run["emit"], "schedule_task", when, prompt, unattended=run["unattended"]
        )
        if not decision["approved"]:
            return {"error": "schedule not approved by user"}
        try:
            return scheduler.add(
                prompt,
                every_minutes=args.get("every_minutes"),
                daily_at=args.get("daily_at"),
                once_at=args.get("once_at"),
            )
        except ValueError as e:
            return {"error": str(e)}

    if name == "list_schedules":
        return {"schedules": scheduler.list()}

    if name == "cancel_schedule":
        ok = scheduler.cancel(args.get("id", ""))
        return {"ok": ok} if ok else {"error": "no schedule with that id"}

    return {"error": f"unknown meta tool: {name}"}


async def _run_subagent(run, args) -> dict:
    task = (args.get("task") or "").strip()
    if not task:
        return {"error": "task is required"}
    label = f"sub:{uuid.uuid4().hex[:4]}"
    await run["emit"]({"type": "subagent_started", "agent": label, "task": task[:200]})
    messages = [
        {"role": "system", "content": SUBAGENT_PROMPT.format(workdir=run["workdir"])},
        {
            "role": "user",
            "content": task + (f"\n\nContext:\n{args['context']}" if args.get("context") else ""),
        },
    ]
    try:
        result = await _agent_loop(run, messages, SUB_MAX_ITERATIONS, agent=label, allow_meta=False)
    except Exception as e:
        await run["emit"]({"type": "subagent_complete", "agent": label, "result": f"error: {e}"})
        return {"error": f"subagent failed: {str(e)[:300]}"}
    await run["emit"](
        {"type": "subagent_complete", "agent": label, "result": (result or "")[:300]}
    )
    return {"result": result or "(subagent produced no final text)"}


def _summarize(result: dict) -> str:
    if "error" in result:
        return result["error"][:200]
    if "result" in result:
        return str(result["result"])[:200]
    if "content" in result:
        return f"{len(result['content'])} chars"
    if "entries" in result:
        return f"{len(result['entries'])} entries"
    if "exit_code" in result:
        return f"exit {result['exit_code']}"
    if "schedules" in result:
        return f"{len(result['schedules'])} schedules"
    return "ok"
