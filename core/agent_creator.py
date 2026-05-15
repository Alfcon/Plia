"""
agent_creator.py — Turns "create an agent that does X" into a live agent.

Pure helpers:
  parse_intent(text)        -> task string | None
  pick_tools(task)          -> list[str]   (safe default tool whitelist)
  classify_executor(...)    -> "script" | "tool_loop"
  parse_trigger / parse_persistence / parse_notify / parse_quota

State machine:
  WizardController          -> drives trigger/cadence/quota/persistence/notify Q&A

Commit:
  write_role_yaml(...)      -> Path to ~/.plia_ai/roles/<slug>.yml
  commit(...)               -> AgentState (also arms the scheduler)

Voice wrapper:
  VoiceWizardSession        -> wraps WizardController for spoken multi-turn use
"""

from __future__ import annotations

import re
import requests
from typing import List, Optional

# ── Intent detection ──────────────────────────────────────────────────────
_INTENT_PATTERNS = [
    r"(?:create|make|build|add|set\s+up)\s+(?:me\s+)?(?:an?|the)?\s*"
    r"(?:custom\s+|live\s+)?agent\s+(?:that|to|for|which|called|named)?\s+"
    r"(?:can\s+|will\s+)?(.+)",
]
_INTENT_RE = [re.compile(p, re.IGNORECASE) for p in _INTENT_PATTERNS]

_DANGEROUS_VERBS = ("delete", "remove", "rm ", "format", "shell", "wipe", "erase")


def parse_intent(text: str) -> Optional[str]:
    """Return the task description from a create-agent phrase, else None.

    A task must be at least 4 words long to be considered specific enough.
    """
    if not text:
        return None
    stripped = text.strip()
    for rx in _INTENT_RE:
        m = rx.search(stripped)
        if m:
            task = m.group(1).strip().rstrip(".!?,")
            if len(task.split()) < 3:
                return None
            return task
    return None


# ── Tool whitelist picker ─────────────────────────────────────────────────
_TOOL_KEYWORDS = [
    (("github", "repo", "repository", "pull request"), ["web_search", "http_get"]),
    (("email", "inbox"), ["read_emails"]),
    (("calendar", "event", "meeting", "schedule appointment"), ["get_system_info"]),
    (("news", "rss", "article", "headline"), ["web_search", "http_get"]),
    (("stock", "share price", "currency", "exchange rate"),
     ["get_stock_price", "convert_currency"]),
]


def pick_tools(task: str) -> List[str]:
    """Pick a safe default tool whitelist for a task.

    Tasks containing dangerous verbs get an empty list — the user must opt in
    to destructive tools explicitly via the editor.
    """
    t = (task or "").lower()
    if any(verb in t for verb in _DANGEROUS_VERBS):
        return []
    for keywords, tools in _TOOL_KEYWORDS:
        if any(kw in t for kw in keywords):
            return list(tools)
    return ["web_search"]


# ── Executor classifier ───────────────────────────────────────────────────
_CLASSIFY_PROMPT = (
    "You are picking the execution model for a Plia agent.\n"
    "TASK: {task}\n\n"
    "Reply with exactly one word:\n"
    "- script    -> task is deterministic and repeatable "
    "(search+download, RSS fetch, fixed-API check)\n"
    "- tool_loop -> task is exploratory or multi-step "
    "(research, compare, decide based on findings)"
)


def classify_executor(task: str, ollama_url: str, model: str) -> str:
    """Ask the local LLM whether this task suits a generated script or a
    tool-loop. Defaults to 'tool_loop' on any failure (safer — runs under
    an iteration cap)."""
    base = ollama_url.rstrip("/api").rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user",
                      "content": _CLASSIFY_PROMPT.format(task=task)}],
        "stream": False,
        "options": {"num_predict": 8, "temperature": 0.0},
    }
    try:
        resp = requests.post(f"{base}/api/chat", json=payload, timeout=30)
        resp.raise_for_status()
        content = (resp.json().get("message", {}).get("content", "") or "").lower()
    except Exception as exc:
        print(f"[agent_creator] classify_executor failed: {exc}")
        return "tool_loop"
    if "script" in content and "tool_loop" not in content:
        return "script"
    if "tool_loop" in content:
        return "tool_loop"
    return "tool_loop"
