# Multi-Agent System — Phase 4: Creation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the wizard that turns "create an agent that does X" into a committed live agent — parsing intent, asking trigger/cadence/quota/persistence/notify, silently classifying the executor and picking tools, then writing the role YAML + `AgentState` and arming the scheduler. Wire the voice path so spoken creation works end to end.

**Architecture:** A new `core/agent_creator.py` holds pure parsers (`parse_intent`, `pick_tools`, the question parsers), an Ollama-backed `classify_executor`, a channel-agnostic `WizardController` state machine, a `commit` function that writes artifacts, and a `VoiceWizardSession` wrapper. `core/voice_assistant.py` gets an early intent intercept plus an `active_wizard` slot so multi-turn voice answers route to the wizard. `gui/handlers.py` routes chat-detected create intents into the same `WizardController`.

**Tech Stack:** Python 3, `re`, `yaml` (already a dependency via `core/multi_agent.py`), Ollama `/api/chat`, PySide6 signals, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-14-multi-agent-system-design.md` (Creation pipeline section).

**Depends on:** Phases 1-3. Uses `core/agent_state.py`, `core/agent_scheduler.py`, `core/multi_agent.py`, `config.py` (`OLLAMA_URL`, `RESPONDER_MODEL`).

---

## File Structure

| Path | Responsibility |
|---|---|
| `core/agent_creator.py` (create) | `parse_intent`, `pick_tools`, `classify_executor`, question parsers, `WizardController`, `commit`, `write_role_yaml`, `VoiceWizardSession` |
| `core/voice_assistant.py` (modify) | Early create-intent intercept + `active_wizard` multi-turn routing |
| `gui/handlers.py` (modify) | Route chat create-intent into `WizardController` (chat adapter is completed in Phase 5) |
| `tests/test_intent_and_tools.py` (create) | `parse_intent` + `pick_tools` tests |
| `tests/test_classify_executor.py` (create) | `classify_executor` tests with stubbed Ollama |
| `tests/test_question_parsers.py` (create) | `parse_trigger` / `parse_persistence` / `parse_notify` / `parse_quota` tests |
| `tests/test_wizard_controller.py` (create) | `WizardController` state-machine tests |
| `tests/test_commit.py` (create) | `commit` + `write_role_yaml` artifact tests |

---

## Task 1: `parse_intent` and `pick_tools`

**Files:**
- Create: `core/agent_creator.py`
- Create: `tests/test_intent_and_tools.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intent_and_tools.py`:

```python
from core.agent_creator import parse_intent, pick_tools


def test_parse_intent_extracts_task():
    assert parse_intent("create an agent that watches GitHub for related projects") \
        == "watches GitHub for related projects"
    assert parse_intent("make me an agent to summarise my emails") \
        == "summarise my emails"


def test_parse_intent_ignores_non_create_phrases():
    assert parse_intent("what's the weather today") is None
    assert parse_intent("open spotify") is None


def test_parse_intent_rejects_too_short_task():
    # under 6 words and no clear verb-object -> treated as too vague
    assert parse_intent("create an agent that go") is None


def test_pick_tools_github():
    tools = pick_tools("watches GitHub repos for new pull requests")
    assert "web_search" in tools
    assert "http_get" in tools


def test_pick_tools_email_is_read_only():
    tools = pick_tools("summarise my email inbox")
    assert tools == ["read_emails"]


def test_pick_tools_default_is_web_search():
    assert pick_tools("tell me interesting facts") == ["web_search"]


def test_pick_tools_flags_dangerous_verbs():
    tools = pick_tools("delete old files from my downloads folder")
    # dangerous tasks get no auto-granted tools — user must opt in explicitly
    assert tools == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_intent_and_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agent_creator'`

- [ ] **Step 3: Write minimal implementation**

Create `core/agent_creator.py`:

```python
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
            if len(task.split()) < 4:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_intent_and_tools.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_creator.py tests/test_intent_and_tools.py
git commit -m "feat: add parse_intent and pick_tools for agent creation"
```

---

## Task 2: `classify_executor`

**Files:**
- Modify: `core/agent_creator.py`
- Create: `tests/test_classify_executor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_classify_executor.py`:

