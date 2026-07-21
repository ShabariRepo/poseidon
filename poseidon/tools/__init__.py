"""Tool registry. Reads are free; writes and commands go through the approval broker.

Each tool: OpenAI-format schema, async handler(args, ctx), and — if it needs
approval — a subject() that extracts what the user is being asked to approve.
ctx is {"workdir": Path}.
"""
from .. import memory as memory_store
from . import comms, docs, files, shell, web

TOOLS = {}


def _register(name, description, parameters, handler, needs_approval=False, subject=None):
    TOOLS[name] = {
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        },
        "handler": handler,
        "needs_approval": needs_approval,
        "subject": subject,
    }


_register(
    "list_dir",
    "List files and directories at a path (relative to the working directory).",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path, default '.'"}},
    },
    files.list_dir,
)

_register(
    "read_file",
    "Read a text file. Returns up to 100KB.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    files.read_file,
)

_register(
    "write_file",
    "Create or overwrite a file with the given content.",
    {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
    files.write_file,
    needs_approval=True,
    subject=lambda a: (a.get("path", ""), a.get("content", "")[:2000]),
)

_register(
    "edit_file",
    "Replace an exact string in a file with a new string. old_string must appear exactly once.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    files.edit_file,
    needs_approval=True,
    subject=lambda a: (
        a.get("path", ""),
        f"- {a.get('old_string', '')[:900]}\n+ {a.get('new_string', '')[:900]}",
    ),
)

_register(
    "run_command",
    "Run a shell command in the working directory. Returns stdout, stderr, and exit code.",
    {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    shell.run_command,
    needs_approval=True,
    subject=lambda a: (a.get("command", ""), a.get("command", "")),
)

_register(
    "web_fetch",
    "Fetch a URL and return its text content (HTML stripped).",
    {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    web.web_fetch,
)


async def _save_memory(args, ctx):
    return memory_store.save(ctx.get("project_id", "default"), args["title"], args["content"])


async def _read_memory(args, ctx):
    return memory_store.read(ctx.get("project_id", "default"), args["name"])


async def _forget_memory(args, ctx):
    return memory_store.forget(ctx.get("project_id", "default"), args["name"])


async def _search_memory(args, ctx):
    from ..retrieval import BM25
    entries = memory_store.list_entries(ctx.get("project_id", "default"))
    if not entries:
        return {"results": [], "note": "no memories yet"}
    docs = [(e["name"], f"{e['title']} {e['preview']}") for e in entries]
    hits = BM25(docs).search(args["query"], top_k=int(args.get("top_k", 5)), min_score=0.01)
    by_name = {e["name"]: e for e in entries}
    return {"results": [
        {"name": n, "title": by_name[n]["title"], "preview": by_name[n]["preview"][:300],
         "links": by_name[n]["links"], "score": round(sc, 3)}
        for n, sc in hits]}


_register(
    "save_memory",
    "Save a durable fact to persistent memory (survives across sessions, shared with the team). Connect related memories with [[Other Memory Title]] wikilinks inside the content — memory is a graph and linked facts are recalled together. Overwrites if the title already exists.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short descriptive title"},
            "content": {"type": "string", "description": "The fact, in a few sentences"},
        },
        "required": ["title", "content"],
    },
    _save_memory,
)

_register(
    "read_memory",
    "Read the full content of a memory listed in your memory index.",
    {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Memory name/title from the index"}},
        "required": ["name"],
    },
    _read_memory,
)

_register(
    "forget_memory",
    "Delete a memory that is wrong or no longer relevant.",
    {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    _forget_memory,
)

_register(
    "search_memory",
    "Search persistent memory by keyword and get the best-matching memories back (ranked). Use when your memory index is large or you need a fact that may not be in the always-loaded index. Local keyword search, instant, no cost.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "what you're trying to recall"},
            "top_k": {"type": "integer", "description": "max results (default 5)"},
        },
        "required": ["query"],
    },
    _search_memory,
)


async def _use_skill(args, ctx):
    from .. import skills
    return skills.read_skill(ctx["workdir"], args["name"])


_register(
    "use_skill",
    "Load a skill's full instructions by name (skills are listed in your system prompt).",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    _use_skill,
)

_register(
    "read_document",
    "Read an office document: .xlsx (sheets as tables), .docx (text), .pdf (text).",
    {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    docs.read_document,
)

_register(
    "edit_spreadsheet",
    "Edit or create an .xlsx spreadsheet: set cells and/or append rows.",
    {"type": "object", "properties": {
        "path": {"type": "string"},
        "sheet": {"type": "string", "description": "sheet name (default: active)"},
        "updates": {"type": "array", "items": {"type": "object", "properties": {"cell": {"type": "string"}, "value": {}}, "required": ["cell"]}},
        "append_rows": {"type": "array", "items": {"type": "array", "items": {}}}},
     "required": ["path"]},
    docs.edit_spreadsheet,
    needs_approval=True,
    subject=lambda a: (a.get("path", ""), f"{len(a.get('updates') or [])} cell updates, {len(a.get('append_rows') or [])} new rows"),
)

_register(
    "list_emails",
    "List recent emails from the connected Gmail inbox (headers only).",
    {"type": "object", "properties": {"limit": {"type": "integer", "description": "max emails, default 5"},
     "unread_only": {"type": "boolean", "description": "default true"}}},
    comms.list_emails,
)

_register(
    "read_email",
    "Read one email's full body by id (from list_emails).",
    {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    comms.read_email,
)

_register(
    "send_email",
    "Send an email from the connected Gmail account.",
    {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]},
    comms.send_email,
    needs_approval=True,
    subject=lambda a: (a.get("to", ""), f"Subject: {a.get('subject', '')}\n\n{a.get('body', '')[:1500]}"),
)

_register(
    "slack_post",
    "Post a message to Slack (uses the default channel if none given).",
    {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["text"]},
    comms.slack_post,
    needs_approval=True,
    subject=lambda a: (a.get("channel") or "default channel", a.get("text", "")[:1500]),
)


def tool_schemas() -> list:
    return [t["schema"] for t in TOOLS.values()]
