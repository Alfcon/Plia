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
    return (
        "You have these tools available: " + ", ".join(allowed_tools) + ".\n\n"
        "RULES (read carefully):\n"
        "1. You MUST call at least one tool before answering. Do not answer "
        "from memory or guesswork.\n"
        "2. NEVER invent URLs, repository names, titles, prices, or facts. "
        "Every item you return must come from a tool result you actually "
        "observed in this conversation.\n"
        "3. Stay strictly on the task topic and ignore unrelated search hits.\n"
        "4. If tool results are empty or unhelpful, return ITEMS_FOUND: 0 and "
        "say so honestly in SUMMARY. Do not fill the gap with made-up items.\n\n"
        "When you have enough information, reply with plain text in this exact format "
        "(no extra prose before SUMMARY):\n"
        "SUMMARY: <one concise sentence describing what you actually found>\n"
        "ITEMS_FOUND: <integer count>\n"
        'ITEMS_JSON: <json array; each item MUST be an object with at least '
        '"title" and "url" keys taken directly from tool results, e.g. '
        '[{"title": "acme/repo", "url": "https://github.com/acme/repo"}]>'
    )


def _parse_final(content: str) -> "RunResult":
    """Parse the LLM's final response.

    Preferred format is `SUMMARY: ... \\nITEMS_FOUND: N\\nITEMS_JSON: [...]`,
    but if the model produced free-form prose we still want a useful result:
      - Summary falls back to the first non-empty line (no hard truncation).
      - Items fall back to any `[title](url)` markdown links scraped from prose.
    This makes prose-loving models (e.g. small Qwen variants on comparison
    tasks) still surface clickable hits in the chat tab.
    """
    from core.executors.run_result import RunResult

    text = content or ""
    summary_m = re.search(r"SUMMARY:\s*(.+)", text)
    found_m = re.search(r"ITEMS_FOUND:\s*(\d+)", text)
    items_m = re.search(r"ITEMS_JSON:\s*(\[.*\])", text, re.DOTALL)

    if summary_m:
        summary = summary_m.group(1).strip()
    else:
        # First non-blank line of the response — no character truncation;
        # details holds the full text anyway.
        first_line = next(
            (ln.strip() for ln in text.splitlines() if ln.strip()),
            "",
        )
        summary = first_line or "Done."

    items: List[Dict] = []
    if items_m:
        try:
            parsed = json.loads(items_m.group(1))
            if isinstance(parsed, list):
                items = parsed
        except json.JSONDecodeError:
            items = []

    # Fallback: pull markdown [title](url) links from the prose so prose-only
    # answers still get clickable hits in chat.
    if not items:
        seen = set()
        for m in re.finditer(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", text):
            title, url = m.group(1).strip(), m.group(2).strip()
            if url in seen:
                continue
            seen.add(url)
            items.append({"title": title, "url": url})

    items_found = int(found_m.group(1)) if found_m else len(items)
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
        tool_calls_made = 0       # how many tools the LLM actually invoked
        forced_retry_used = False # we allow one nudge if it tries to answer without calling tools

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
                        tool_calls_made += 1
                    except Exception as exc:
                        tool_result = {"success": False, "message": str(exc)}
                    messages.append({"role": "tool",
                                     "content": json.dumps(tool_result)[:6000]})
                continue

            # Final response (model returned plain text, no tool_calls).
            final = _parse_final(msg.get("content", "") or "")

            if tool_calls_made == 0:
                # Skipped tools entirely AND came back empty? Almost certainly
                # the model didn't bother doing the work. Nudge it once.
                if final.items_found == 0 and not forced_retry_used:
                    forced_retry_used = True
                    messages.append(msg)
                    primary_tool = allowed_tools[0] if allowed_tools else "the available tool"
                    messages.append({
                        "role": "user",
                        "content": (
                            "Your previous answer found 0 items and you did "
                            "not call any tools. You MUST call "
                            f"`{primary_tool}` first to gather real data, "
                            "then answer in the SUMMARY / ITEMS_FOUND / "
                            "ITEMS_JSON format."
                        ),
                    })
                    continue
                # Items returned but no tool was called — likely fabricated.
                final.error = "no_tool_call"
                final.details = (
                    "⚠️ The agent did not call any tools before answering. "
                    "Results below may be fabricated — consider using a "
                    "larger model (e.g. qwen3:8b) for reliable tool use.\n\n"
                    + final.details
                )
            return final

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