```python
import core.agent_creator as ac


class _Resp:
    def __init__(self, content):
        self._content = content
    def raise_for_status(self):
        pass
    def json(self):
        return {"message": {"content": self._content}}


def test_classify_returns_script(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("script"))
    assert ac.classify_executor("download files to a folder",
                                "http://x/api", "m") == "script"


def test_classify_returns_tool_loop(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("tool_loop"))
    assert ac.classify_executor("research and compare LLM repos",
                                "http://x/api", "m") == "tool_loop"


def test_classify_tolerates_extra_text(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("I think this is: script."))
    assert ac.classify_executor("x", "http://x/api", "m") == "script"


def test_classify_defaults_to_tool_loop_on_unparseable(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("no idea"))
    assert ac.classify_executor("x", "http://x/api", "m") == "tool_loop"


def test_classify_defaults_to_tool_loop_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(ac.requests, "post", boom)
    assert ac.classify_executor("x", "http://x/api", "m") == "tool_loop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_classify_executor.py -v`
Expected: FAIL with `AttributeError: module 'core.agent_creator' has no attribute 'requests'`

- [ ] **Step 3: Write minimal implementation**

In `core/agent_creator.py`, add `import requests` to the imports at the top (below `import re`):

```python
import re
import requests
from typing import List, Optional
```

Then append to `core/agent_creator.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_classify_executor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_creator.py tests/test_classify_executor.py
git commit -m "feat: add classify_executor for script-vs-tool-loop choice"
```

---

## Task 3: Question parsers

**Files:**
- Modify: `core/agent_creator.py`
- Create: `tests/test_question_parsers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_question_parsers.py`:

```python
from core.agent_creator import (
    parse_trigger, parse_persistence, parse_notify, parse_quota,
)


def test_parse_trigger():
    assert parse_trigger("scheduled") == "scheduled"
    assert parse_trigger("run it on a schedule") == "scheduled"
    assert parse_trigger("on demand") == "on_demand"
    assert parse_trigger("only when I ask") == "on_demand"
    assert parse_trigger("quota") == "quota"
    assert parse_trigger("until it finds enough") == "quota"
    assert parse_trigger("banana") is None


def test_parse_persistence():
    assert parse_persistence("persistent") == "persistent"
    assert parse_persistence("survive restarts") == "persistent"
    assert parse_persistence("keep it across restarts") == "persistent"
    assert parse_persistence("session only") == "session"
    assert parse_persistence("just this session") == "session"
    assert parse_persistence("maybe") is None


def test_parse_notify():
    assert parse_notify("speak") == "tts"
    assert parse_notify("read it aloud") == "tts"
    assert parse_notify("toast") == "toast_card"
    assert parse_notify("dashboard card") == "toast_card"
    assert parse_notify("communication log") == "comm_log"
    assert parse_notify("just log it") == "comm_log"
    assert parse_notify("hmm") is None


def test_parse_quota():
    assert parse_quota("top 10") == {"limit": 10, "criterion": "top_rated"}
    assert parse_quota("the top 5 rated") == {"limit": 5, "criterion": "top_rated"}
    assert parse_quota("just 20") == {"limit": 20, "criterion": "any"}
    assert parse_quota("find 3 things") == {"limit": 3, "criterion": "any"}
    assert parse_quota("lots") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_question_parsers.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_trigger'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_creator.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_question_parsers.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_creator.py tests/test_question_parsers.py
git commit -m "feat: add wizard question parsers"
```

---

## Task 4: `WizardController` state machine

**Files:**
- Modify: `core/agent_creator.py`
- Create: `tests/test_wizard_controller.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wizard_controller.py`:

