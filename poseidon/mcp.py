"""MCP client (stdio transport): connect Model Context Protocol servers and
expose their tools to the agent as mcp__<server>__<tool>. Every MCP call is
approval-gated — third-party tools have unknown side effects; "always allow"
scopes to that one server.tool.

Config:
  "mcp_servers": {
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_TOKEN": "..."}}
  }
"""
import asyncio
import json
import os
import re

from . import __version__
from .config import load_config

PROTOCOL = "2024-11-05"
SEP = "__"


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:40]


class MCPServer:
    def __init__(self, name: str, spec: dict):
        self.name = name
        self.spec = spec
        self.proc = None
        self.tools: list = []
        self._pending: dict[int, asyncio.Future] = {}
        self._id = 0
        self._reader_task = None

    async def start(self):
        self.proc = await asyncio.create_subprocess_exec(
            self.spec["command"], *(self.spec.get("args") or []),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, **(self.spec.get("env") or {})},
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._request("initialize", {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "poseidon", "version": __version__},
        }, timeout=20)
        await self._notify("notifications/initialized", {})
        res = await self._request("tools/list", {}, timeout=20)
        self.tools = res.get("tools", [])

    async def _read_loop(self):
        while self.proc and self.proc.stdout:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            fut = self._pending.pop(msg.get("id"), None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(RuntimeError(json.dumps(msg["error"])[:300]))
                else:
                    fut.set_result(msg.get("result") or {})

    async def _send(self, obj: dict):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def _request(self, method: str, params: dict, timeout: float = 60):
        self._id += 1
        mid = self._id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)

    async def _notify(self, method: str, params: dict):
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def call_tool(self, tool: str, args: dict) -> dict:
        res = await self._request("tools/call", {"name": tool, "arguments": args}, timeout=120)
        parts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
        out = {"result": "\n".join(parts)[:12000] or "(no text content)"}
        if res.get("isError"):
            out = {"error": out["result"][:500]}
        return out

    async def stop(self):
        if self._reader_task:
            self._reader_task.cancel()
        if self.proc:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass


class MCPManager:
    def __init__(self):
        self.servers: dict[str, MCPServer] = {}
        self.errors: dict[str, str] = {}

    async def start_all(self):
        await self.stop_all()
        for name, spec in (load_config().get("mcp_servers") or {}).items():
            if not isinstance(spec, dict) or not spec.get("command"):
                continue
            srv = MCPServer(_safe(name), spec)
            try:
                await srv.start()
                self.servers[srv.name] = srv
            except Exception as e:
                self.errors[name] = str(e)[:200]

    async def stop_all(self):
        for srv in self.servers.values():
            await srv.stop()
        self.servers, self.errors = {}, {}

    def schemas(self) -> list:
        out = []
        for sname, srv in self.servers.items():
            for t in srv.tools:
                out.append({"type": "function", "function": {
                    "name": f"mcp{SEP}{sname}{SEP}{_safe(t['name'])}",
                    "description": f"[{sname} via MCP] {t.get('description', '')[:400]}",
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
                }})
        return out

    def resolve(self, qualified: str):
        parts = qualified.split(SEP, 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return None, None
        srv = self.servers.get(parts[1])
        if not srv:
            return None, None
        for t in srv.tools:
            if _safe(t["name"]) == parts[2]:
                return srv, t["name"]
        return None, None

    async def call(self, qualified: str, args: dict) -> dict:
        srv, tool = self.resolve(qualified)
        if not srv:
            return {"error": f"unknown MCP tool: {qualified}"}
        try:
            return await srv.call_tool(tool, args)
        except Exception as e:
            return {"error": f"MCP call failed: {str(e)[:300]}"}

    def status(self) -> dict:
        return {**{n: len(s.tools) for n, s in self.servers.items()},
                **{n: f"error: {e}" for n, e in self.errors.items()}}


_manager: MCPManager | None = None


def get_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager
