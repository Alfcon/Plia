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


# ── Question parsers ──────────────────────────────────────────────────────
def parse_trigger(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "quota" in t or "until it finds" in t or "until i find" in t \
            or "enough" in t or "top " in t:
        return "quota"
    if "schedul" in t or "every" in t or "periodic" in t or "regular" in t:
        return "scheduled"
    if "on demand" in t or "on-demand" in t or "when i ask" in t \
            or "manual" in t or "only when" in t:
        return "on_demand"
    return None


def parse_persistence(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "persist" in t or "survive" in t or "across restart" in t \
            or "keep it" in t or "stay" in t:
        return "persistent"
    if "session" in t or "just this" in t or "temporary" in t \
            or "don't keep" in t or "do not keep" in t:
        return "session"
    return None


def parse_notify(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "speak" in t or "aloud" in t or "say it" in t or "tts" in t \
            or "voice" in t:
        return "tts"
    if "toast" in t or "card" in t or "dashboard" in t or "popup" in t \
            or "pop-up" in t or "notification" in t:
        return "toast_card"
    if "log" in t or "comm" in t:
        return "comm_log"
    return None


def parse_quota(text: str) -> Optional[dict]:
    t = (text or "").lower()
    m = re.search(r"(\d+)", t)
    if not m:
        return None
    limit = int(m.group(1))
    criterion = "top_rated" if ("top" in t or "rated" in t or "best" in t) else "any"
    return {"limit": limit, "criterion": criterion}


from dataclasses import dataclass, field
from typing import Callable, Dict

from core.agent_scheduler import parse_cadence

_CANCEL_WORDS = ("cancel", "never mind", "nevermind", "stop", "forget it")


@dataclass
class WizardStep:
    question: str
    examples: List[str] = field(default_factory=list)
    done: bool = False
    cancelled: bool = False
    answers: Optional[Dict] = None


_Q_TRIGGER = WizardStep(
    "How should this agent run — scheduled, on-demand, or quota?",
    ["scheduled", "on demand", "quota (stop after N results)"])
_Q_CADENCE = WizardStep(
    "How often should it run?",
    ["every hour", "every 6 hours", "twice a day", "every Monday morning"])
_Q_QUOTA = WizardStep(
    "How many results should it collect before stopping?",
    ["top 10", "just 20", "find 5 things"])
_Q_PERSISTENCE = WizardStep(
    "Should it survive restarts, or run for this session only?",
    ["persistent", "session only"])
_Q_NOTIFY = WizardStep(
    "How should it notify you — speak aloud, toast and dashboard card, "
    "or communication log?",
    ["speak", "toast and card", "communication log"])


class WizardController:
    """Channel-agnostic Q&A state machine for creating a live agent.

    Adapters (voice, chat) call current_question() to get the prompt and
    answer(text) to advance. answer() returns the next WizardStep; when
    step.done is True, step.answers holds the collected configuration (or
    step.cancelled is True if the user bailed out).
    """

    def __init__(self, task: str, classify_fn: Callable[[str], str]):
        self.task = task
        self._classify_fn = classify_fn
        self._state = "ASK_TRIGGER"
        self._answers: Dict = {
            "task": task, "trigger": None, "cadence": None, "quota": None,
            "persistence": None, "notify": None, "executor": None, "tools": None,
        }

    def current_question(self) -> WizardStep:
        return {
            "ASK_TRIGGER": _Q_TRIGGER,
            "ASK_CADENCE": _Q_CADENCE,
            "ASK_QUOTA": _Q_QUOTA,
            "ASK_PERSISTENCE": _Q_PERSISTENCE,
            "ASK_NOTIFY": _Q_NOTIFY,
            "CONFIRM": self._confirm_step(),
        }[self._state]

    def answer(self, text: str) -> WizardStep:
        if any(w in (text or "").lower() for w in _CANCEL_WORDS):
            return WizardStep("Cancelled.", done=True, cancelled=True)

        if self._state == "ASK_TRIGGER":
            trigger = parse_trigger(text)
            if trigger is None:
                return _Q_TRIGGER
            self._answers["trigger"] = trigger
            if trigger == "scheduled":
                self._state = "ASK_CADENCE"
            elif trigger == "quota":
                self._state = "ASK_QUOTA"
            else:
                self._state = "ASK_PERSISTENCE"
            return self.current_question()

        if self._state == "ASK_CADENCE":
            cadence = parse_cadence(text)
            if cadence is None:
                return _Q_CADENCE
            self._answers["cadence"] = cadence
            self._state = "ASK_PERSISTENCE"
            return self.current_question()

        if self._state == "ASK_QUOTA":
            quota = parse_quota(text)
            if quota is None:
                return _Q_QUOTA
            self._answers["quota"] = quota
            self._state = "ASK_PERSISTENCE"
            return self.current_question()

        if self._state == "ASK_PERSISTENCE":
            persistence = parse_persistence(text)
            if persistence is None:
                return _Q_PERSISTENCE
            self._answers["persistence"] = persistence
            self._state = "ASK_NOTIFY"
            return self.current_question()

        if self._state == "ASK_NOTIFY":
            notify = parse_notify(text)
            if notify is None:
                return _Q_NOTIFY
            self._answers["notify"] = notify
            # silent steps run before CONFIRM
            self._answers["executor"] = self._classify_fn(self.task)
            self._answers["tools"] = pick_tools(self.task)
            self._state = "CONFIRM"
            return self.current_question()

        if self._state == "CONFIRM":
            if "yes" in (text or "").lower() or "confirm" in (text or "").lower():
                return WizardStep("Created.", done=True, answers=dict(self._answers))
            # "no" -> restart from the trigger question
            self._state = "ASK_TRIGGER"
            return _Q_TRIGGER

        raise RuntimeError(f"Unknown wizard state: {self._state}")

    def _confirm_step(self) -> WizardStep:
        a = self._answers
        bits = [f"Agent that {a['task']}.", f"Trigger: {a['trigger']}."]
        if a["cadence"]:
            bits.append(f"Every {a['cadence']['interval_sec'] // 60} minutes.")
        if a["quota"]:
            bits.append(f"Collect {a['quota']['limit']} ({a['quota']['criterion']}).")
        bits.append(f"Persistence: {a['persistence']}.")
        bits.append(f"Notify via: {a['notify']}.")
        bits.append(f"Engine: {a['executor']} with tools {a['tools']}.")
        return WizardStep("Here is what I'll create. " + " ".join(bits)
                          + " Say yes to create, or no to start over.")


import yaml
from datetime import datetime
from pathlib import Path

from core.agent_state import AgentState, now_iso


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s]", "", (text or "").lower())
    s = re.sub(r"\s+", "_", s.strip())
    return s[:40] or "agent"


def write_role_yaml(*, roles_dir, slug: str, display_name: str,
                    task: str, tools: List[str]) -> Path:
    """Write a RoleDefinition YAML under roles_dir. Dedupes the filename
    with a numeric suffix if a role of that slug already exists."""
    roles_dir = Path(roles_dir)
    roles_dir.mkdir(parents=True, exist_ok=True)

    final_slug = slug
    path = roles_dir / f"{final_slug}.yml"
    i = 2
    while path.exists():
        final_slug = f"{slug}_{i}"
        path = roles_dir / f"{final_slug}.yml"
        i += 1

    role = {
        "id": final_slug,
        "name": display_name,
        "description": f"Agent that {task}.",
        "responsibilities": [task],
        "autonomous_actions": list(tools),
        "approval_required": [],
        "kpis": [],
        "communication_style": {
            "tone": "concise", "verbosity": "brief", "formality": "neutral",
        },
        "heartbeat_instructions": f"Your task: {task}. "
                                  "Report concise, useful results each run.",
        "sub_roles": [],
        "tools": list(tools),
        "authority_level": 1,
    }
    path.write_text(yaml.safe_dump(role, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return path


def commit(answers: Dict, *, roles_dir, state_store, scheduler,
           multi_agent_system, instance_factory,
           script_path: Optional[str] = None,
           icon: str = "🤖") -> AgentState:
    """Write the role YAML + AgentState, register the AgentInstance, reload
    roles, and arm the scheduler. Returns the new AgentState.

    instance_factory(role_id, display_name) -> AgentInstance is injected so
    tests do not need a real MultiAgentSystem hierarchy.
    """
    task = answers["task"]
    display_name = task[:60].strip().title()
    slug = _slugify(display_name)

    role_path = write_role_yaml(
        roles_dir=roles_dir, slug=slug, display_name=display_name,
        task=task, tools=answers.get("tools") or [],
    )
    role_id = role_path.stem

    instance = instance_factory(role_id, display_name)

    state = AgentState(
        role_id=role_id,
        instance_id=getattr(instance, "id", role_id),
        display_name=display_name,
        icon=icon,
        executor=answers["executor"],
        trigger=answers["trigger"],
        persistence=answers["persistence"],
        notify=answers["notify"],
        status="active",
        created_at=now_iso(),
        script_path=script_path,
        cadence=answers.get("cadence"),
        quota=answers.get("quota"),
    )

    multi_agent_system.reload_roles()
    state_store.upsert(state)
    scheduler.arm(state)
    return state