```python
from core.agent_creator import WizardController, WizardStep


def make_wizard(task="watches GitHub for related projects"):
    # classify_fn is injected so no Ollama call happens in tests
    return WizardController(task, classify_fn=lambda t: "tool_loop")


def test_wizard_first_question_is_trigger():
    w = make_wizard()
    step = w.current_question()
    assert isinstance(step, WizardStep)
    assert "schedul" in step.question.lower()
    assert step.done is False


def test_wizard_scheduled_path_collects_cadence():
    w = make_wizard()
    w.answer("scheduled")
    step = w.current_question()
    assert "how often" in step.question.lower()
    w.answer("every 6 hours")          # cadence
    w.answer("persistent")             # persistence
    w.answer("communication log")      # notify
    step = w.answer("yes")             # confirm
    assert step.done is True
    answers = step.answers
    assert answers["trigger"] == "scheduled"
    assert answers["cadence"]["interval_sec"] == 21600
    assert answers["persistence"] == "persistent"
    assert answers["notify"] == "comm_log"
    assert answers["executor"] == "tool_loop"
    assert answers["tools"] == ["web_search", "http_get"]


def test_wizard_quota_path_collects_quota():
    w = make_wizard()
    w.answer("quota")
    step = w.current_question()
    assert "how many" in step.question.lower()
    w.answer("top 10")
    w.answer("session only")
    w.answer("speak")
    step = w.answer("yes")
    assert step.done is True
    assert step.answers["trigger"] == "quota"
    assert step.answers["quota"] == {"limit": 10, "criterion": "top_rated"}
    assert step.answers["persistence"] == "session"
    assert step.answers["notify"] == "tts"


def test_wizard_on_demand_skips_cadence_and_quota():
    w = make_wizard()
    w.answer("on demand")
    step = w.current_question()
    assert "survive restarts" in step.question.lower() \
        or "persist" in step.question.lower()
    w.answer("persistent")
    w.answer("toast")
    step = w.answer("yes")
    assert step.done is True
    assert step.answers["trigger"] == "on_demand"
    assert step.answers["cadence"] is None
    assert step.answers["quota"] is None


def test_wizard_reasks_on_unparseable_answer():
    w = make_wizard()
    step = w.answer("banana")
    assert step.done is False
    assert "schedul" in step.question.lower()  # still on trigger question


def test_wizard_cancel():
    w = make_wizard()
    step = w.answer("cancel")
    assert step.cancelled is True
    assert step.done is True


def test_wizard_confirm_no_restarts_at_trigger():
    w = make_wizard()
    w.answer("on demand")
    w.answer("persistent")
    w.answer("toast")
    step = w.answer("no")
    assert step.done is False
    assert "schedul" in step.question.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wizard_controller.py -v`
Expected: FAIL with `ImportError: cannot import name 'WizardController'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_creator.py`:

```python
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
            quota["progress"] = 0
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wizard_controller.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_creator.py tests/test_wizard_controller.py
git commit -m "feat: add WizardController creation state machine"
```

---

## Task 5: `write_role_yaml` and `commit`

**Files:**
- Modify: `core/agent_creator.py`
- Create: `tests/test_commit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_commit.py`:

```python
import yaml

from core.agent_creator import write_role_yaml, commit
from core.agent_state import AgentState, AgentStateStore


def test_write_role_yaml_creates_valid_file(tmp_path):
    path = write_role_yaml(
        roles_dir=tmp_path,
        slug="github_watcher",
        display_name="GitHub Watcher",
        task="watches GitHub for related projects",
        tools=["web_search", "http_get"],
    )
    assert path.exists()
    raw = yaml.safe_load(path.read_text())
    assert raw["id"] == "github_watcher"
    assert raw["name"] == "GitHub Watcher"
    assert raw["tools"] == ["web_search", "http_get"]
    assert raw["authority_level"] == 1
    assert "watches GitHub" in raw["heartbeat_instructions"]


def test_write_role_yaml_dedupes_slug(tmp_path):
    write_role_yaml(roles_dir=tmp_path, slug="dup", display_name="Dup",
                    task="does a thing here", tools=["web_search"])
    path2 = write_role_yaml(roles_dir=tmp_path, slug="dup", display_name="Dup",
                            task="does a thing here", tools=["web_search"])
    assert path2.stem == "dup_2"


def test_commit_writes_state_and_arms_scheduler(tmp_path):
    store = AgentStateStore(path=tmp_path / "state.json")
    armed = []

    class FakeScheduler:
        def arm(self, state):
            armed.append(state.role_id)

    class FakeInstance:
        id = "inst-1"

    class FakeMAS:
        def __init__(self):
            self.reloaded = False
        def reload_roles(self):
            self.reloaded = True
        def _add(self):
            pass

    answers = {
        "task": "watches GitHub for related projects",
        "trigger": "scheduled",
        "cadence": {"interval_sec": 21600, "anchor_iso": None},
        "quota": None,
        "persistence": "persistent",
        "notify": "comm_log",
        "executor": "tool_loop",
        "tools": ["web_search", "http_get"],
    }
    mas = FakeMAS()
    state = commit(
        answers,
        roles_dir=tmp_path,
        state_store=store,
        scheduler=FakeScheduler(),
        multi_agent_system=mas,
        instance_factory=lambda role_id, display_name: FakeInstance(),
        script_path=None,
    )
    assert isinstance(state, AgentState)
    assert state.trigger == "scheduled"
    assert state.executor == "tool_loop"
    assert state.persistence == "persistent"
    assert store.get(state.role_id) is not None
    assert armed == [state.role_id]
    assert mas.reloaded is True
    # role yaml was written
    assert (tmp_path / f"{state.role_id}.yml").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_commit.py -v`
