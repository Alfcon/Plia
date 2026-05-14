"""
core/mcp_client.py — MCP client for Plia

Spawns MCP servers from ~/.plia/mcp.json, discovers their tools, and executes
tool calls on demand.

Integration contract (used by router + executor):
- tool_id format: "<serverId>:<toolName>"
- execute(tool_id, arguments_json_or_text) returns:
    { "success": bool, "message": str, "data": { "tool_id": str, "tool_name": str, "output": Any } }

Design notes
-------------
* Qt threading: execution is invoked from non-async code paths. This module
  runs an asyncio event loop in a dedicated background thread and exposes
  synchronous methods that schedule coroutines on that loop.
* Discovery cache: tool catalog is cached in-memory for router prompting.
* Transport: currently supports "stdio" (the common "Claude Desktop style").
  Other transports can be added later.

Config schema (minimal)
------------------------
~/.plia/mcp.json

{
  "servers": [
    {
      "id": "isair",
      "transport": "stdio",
      "command": "node",
      "args": ["path/to/server.js"],
      "env": { "KEY": "..." }
    }
  ]
}

If ~/.plia/mcp.json is missing or invalid, Plia runs without MCP tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

import hashlib
import re

# Paths
PLIA_DIR = Path.home() / ".plia"
MCP_CONFIG_PATH = PLIA_DIR / "mcp.json"

# Keep router prompt reasonable
DEFAULT_TOOL_CATALOG_MAX = 35
DEFAULT_TOOL_CATALOG_MAX_CHARS = 1800

_PROMPT_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")

@dataclass(frozen=True)
class MCPServerConfig:
    id: str
    transport: str
    command: str
    args: List[str]
    env: Dict[str, str]
    # Optional timeout knobs
    connect_timeout_seconds: float = 10.0
    call_timeout_seconds: float = 60.0


@dataclass(frozen=True)
class MCPToolInfo:
    tool_id: str       # "<serverId>:<toolName>"
    server_id: str
    tool_name: str
    description: str


class MCPClient:
    def __init__(
        self,
        config_path: Path = MCP_CONFIG_PATH,
        tool_catalog_max: int = DEFAULT_TOOL_CATALOG_MAX,
        tool_catalog_max_chars: int = DEFAULT_TOOL_CATALOG_MAX_CHARS,
    ) -> None:
        self._config_path = config_path
        self._tool_catalog_max = tool_catalog_max
        self._tool_catalog_max_chars = tool_catalog_max_chars

        self._ready_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

        self._server_configs: List[MCPServerConfig] = []
        self._tools_by_id: Dict[str, MCPToolInfo] = {}
        self._sessions_by_server_id: Dict[str, Any] = {}  # stored in event loop thread
        self._discovery_error: Optional[str] = None

        self._start_background_loop()

    # ---------------------------
    # Public API used by router/executor
    # ---------------------------

    def is_ready(self) -> bool:
        """True when tool discovery completed (even if discovery found 0 tools)."""
        return self._ready_event.is_set()

    def get_tool_catalog_text(self, user_prompt: Optional[str] = None) -> str:
        """
        Return a short human-readable tool catalog for router prompting.

        If user_prompt is provided, the catalog is pruned to only the most
        relevant MCP tools using simple token/description scoring. If pruning
        finds no relevant tools (or user_prompt is empty), it falls back to the
        original stable top-N behavior.

        Router uses this to pick the right tool_id to call.
        """
        if not self._tools_by_id:
            return ""

        # Stable ordering for determinism (used for tie-breaks and fallback)
        tools_all = sorted(
            self._tools_by_id.values(), key=lambda t: (t.server_id, t.tool_name)
        )

        # Fast path: no prompt => old behavior
        if not user_prompt or not str(user_prompt).strip():
            lines: List[str] = ["MCP TOOL CATALOG (tool_id is what you must pass):"]
            for t in tools_all[: self._tool_catalog_max]:
                desc = (t.description or "").strip() or "No description."
                lines.append(f"- {t.tool_id}: {desc}")
            text = "\n".join(lines)
            if len(text) > self._tool_catalog_max_chars:
                text = text[: self._tool_catalog_max_chars].rstrip() + "..."
            return text

        # Basic relevance scoring
        prompt = str(user_prompt).lower()
        prompt_tokens = set(_PROMPT_TOKEN_RE.findall(prompt))
        if not prompt_tokens:
            # tokenization failed => fallback
            lines = ["MCP TOOL CATALOG (tool_id is what you must pass):"]
            for t in tools_all[: self._tool_catalog_max]:
                desc = (t.description or "").strip() or "No description."
                lines.append(f"- {t.tool_id}: {desc}")
            text = "\n".join(lines)
            if len(text) > self._tool_catalog_max_chars:
                text = text[: self._tool_catalog_max_chars].rstrip() + "..."
            return text

        def score_tool(t: MCPToolInfo) -> int:
            name = (t.tool_name or "").lower()
            desc = (t.description or "").lower()

            score = 0
            for tok in prompt_tokens:
                if not tok:
                    continue
                if tok in name:
                    score += 5
                if tok in desc:
                    score += 1
            # Tiny boost for token overlap with common tool/action verbs
            # (helps with generic prompts like "create" / "search" / "lookup")
            if "search" in prompt or "lookup" in prompt or "find" in prompt:
                if "search" in desc or "lookup" in desc or "find" in desc:
                    score += 2
            return score

        # Compute scores and keep positive ones
        scored: List[Tuple[int, MCPToolInfo]] = [(score_tool(t), t) for t in tools_all]
        scored_pos = [(s, t) for s, t in scored if s > 0]

        # If no positive relevance, fall back to top-N by stable ordering
        if not scored_pos:
            lines = ["MCP TOOL CATALOG (tool_id is what you must pass):"]
            for t in tools_all[: self._tool_catalog_max]:
                desc = (t.description or "").strip() or "No description."
                lines.append(f"- {t.tool_id}: {desc}")
            text = "\n".join(lines)
            if len(text) > self._tool_catalog_max_chars:
                text = text[: self._tool_catalog_max_chars].rstrip() + "..."
            return text

        # Sort by relevance score desc, then stable tie-break by server_id/tool_name
        scored_pos.sort(
            key=lambda st: (-st[0], st[1].server_id, st[1].tool_name)
        )
        tools_pruned = [t for _, t in scored_pos[: self._tool_catalog_max]]

        lines = ["MCP TOOL CATALOG (tool_id is what you must pass):"]
        for t in tools_pruned:
            desc = (t.description or "").strip() or "No description."
            lines.append(f"- {t.tool_id}: {desc}")

        text = "\n".join(lines)
        if len(text) > self._tool_catalog_max_chars:
            text = text[: self._tool_catalog_max_chars].rstrip() + "..."
        return text

    def execute(self, tool_id: str, arguments: Any) -> Dict[str, Any]:
        """
        Execute an MCP tool call synchronously.

        arguments can be:
        - a dict (preferred)
        - a JSON string representing a dict
        - any other type => passed as-is (server may reject)
        """
        if not self.is_ready():
            return {
                "success": False,
                "message": "MCP not ready (servers not discovered yet).",
                "data": None,
            }

        if not tool_id or tool_id not in self._tools_by_id:
            return {
                "success": False,
                "message": f"Unknown MCP tool_id: {tool_id}",
                "data": None,
            }

        tool = self._tools_by_id[tool_id]
        if not self._loop:
            return {
                "success": False,
                "message": "MCP event loop unavailable.",
                "data": None,
            }

        # Normalize arguments into dict for MCP call_tool(name, arguments)
        normalized_args: Any = arguments
        if isinstance(arguments, str):
            s = arguments.strip()
            if s.startswith("{") or s.startswith("["):
                try:
                    normalized_args = json.loads(s)
                except Exception:
                    # keep as string fallback
                    normalized_args = arguments

        # schedule on loop thread
        fut = asyncio.run_coroutine_threadsafe(
            self._async_call_tool(
                server_id=tool.server_id,
                tool_name=tool.tool_name,
                arguments=normalized_args,
            ),
            self._loop,
        )

        try:
            payload = fut.result(timeout=(60.0 + 10.0))
        except Exception as exc:
            return {
                "success": False,
                "message": f"MCP tool execution failed: {exc}",
                "data": None,
            }

        return payload

    # ---------------------------
    # Background loop & server sessions
    # ---------------------------

    def _start_background_loop(self) -> None:
        self._loop_thread = threading.Thread(
            target=self._loop_worker, daemon=True, name="MCP-Client-Loop"
        )
        self._loop_thread.start()

    def _loop_worker(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._async_load_and_discover())
        except Exception as exc:
            self._discovery_error = f"{type(exc).__name__}: {exc}"
        finally:
            # Even on error, mark ready so router doesn't wait forever
            self._ready_event.set()

            # Keep loop alive for later tool execution
            try:
                loop.run_forever()
            finally:
                loop.close()

    async def _async_load_and_discover(self) -> None:
        self._server_configs = self._parse_config()

        if not self._server_configs:
            # No config => no tools, but ready for graceful degradation.
            return

        # Start server tasks concurrently (they keep sessions alive forever).
        for cfg in self._server_configs:
            asyncio.create_task(self._async_serve_server(cfg))

        # Wait briefly for initial tool discovery so the router can prompt.
        # Do not block forever: servers may be slow or fail to start.
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if self._tools_by_id:
                break
            await asyncio.sleep(0.2)

    def _parse_config(self) -> List[MCPServerConfig]:
        if not self._config_path.exists():
            return []

        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        if not isinstance(raw, dict):
            return []

        servers = raw.get("servers", [])
        if not isinstance(servers, list):
            return []

        parsed: List[MCPServerConfig] = []
        for s in servers:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id", "")).strip()
            transport = str(s.get("transport", "stdio")).strip().lower()
            command = str(s.get("command", "")).strip()
            args = s.get("args", []) or []
            env = s.get("env", {}) or {}

            if not sid or not command:
                continue
            if transport != "stdio":
                # Only stdio supported in this first pass
                continue

            if not isinstance(args, list):
                args = [str(args)]
            if not isinstance(env, dict):
                env = {}

            parsed.append(
                MCPServerConfig(
                    id=sid,
                    transport=transport,
                    command=command,
                    args=[str(a) for a in args],
                    env={str(k): str(v) for k, v in env.items()},
                    connect_timeout_seconds=float(
                        s.get("connect_timeout_seconds", 10.0) or 10.0
                    ),
                    call_timeout_seconds=float(
                        s.get("call_timeout_seconds", 60.0) or 60.0
                    ),
                )
            )
        return parsed

    async def _async_serve_server(self, cfg: MCPServerConfig) -> None:
        """
        Connect to one MCP server via stdio, discover its tools, then keep the
        session alive indefinitely.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=cfg.env,
        )

        # Use stdio_client context to keep read/write streams open.
        async with stdio_client(server_params) as (read, write):
            # Create session and keep it open
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Discover tools (once) and cache
                try:
                    list_res = await session.list_tools()
                    tools = list_res.tools or []
                except Exception:
                    tools = []

                # Register tool catalog entries
                for tool in tools:
                    tool_name = getattr(tool, "name", "") or ""
                    if not tool_name:
                        continue
                    desc = getattr(tool, "description", "") or ""
                    tool_id = f"{cfg.id}:{tool_name}"
                    self._tools_by_id[tool_id] = MCPToolInfo(
                        tool_id=tool_id,
                        server_id=cfg.id,
                        tool_name=tool_name,
                        description=str(desc).strip(),
                    )

                # Save the session for future tool executions
                self._sessions_by_server_id[cfg.id] = session

                # Keep running forever; tool execution requests are handled via
                # run_coroutine_threadsafe which uses this same session.
                while True:
                    await asyncio.sleep(3600)

    async def _async_call_tool(
        self, server_id: str, tool_name: str, arguments: Any
    ) -> Dict[str, Any]:
        session = self._sessions_by_server_id.get(server_id)
        if not session:
            return {
                "success": False,
                "message": f"MCP server session not available: {server_id}",
                "data": None,
            }

        try:
            # MCP expects a dict of tool arguments. The SDK will validate
            # against the input schema.
            call_args = arguments if isinstance(arguments, dict) else {"value": arguments}

            # call_tool signature: call_tool(name, arguments, read_timeout_seconds=..., progress_callback=..., meta=...)
            res = await session.call_tool(
                name=tool_name,
                arguments=call_args,
                read_timeout_seconds=60.0,
            )

            # SDK returns CallToolResult with:
            #   content: list[content items]
            #   structuredContent: optional JSON
            #   isError: bool
            is_error = bool(getattr(res, "isError", False))
            structured = getattr(res, "structuredContent", None)

            # Convert content to a simple string for our UI context.
            content_items = getattr(res, "content", None) or []
            content_texts: List[str] = []
            for item in content_items:
                text = None
                if isinstance(item, dict):
                    text = item.get("text") or item.get("data") or item.get("content")
                else:
                    text = getattr(item, "text", None)
                    if text is None:
                        text = str(item)
                if text is not None:
                    content_texts.append(str(text))

            output: Any = structured if structured is not None else (content_texts[0] if content_texts else None)
            if is_error:
                return {
                    "success": False,
                    "message": f"MCP tool {tool_name} returned an error.",
                    "data": {"tool_name": tool_name, "output": output},
                }

            return {
                "success": True,
                "message": f"MCP tool executed: {tool_name}",
                "data": {
                    "tool_id": f"{server_id}:{tool_name}",
                    "tool_name": tool_name,
                    "output": output,
                },
            }

        except Exception as exc:
            return {
                "success": False,
                "message": f"MCP call_tool failed ({tool_name}): {type(exc).__name__}: {exc}",
                "data": None,
            }


# Module-level singleton for easy integration
mcp_client = MCPClient()
