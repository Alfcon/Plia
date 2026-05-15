"""
tool_loop_executor.py — Runs an agent as an LLM tool-call loop.

make_tool_loop_runner(...) returns a callable matching the AgentTaskManager
runner signature: runner(*, agent, task, context) -> RunResult.

The loop: send task + tool catalog to Ollama -> if the model returns
tool_calls, execute the allowed ones via function_executor and feed results
back -> repeat until the model returns plain text or a hard limit is hit.

Hard limits:
  - max_steps         iteration cap (default 8)
  - token_budget      sum of prompt_eval_count + eval_count across calls
  - allowed_tools     any tool call outside this set is refused, not executed
"""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, List

import requests

from core.function_executor import executor as function_executor
from core.multi_agent import build_system_prompt


def _build_catalog(allowed_tools: List[str]) -> List[Dict]:
    """Build an Ollama-style tools array. Descriptions are intentionally
    generic — the model only needs names + that arguments are free-form."""
    catalog = []
    for name in allowed_tools:
        catalog.append({
            "type": "function",
            "function": {
                "name": name,
                "description": f"Plia tool '{name}'. Pass arguments as needed.",
                "parameters": {"type": "object", "properties": {}},
            },
        })
    return catalog


def _catalog_text(allowed_tools: List[str]) -> str:
    if not allowed_tools:
        return "You have no tools available. Answer from reasoning alone."
    return ("You may call these tools: " + ", ".join(allowed_tools) +
            ".\nWhen finished, reply with plain text in this exact format:\n"
            "SUMMARY: <one line>\nITEMS_FOUND: <integer>\nITEMS_JSON: <json array>")


def _parse_final(content: str) -> "RunResult":
    from core.executors.run_result import RunResult
    summary_m = re.search(r"SUMMARY:\s*(.+)", content)
    found_m = re.search(r"ITEMS_FOUND:\s*(\d+)", content)
    items_m = re.search(r"ITEMS_JSON:\s*(\[.*\])", content, re.DOTALL)
    summary = summary_m.group(1).strip() if summary_m else content.strip()[:200] or "Done."
    items_found = int(found_m.group(1)) if found_m else 0
    items: List[Dict] = []
    if items_m:
        try:
            parsed = json.loads(items_m.group(1))
            if isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            items = []
    return RunResult(
        success=True,
        summary=summary,
        details=content.strip(),
        items_found=items_found,
        items=items,
        error=None,
    )


def make_tool_loop_runner(*, allowed_tools: List[str], ollama_url: str,
                          model: str, max_steps: int = 8,
                          token_budget: int = 100_000) -> Callable[..., "RunResult"]:
    from core.executors.run_result import RunResult

    def _runner(*, agent, task: str, context: str) -> RunResult:
        role = agent.agent.role
        base = ollama_url.rstrip("/api").rstrip("/")
        messages = [
            {"role": "system",
             "content": build_system_prompt(role) + "\n\n" + _catalog_text(allowed_tools)},
            {"role": "user", "content": task},
        ]
        if context:
            messages.append({"role": "user", "content": f"Previous run summary: {context}"})

        catalog = _build_catalog(allowed_tools)
        tokens_used = 0

        for _step in range(max_steps):
            payload = {"model": model, "messages": messages,
                       "tools": catalog, "stream": False}
            try:
                resp = requests.post(f"{base}/api/chat", json=payload, timeout=120)
                resp.raise_for_status()
                obj = resp.json()
            except Exception as exc:
                return RunResult(
                    success=False,
                    summary="Tool-loop call failed.",
                    details=str(exc),
                    error="executor_internal",
                )

            tokens_used += int(obj.get("prompt_eval_count", 0) or 0)
            tokens_used += int(obj.get("eval_count", 0) or 0)
            if tokens_used > token_budget:
                return RunResult(
                    success=True,
                    summary="Token budget reached. Partial results.",
                    details=_last_assistant_text(messages),
                    error="token_budget",
                )

            msg = obj.get("message", {}) or {}
            tool_calls = msg.get("tool_calls") or []

            if tool_calls:
                messages.append(msg)
                for call in tool_calls:
                    fn = call.get("function", {}) or {}
                    name = fn.get("name", "")
                    args = fn.get("arguments", {}) or {}
                    if name not in allowed_tools:
                        messages.append({"role": "tool",
                                         "content": f"DENIED: '{name}' not in allowed_tools"})
                        continue
                    try:
                        tool_result = function_executor.execute(name, args)
                    except Exception as exc:
                        tool_result = {"success": False, "message": str(exc)}
                    messages.append({"role": "tool",
                                     "content": json.dumps(tool_result)[:6000]})
                continue

            return _parse_final(msg.get("content", "") or "")

        return RunResult(
            success=True,
            summary="Iteration cap reached. Partial results.",
            details=_last_assistant_text(messages),
            error="iteration_cap",
        )

    return _runner


def _last_assistant_text(messages: List[Dict]) -> str:
    for m in reversed(messages):
        if m.get("role") in ("assistant", "tool") and m.get("content"):
            return str(m["content"])
    return ""