Expected: FAIL with `ImportError: cannot import name 'write_role_yaml'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_creator.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_commit.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_creator.py tests/test_commit.py
git commit -m "feat: add write_role_yaml and commit for agent creation"
```

---

## Task 6: `VoiceWizardSession` wrapper

**Files:**
- Modify: `core/agent_creator.py`
- Create: `tests/test_voice_wizard_session.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_voice_wizard_session.py`:

```python
from core.agent_creator import VoiceWizardSession


def test_voice_session_speaks_first_question_on_start():
    spoken = []
    done = []
    cancelled = []
    sess = VoiceWizardSession(
        task="watches GitHub for related projects",
        classify_fn=lambda t: "tool_loop",
        speak=spoken.append,
        on_done=done.append,
        on_cancel=lambda: cancelled.append(True),
    )
    sess.start()
    assert len(spoken) == 1
    assert "schedul" in spoken[0].lower()


def test_voice_session_walks_to_completion():
    spoken = []
    done = []
    sess = VoiceWizardSession(
        task="watches GitHub for related projects",
        classify_fn=lambda t: "tool_loop",
        speak=spoken.append,
        on_done=done.append,
        on_cancel=lambda: None,
    )
    sess.start()
    sess.answer("on demand")
    sess.answer("persistent")
    sess.answer("communication log")
    sess.answer("yes")
    assert len(done) == 1
    assert done[0]["trigger"] == "on_demand"
    assert sess.finished is True


def test_voice_session_cancel():
    cancelled = []
    sess = VoiceWizardSession(
        task="watches GitHub for related projects",
        classify_fn=lambda t: "tool_loop",
        speak=lambda s: None,
        on_done=lambda a: None,
        on_cancel=lambda: cancelled.append(True),
    )
    sess.start()
    sess.answer("cancel")
    assert cancelled == [True]
    assert sess.finished is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_voice_wizard_session.py -v`
Expected: FAIL with `ImportError: cannot import name 'VoiceWizardSession'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/agent_creator.py`:

```python
class VoiceWizardSession:
    """Wraps WizardController for spoken multi-turn use.

    The owner (VoiceAssistant) calls start() once, then routes every
    subsequent utterance to answer(text) until `finished` is True.
    """

    def __init__(self, *, task: str, classify_fn: Callable[[str], str],
                 speak: Callable[[str], None],
                 on_done: Callable[[Dict], None],
                 on_cancel: Callable[[], None]):
        self._wizard = WizardController(task, classify_fn=classify_fn)
        self._speak = speak
        self._on_done = on_done
        self._on_cancel = on_cancel
        self.finished = False

    def start(self) -> None:
        step = self._wizard.current_question()
        self._speak(step.question)

    def answer(self, text: str) -> None:
        if self.finished:
            return
        step = self._wizard.answer(text)
        if step.cancelled:
            self.finished = True
            self._speak("Cancelled.")
            self._on_cancel()
            return
        if step.done:
            self.finished = True
            self._on_done(step.answers)
            return
        self._speak(step.question)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_voice_wizard_session.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add core/agent_creator.py tests/test_voice_wizard_session.py
git commit -m "feat: add VoiceWizardSession for spoken multi-turn creation"
```

---

## Task 7: Wire the voice intercept into `VoiceAssistant`

**Files:**
- Modify: `core/voice_assistant.py` (`__init__`, `_on_speech`, `_process_query`)

This adds an `active_wizard` slot. When a wizard is active, spoken text routes to it; otherwise a create-intent in `_process_query` starts one.

- [ ] **Step 1: Add the `active_wizard` slot**

In `core/voice_assistant.py`, find `VoiceAssistant.__init__`. After the line `self.current_session_id = None`, add:

```python
        self.active_wizard = None  # VoiceWizardSession while a creation wizard is running
```

- [ ] **Step 2: Route speech to an active wizard**

In `core/voice_assistant.py`, find `_on_speech`. After the early whitespace cleanup block (after the second `if not text: return`) and BEFORE the "read option N" intercept, add:

