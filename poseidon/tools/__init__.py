"""Tool registry. Reads are free; writes and commands go through the approval broker.

Each tool: OpenAI-format schema, async handler(args, ctx), and — if it needs
approval — a subject() that extracts what the user is being asked to approve.
ctx is {"workdir": Path}.
"""
from .. import memory as memory_store
from . import files, shell, web

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
    return memory_store.save(args["title"], args["content"])


async def _read_memory(args, ctx):
    return memory_store.read(args["name"])


async def _forget_memory(args, ctx):
    return memory_store.forget(args["name"])


_register(
    "save_memory",
    "Save a durable fact to persistent memory (survives across sessions). Use for lasting facts about the user, their projects, or their preferences — not session-only details. Overwrites if the title already exists.",
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


def tool_schemas() -> list:
    return [t["schema"] for t in TOOLS.values()]
