"""
direct_tool_executor.py — Deterministic single-tool runner.

Where the tool-loop executor lets an LLM choose tools and synthesise an
answer, the direct-tool executor invokes one named tool with fixed
arguments. Useful for scheduled, deterministic checks:

  * "every hour, call github:list_notifications and post to chat"
  * "every 5 minutes, call my_plugin:ping_server and toast if down"
  * "every morning, call brave:search('AI news') and append to file"

Output normalisation maps the tool's response into a RunResult:

  - tool's ``success``  → RunResult.success
  - tool's ``message``  → RunResult.summary
  - tool's ``data.items`` / ``data.results`` (if list of dicts) → items
  - everything is also stuffed into ``details`` as pretty JSON for the
    file / details panels.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

from core.executors.run_result import RunResult
from core.function_executor import executor as function_executor


def _extract_items(data: Any) -> List[Dict[str, Any]]:
    """Best-effort: find a list[dict] inside the tool's `data` payload."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "results", "entries", "list"):
            v = data.get(key)
            if isinstance(v, list):
                hits = [x for x in v if isinstance(x, dict)]
                if hits:
                    return hits
    return []


def _format_details(data: Any) -> str:
    if data is None:
        return ""
    try:
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)[:5000]
    except Exception:
        return str(data)[:5000]


def make_direct_tool_runner(*, tool_id: str,
                            arguments: Dict[str, Any]) -> Callable[..., RunResult]:
    """Build a runner that calls one function-tool with fixed arguments.

    `tool_id` is whatever `executor.execute()` accepts: a built-in name
    (e.g. ``web_search``), a plugin tool (``my_plugin:do_thing``), or an MCP
    tool routed via ``mcp_tool_call`` (in which case pass tool_id=
    "mcp_tool_call" and arguments={"tool_id": "<server>:<tool>", "arguments": {...}}).
    """
    static_args = dict(arguments or {})

    def _runner(*, agent, task, context) -> RunResult:
        if not tool_id:
            return RunResult(
                success=False,
                summary="No tool_id configured.",
                details="direct_tool runner was created without a tool_id.",
                error="missing_tool_id",
            )
        try:
            result = function_executor.execute(tool_id, static_args)
        except Exception as exc:
            return RunResult(
                success=False,
                summary=f"Tool {tool_id!r} crashed.",
                details=str(exc),
                error="executor_internal",
            )

        if not isinstance(result, dict):
            return RunResult(
                success=False,
                summary=f"Tool {tool_id!r} returned non-dict.",
                details=str(result)[:2000],
                error="non_dict_result",
            )

        success = bool(result.get("success", False))
        message = str(result.get("message") or "").strip() or (
            "Tool returned no message"
        )
        data = result.get("data")
        items = _extract_items(data)
        details = _format_details(data) or message

        return RunResult(
            success=success,
            summary=message[:500],
            details=details,
            items_found=len(items),
            items=items,
            error=None if success else (result.get("error") or "tool_failed"),
        )

    return _runner