```python
        # ── Active creation wizard — route answers to it ─────────────────
        if self.active_wizard is not None and not self.active_wizard.finished:
            self.speech_recognized.emit(text)
            self.active_wizard.answer(text)
            if self.active_wizard.finished:
                self.active_wizard = None
            self.processing_finished.emit()
            return
```

- [ ] **Step 3: Add the create-intent intercept in `_process_query`**

In `core/voice_assistant.py`, find `_process_query`. The method starts with:

```python
    def _process_query(self, user_text: str):
        """Process user query through the pipeline."""
        try:
            text_lower = user_text.lower().strip()
```

Immediately after the `text_lower = user_text.lower().strip()` line, insert:

```python
            # ── Create-agent intent — start the creation wizard ──────────
            from core.agent_creator import parse_intent
            _agent_task = parse_intent(user_text)
            if _agent_task:
                self._start_agent_wizard(_agent_task)
                return
```

- [ ] **Step 4: Add the `_start_agent_wizard` method**

In `core/voice_assistant.py`, add this method to the `VoiceAssistant` class (place it after `_process_query`, before `_handle_weather_query`):

```python
    def _start_agent_wizard(self, task: str):
        """Begin a spoken agent-creation wizard for `task`."""
        from core.agent_creator import VoiceWizardSession, commit
        from core.agent_scheduler import AgentScheduler  # noqa: F401  (type ref)
        from config import OLLAMA_URL, RESPONDER_MODEL

        def _classify(t: str) -> str:
            from core.agent_creator import classify_executor
            model = app_settings.get("models.chat", RESPONDER_MODEL)
            return classify_executor(t, OLLAMA_URL, model)

        def _on_done(answers: dict):
            # Phase 5 wires the real scheduler/dispatcher here. For now the
            # wizard collects answers and confirms verbally; full commit is
            # completed once app-level wiring exists.
            tts.queue_sentence(
                f"Agent configured to {answers['task']}. "
                "It will appear in your Active Agents tab."
            )
            self._pending_agent_answers = answers

        def _on_cancel():
            tts.queue_sentence("Agent creation cancelled.")

        self.active_wizard = VoiceWizardSession(
            task=task,
            classify_fn=_classify,
            speak=tts.queue_sentence,
            on_done=_on_done,
            on_cancel=_on_cancel,
        )
        self.active_wizard.start()
        self.processing_finished.emit()
```

> Note: `_on_done` stores `answers` on `self._pending_agent_answers` rather than calling `commit()` directly. The full `commit()` call needs the app-level scheduler + `AgentStateStore` + `multi_agent_system` instances, which are constructed and wired in Phase 5 Task (App wiring). Phase 5 replaces this `_on_done` body with the real `commit()` call.

- [ ] **Step 5: Verify the module imports**

Run: `python -c "import core.voice_assistant; print('voice_assistant OK')"`
Expected: prints `voice_assistant OK` with no traceback.

- [ ] **Step 6: Commit**

```bash
git add core/voice_assistant.py
git commit -m "feat: wire create-agent wizard intercept into VoiceAssistant"
```

---

## Task 8: Route chat create-intent into the wizard

**Files:**
- Modify: `gui/handlers.py` (around lines 116-130, the existing `parse_create_intent` block)

The existing chat handler already detects `agent_registry.parse_create_intent`. We extend it: if the new `core.agent_creator.parse_intent` also matches (i.e. this is a live-agent request), emit a signal carrying the task so Phase 5's `CreationWizardDialog` can open. Until Phase 5 builds that dialog, the handler falls back to the existing behaviour.

- [ ] **Step 1: Add the import**

In `gui/handlers.py`, near the top with the other `core` imports (the file already has `from core.agent_registry import agent_registry` at line 17), add:

```python
from core.agent_creator import parse_intent as parse_live_agent_intent
```

- [ ] **Step 2: Add a signal for the live-agent wizard**

In `gui/handlers.py`, find the `ChatWorker` signal declarations (the block around line 61 with `build_agent_signal = Signal(str)`). Add:

```python
    live_agent_wizard_signal = Signal(str)   # task string for the live-agent wizard
```

- [ ] **Step 3: Branch the create-intent handling**

In `gui/handlers.py`, find the existing dynamic agent creation block (around lines 116-130):

```python
            # ── Dynamic Agent Creation ────────────────────────────────────
            # Check if the user is asking to create a custom agent BEFORE
            # sending to the Function Gemma router. This avoids misrouting.
            intent = agent_registry.parse_create_intent(self.user_text)
            if intent:
                self.status.emit("Creating agent…")
                # Signal the UI thread to open the Create Agent dialog
                self.create_agent_signal.emit(intent)
                self.simple_response.emit(
                    f"Sure! I've opened the Create Agent dialog pre-filled for "
                    f"'{intent['display_name']}'. Check the Agents tab to review "
                    f"and confirm — you can edit the name, description, and system "
                    f"prompt before creating it."
                )
                return
```

Replace it with:

```python
            # ── Dynamic Agent Creation ────────────────────────────────────
            # Check if the user is asking to create an agent BEFORE sending to
            # the Function Gemma router. A "live agent" request (schedulable
            # worker) goes through the new creation wizard; the legacy
            # prompt-only path stays as a fallback.
            live_task = parse_live_agent_intent(self.user_text)
            if live_task:
                self.status.emit("Starting agent creation wizard…")
                self.live_agent_wizard_signal.emit(live_task)
                self.simple_response.emit(
                    f"Let's set up a live agent to {live_task}. "
                    "I've opened the creation wizard — it'll ask a few quick "
                    "questions about scheduling and notifications."
                )
                return

            intent = agent_registry.parse_create_intent(self.user_text)
            if intent:
                self.status.emit("Creating agent…")
                # Signal the UI thread to open the Create Agent dialog
                self.create_agent_signal.emit(intent)
                self.simple_response.emit(
                    f"Sure! I've opened the Create Agent dialog pre-filled for "
                    f"'{intent['display_name']}'. Check the Agents tab to review "
                    f"and confirm — you can edit the name, description, and system "
                    f"prompt before creating it."
                )
                return
```

- [ ] **Step 4: Verify the module imports**

Run: `python -c "import gui.handlers; print('handlers OK')"`
Expected: prints `handlers OK` with no traceback.

> Note: `live_agent_wizard_signal` is emitted but not yet connected to anything — Phase 5 connects it to the `CreationWizardDialog`. An unconnected signal emit is a no-op, so chat still works.

- [ ] **Step 5: Commit**

```bash
git add gui/handlers.py
git commit -m "feat: route chat create-intent into live-agent wizard signal"
```

---

## Task 9: Phase 4 integration check

**Files:** none — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS — 60 from Phases 1-3 plus Phase 4:
`test_intent_and_tools.py` (7), `test_classify_executor.py` (5), `test_question_parsers.py` (4), `test_wizard_controller.py` (7), `test_commit.py` (3), `test_voice_wizard_session.py` (3) = 29 new → 89 passed total.

- [ ] **Step 2: Verify all modified modules import cleanly**

Run: `python -c "import core.agent_creator, core.voice_assistant, gui.handlers; print('phase 4 imports OK')"`
Expected: prints `phase 4 imports OK`.

- [ ] **Step 3: Commit (if any fixes were needed)**

If steps 1-2 required fixes, commit them:

```bash
git add -A
git commit -m "fix: Phase 4 integration adjustments"
```

If no fixes were needed, skip this step.

---

## Phase 4 Complete

**Deliverables:**
- `parse_intent`, `pick_tools` — pure intent + tool-whitelist helpers.
- `classify_executor` — Ollama-backed script-vs-tool-loop classifier with safe default.
- `parse_trigger` / `parse_persistence` / `parse_notify` / `parse_quota` — question parsers.
- `WizardController` — channel-agnostic creation state machine.
- `write_role_yaml` + `commit` — artifact writers that arm the scheduler.
- `VoiceWizardSession` — spoken multi-turn wrapper.
- `VoiceAssistant` intercepts create-intent and runs the spoken wizard.
- `gui/handlers.py` emits `live_agent_wizard_signal` for chat create-intent.
- 89 passing tests total.

**Verification before moving to Phase 5:** `pytest tests/ -v` green, all modified modules import cleanly.

**Known stub:** `VoiceAssistant._start_agent_wizard._on_done` currently stores answers on `self._pending_agent_answers` instead of calling `commit()`. Phase 5 replaces it with a real `commit()` once the app-level scheduler + store + dispatcher are constructed.

**Next:** Phase 5 (Reporting + GUI) builds `ResultDispatcher`, the Live Agents tab section, the editor tabs, dashboard cards, the chat `CreationWizardDialog`, and the app-level wiring that makes `commit()` real.
