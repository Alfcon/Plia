# Multi-Agent System — Phase 2: Executors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the two execution backends (`script_executor`, `tool_loop_executor`) plus the shared `RunResult` type, add the `http_get` tool, and tighten `AgentBuilder`'s output contract — so an agent's task can actually be run.

**Architecture:** A new `core/executors/` package holds `RunResult` (the shared result type) and two runner-factory modules. Each factory returns a callable matching `AgentTaskManager.launch()`'s `runner(*, agent, task, context)` signature. `script_executor` runs a generated `.py` as an isolated subprocess; `tool_loop_executor` drives an Ollama tool-call loop against the existing `function_executor`. A new `http_get` tool is added to `function_executor` for API-driven agents.

**Tech Stack:** Python 3, `subprocess`, `requests`, `dataclasses`, Ollama `/api/chat` tool-calling, `pytest` with `monkeypatch`.

**Spec:** `docs/superpowers/specs/2026-05-14-multi-agent-system-design.md` (Execution model section).

**Depends on:** Phase 1 (`core/agent_state.py`). Uses `core/multi_agent.py` `AgentInstance` / `build_system_prompt` and `core/function_executor.py`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `core/executors/__init__.py` (create) | Package init — re-exports `RunResult` |
| `core/executors/run_result.py` (create) | `RunResult` dataclass + `from_runner_output` normaliser |
| `core/executors/script_executor.py` (create) | `make_script_runner(script_path, timeout_sec)` → runner callable (subprocess) |
| `core/executors/tool_loop_executor.py` (create) | `make_tool_loop_runner(...)` → runner callable (Ollama tool-call loop) |
| `core/function_executor.py` (modify) | Add `http_get` dispatch case + `_http_get` method |
| `core/agent_builder.py` (modify) | Extend `_SYSTEM_PROMPT` to require the `run() -> dict` result shape |
| `tests/test_run_result.py` (create) | `RunResult` + normaliser tests |
| `tests/test_script_executor.py` (create) | Subprocess runner tests with a fake `subprocess.run` |
| `tests/test_tool_loop_executor.py` (create) | Tool-loop tests with stubbed Ollama + `function_executor` |
| `tests/test_http_get.py` (create) | `http_get` tool tests with stubbed `requests.get` |

---

## Task 1: Create the `RunResult` type

**Files:**
- Create: `core/executors/__init__.py`
- Create: `core/executors/run_result.py`
- Create: `tests/test_run_result.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_result.py`:

```python
from core.executors.run_result import RunResult


def test_run_result_to_dict_round_trip():
    r = RunResult(success=True, summary="ok", details="full text",
                  items_found=3, items=[{"title": "x"}], error=None)
    d = r.to_dict()
    assert d == {
        "success": True, "summary": "ok", "details": "full text",
        "items_found": 3, "items": [{"title": "x"}], "error": None,
    }


def test_run_result_defaults():
    r = RunResult(success=False, summary="bad", details="")
    assert r.items_found == 0
    assert r.items == []
    assert r.error is None


def test_from_runner_output_passes_through_run_result():
    r = RunResult(success=True, summary="ok", details="d")
    assert RunResult.from_runner_output(r) is r


def test_from_runner_output_wraps_dict():
    out = {"success": False, "response": "boom"}
    r = RunResult.from_runner_output(out)
    assert r.success is False
    assert "boom" in r.details
    assert r.error == "runner_returned_dict"


def test_from_runner_output_wraps_unexpected_type():
    r = RunResult.from_runner_output(None)
    assert r.success is False
    assert r.error == "runner_returned_dict"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_result.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.executors'`

- [ ] **Step 3: Write minimal implementation**

Create `core/executors/__init__.py`:

```python
"""Executors package — runner backends for Plia live agents."""

from core.executors.run_result import RunResult

__all__ = ["RunResult"]
```

Create `core/executors/run_result.py`:

```python
"""
run_result.py — Shared result type for all agent executors.

Every executor (script or tool-loop) returns a RunResult. The scheduler's
completion callback normalises whatever AgentTaskManager hands back (which
may be a RunResult, or a plain dict if AgentTaskManager caught an exception)
into a RunResult via `from_runner_output`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RunResult:
    success: bool
    summary: str
    details: str
    items_found: int = 0
    items: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_runner_output(cls, output: Any) -> "RunResult":
        """Normalise a runner's return value into a RunResult.

        AgentTaskManager stores whatever the runner returns; on an exception
        it stores {"success": False, "response": str(exc)}. Anything that is
        not already a RunResult is treated as a failure dict.
        """
        if isinstance(output, RunResult):
            return output
        details = ""
        if isinstance(output, dict):
            details = str(output.get("response", output))
        else:
            details = str(output)
        return cls(
            success=False,
            summary="Run did not return a structured result.",
            details=details,
            error="runner_returned_dict",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_result.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/executors/__init__.py core/executors/run_result.py tests/test_run_result.py
git commit -m "feat: add RunResult shared executor result type"
```

---

## Task 2: Add the `http_get` tool to `function_executor`

**Files:**
- Modify: `core/function_executor.py:130-133` (dispatch) and add `_http_get` method
- Create: `tests/test_http_get.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_http_get.py`:

```python
from core.function_executor import executor


class _FakeResponse:
    def __init__(self, status_code, text, url, ok=True):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.ok = ok


def test_http_get_rejects_missing_url():
    result = executor.execute("http_get", {})
    assert result["success"] is False
    assert "url" in result["message"].lower()


def test_http_get_rejects_non_http_scheme():
    result = executor.execute("http_get", {"url": "file:///etc/passwd"})
    assert result["success"] is False


def test_http_get_returns_body_and_status(monkeypatch):
    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        return _FakeResponse(200, "hello world", url, ok=True)

    monkeypatch.setattr("requests.get", fake_get)
    result = executor.execute("http_get", {"url": "https://example.com"})
    assert result["success"] is True
    assert result["data"]["status_code"] == 200
    assert result["data"]["body"] == "hello world"


def test_http_get_caps_body_size(monkeypatch):
    big = "x" * 500_000

    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        return _FakeResponse(200, big, url, ok=True)

    monkeypatch.setattr("requests.get", fake_get)
    result = executor.execute("http_get", {"url": "https://example.com"})
    assert len(result["data"]["body"]) == 100_000


def test_http_get_handles_request_exception(monkeypatch):
    def fake_get(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("requests.get", fake_get)
    result = executor.execute("http_get", {"url": "https://example.com"})
    assert result["success"] is False
    assert "connection refused" in result["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_http_get.py -v`
Expected: FAIL — `execute("http_get", ...)` currently returns `{"success": False, "message": "Unknown function: http_get", ...}`, so `test_http_get_returns_body_and_status` fails.

- [ ] **Step 3: Add the dispatch case**

In `core/function_executor.py`, find the dispatch chain inside `execute()`. The last `elif` before `else` is:

```python
            elif func_name == "mcp_tool_call":
                return self._mcp_tool_call(params)
            else:
                return {"success": False, "message": f"Unknown function: {func_name}", "data": None}
```

Insert a new branch before the `else`:

```python
            elif func_name == "mcp_tool_call":
                return self._mcp_tool_call(params)
            elif func_name == "http_get":
                return self._http_get(params)
            else:
                return {"success": False, "message": f"Unknown function: {func_name}", "data": None}
```

- [ ] **Step 4: Add the `_http_get` method**

In `core/function_executor.py`, add this method to the executor class (place it near the other `_` action methods, e.g. after `_network_tools` or `_mcp_tool_call`):

```python
    def _http_get(self, params: Dict) -> Dict:
        """Read-only HTTP GET. Returns status code + size-capped text body.

        Used by API-driven live agents (GitHub, generic REST). Only http/https
        URLs are allowed; the body is capped at 100 KB of text.
        """
        url = (params.get("url") or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            return {"success": False,
                    "message": "Invalid or missing URL (must be http/https).",
                    "data": None}
        MAX_BODY = 100_000
        try:
            import requests
            headers = {"User-Agent": "Plia-Agent/1.0"}
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            body = (resp.text or "")[:MAX_BODY]
            return {
                "success": bool(resp.ok),
                "message": f"HTTP {resp.status_code} ({len(body)} chars)",
                "data": {
                    "status_code": resp.status_code,
                    "body": body,
                    "url": resp.url,
                },
            }
        except Exception as e:
            return {"success": False, "message": f"HTTP GET failed: {e}", "data": None}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_http_get.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add core/function_executor.py tests/test_http_get.py
git commit -m "feat: add read-only http_get tool to function_executor"
```

---

## Task 3: Build the script executor

**Files:**
- Create: `core/executors/script_executor.py`
- Create: `tests/test_script_executor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_script_executor.py`:

```python
import subprocess

from core.executors.script_executor import make_script_runner
from core.executors.run_result import RunResult


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run(monkeypatch, *, returncode=0, stdout="", stderr="", raises=None,
         script_exists=True):
    monkeypatch.setattr(
        "core.executors.script_executor.Path.exists", lambda self: script_exists
    )

    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        if raises is not None:
            raise raises
        return _FakeCompleted(returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = make_script_runner("/fake/agent.py", timeout_sec=30)
    return runner(agent=object(), task="do thing", context="")


def test_script_runner_parses_last_json_line(monkeypatch):
    stdout = (
        "starting up\n"
        '{"success": true, "summary": "found 2", "details": "d", '
        '"items_found": 2, "items": [{"title": "a"}]}\n'
    )
    result = _run(monkeypatch, stdout=stdout)
    assert isinstance(result, RunResult)
    assert result.success is True
    assert result.summary == "found 2"
    assert result.items_found == 2


def test_script_runner_missing_script(monkeypatch):
    result = _run(monkeypatch, script_exists=False)
    assert result.success is False
    assert result.error == "script_not_found"


def test_script_runner_nonzero_exit(monkeypatch):
    result = _run(monkeypatch, returncode=1, stderr="traceback here")
    assert result.success is False
    assert result.error == "exit_1"
    assert "traceback here" in result.details


def test_script_runner_no_json_output(monkeypatch):
    result = _run(monkeypatch, stdout="just some text, no json\n")
    assert result.success is False
    assert result.error == "no_json"


def test_script_runner_timeout(monkeypatch):
    exc = subprocess.TimeoutExpired(cmd="x", timeout=30)
    result = _run(monkeypatch, raises=exc)
    assert result.success is False
    assert result.error == "timeout"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_script_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.executors.script_executor'`

- [ ] **Step 3: Write minimal implementation**

Create `core/executors/script_executor.py`:

```python
"""
script_executor.py — Runs a generated agent .py file as an isolated subprocess.

make_script_runner(script_path, timeout_sec) returns a callable matching the
AgentTaskManager runner signature: runner(*, agent, task, context) -> RunResult.

The subprocess is invoked as:
    python <script_path> --task "<task>" --context "<context>" --json
and is expected to print a JSON object as its final stdout line, matching:
    {"success", "summary", "details", "items_found", "items"}
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from core.executors.run_result import RunResult


def make_script_runner(script_path: str, timeout_sec: int = 300) -> Callable[..., RunResult]:
    def _runner(*, agent, task: str, context: str) -> RunResult:
        if not Path(script_path).exists():
            return RunResult(
                success=False,
                summary="Agent script missing.",
                details=f"Script not found at: {script_path}",
                error="script_not_found",
            )
        try:
            proc = subprocess.run(
                [sys.executable, script_path,
                 "--task", task or "",
                 "--context", context or "",
                 "--json"],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                success=False,
                summary="Agent timed out.",
                details=f"Subprocess exceeded {timeout_sec}s.",
                error="timeout",
            )
        except Exception as exc:
            return RunResult(
                success=False,
                summary="Agent failed to start.",
                details=str(exc),
                error="executor_internal",
            )

        if proc.returncode != 0:
            return RunResult(
                success=False,
                summary="Agent script exited with an error.",
                details=(proc.stderr or proc.stdout or "")[-2000:],
                error=f"exit_{proc.returncode}",
            )

        last_json = None
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    last_json = json.loads(line)
                except json.JSONDecodeError:
                    continue
        if last_json is None:
            return RunResult(
                success=False,
                summary="Agent produced no result.",
                details="No JSON result line found in script output.",
                error="no_json",
            )

        return RunResult(
            success=bool(last_json.get("success", True)),
            summary=str(last_json.get("summary", "Done.")),
            details=str(last_json.get("details", "")),
            items_found=int(last_json.get("items_found", 0) or 0),
            items=list(last_json.get("items", []) or []),
            error=last_json.get("error"),
        )

    return _runner
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_script_executor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/executors/script_executor.py tests/test_script_executor.py
git commit -m "feat: add subprocess-based script executor"
```

---

## Task 4: Build the tool-loop executor

**Files:**
- Create: `core/executors/tool_loop_executor.py`
- Create: `tests/test_tool_loop_executor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_loop_executor.py`:

```python
import json
import types

import core.executors.tool_loop_executor as tle
from core.executors.run_result import RunResult


class _FakeAgent:
    """Stands in for AgentInstance — only .agent.role is read."""
    class _Inner:
        role = types.SimpleNamespace(
            name="Test Agent",
            description="does testing",
            responsibilities=["test things"],
            tools=["web_search"],
            authority_level=1,
            heartbeat_instructions="run the test task",
        )
    agent = _Inner()


def _stub_ollama(monkeypatch, responses):
    """responses: list of dicts, each becomes one /api/chat reply."""
    calls = {"i": 0}

    class _Resp:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=None):
        payload = responses[calls["i"]]
        calls["i"] += 1
        return _Resp(payload)

    monkeypatch.setattr(tle.requests, "post", fake_post)
    return calls


def test_tool_loop_returns_final_text(monkeypatch):
    _stub_ollama(monkeypatch, [
        {"message": {"content":
            "SUMMARY: found 2 repos\nITEMS_FOUND: 2\nITEMS_JSON: [{\"title\": \"a\"}, {\"title\": \"b\"}]"},
         "prompt_eval_count": 10, "eval_count": 5},
    ])
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="find repos", context="")
    assert isinstance(result, RunResult)
    assert result.success is True
    assert result.items_found == 2
    assert len(result.items) == 2


def test_tool_loop_executes_allowed_tool(monkeypatch):
    _stub_ollama(monkeypatch, [
        {"message": {"tool_calls": [
            {"function": {"name": "web_search", "arguments": {"query": "x"}}}]},
         "prompt_eval_count": 5, "eval_count": 5},
        {"message": {"content": "SUMMARY: done\nITEMS_FOUND: 0\nITEMS_JSON: []"},
         "prompt_eval_count": 5, "eval_count": 5},
    ])
    executed = []
    monkeypatch.setattr(
        tle.function_executor, "execute",
        lambda name, params: executed.append((name, params)) or
        {"success": True, "message": "ok", "data": None})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="find repos", context="")
    assert executed == [("web_search", {"query": "x"})]
    assert result.success is True


def test_tool_loop_denies_disallowed_tool(monkeypatch):
    _stub_ollama(monkeypatch, [
        {"message": {"tool_calls": [
            {"function": {"name": "control_desktop", "arguments": {}}}]},
         "prompt_eval_count": 5, "eval_count": 5},
        {"message": {"content": "SUMMARY: stopped\nITEMS_FOUND: 0\nITEMS_JSON: []"},
         "prompt_eval_count": 5, "eval_count": 5},
    ])
    executed = []
    monkeypatch.setattr(
        tle.function_executor, "execute",
        lambda name, params: executed.append(name) or {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    runner(agent=_FakeAgent(), task="t", context="")
    assert executed == []  # control_desktop never executed


def test_tool_loop_hits_iteration_cap(monkeypatch):
    tool_reply = {"message": {"tool_calls": [
        {"function": {"name": "web_search", "arguments": {"query": "x"}}}]},
        "prompt_eval_count": 1, "eval_count": 1}
    _stub_ollama(monkeypatch, [tool_reply] * 8)
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=3, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.success is True
    assert result.error == "iteration_cap"


def test_tool_loop_hits_token_budget(monkeypatch):
    _stub_ollama(monkeypatch, [
        {"message": {"tool_calls": [
            {"function": {"name": "web_search", "arguments": {}}}]},
         "prompt_eval_count": 9999, "eval_count": 9999},
    ])
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.error == "token_budget"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tool_loop_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.executors.tool_loop_executor'`

- [ ] **Step 3: Write minimal implementation**

Create `core/executors/tool_loop_executor.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tool_loop_executor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add core/executors/tool_loop_executor.py tests/test_tool_loop_executor.py
git commit -m "feat: add LLM tool-loop executor"
```

---

## Task 5: Tighten `AgentBuilder`'s output contract

**Files:**
- Modify: `core/agent_builder.py` (`_SYSTEM_PROMPT`, around lines 390-418)

This makes generated scripts comply with what `script_executor` expects: a `run()` that returns the result dict and a `__main__` block that prints it as JSON when `--json` is passed.

- [ ] **Step 1: Read the current prompt**

Run: `grep -n "_SYSTEM_PROMPT\|run(\*\*kwargs)" core/agent_builder.py`
Expected: confirms `_SYSTEM_PROMPT` is defined around line 390 and rule 3 mentions `run(**kwargs) -> str`.

- [ ] **Step 2: Replace rule 3 and rule 2 in `_SYSTEM_PROMPT`**

In `core/agent_builder.py`, the `_SYSTEM_PROMPT` currently contains these two rules:

```python
    2.  The file must be immediately runnable with  `python <file>.py`  and must
        include a  `if __name__ == "__main__":` block.
    3.  Export a callable  `run(**kwargs) -> str`  at module level so Plia can
        call it programmatically. It must return a human-readable result string.
```

Replace both with:

```python
    2.  The file must be immediately runnable with  `python <file>.py`  and must
        include a  `if __name__ == "__main__":` block. When the script is run
        with a  `--json`  flag, the __main__ block must print exactly one line
        of JSON: the dict returned by run(). It may also accept optional
        `--task <str>`  and  `--context <str>`  flags and forward them to run().
    3.  Export a callable  `run(**kwargs) -> dict`  at module level so Plia can
        call it programmatically. It MUST return a dict with these exact keys:
          {
            "success":     bool,
            "summary":     str,   # one-line human-readable result
            "details":     str,   # full multi-line output
            "items_found": int,   # count of things found this run (0 if N/A)
            "items":       list,  # list of dicts describing findings (may be [])
          }
```

- [ ] **Step 3: Verify the module still imports**

Run: `python -c "import core.agent_builder; print('agent_builder OK')"`
Expected: prints `agent_builder OK` with no traceback.

- [ ] **Step 4: Commit**

```bash
git add core/agent_builder.py
git commit -m "feat: require structured run() dict from AgentBuilder scripts"
```

---

## Task 6: Phase 2 integration check

**Files:** none — verification only.

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v`
Expected: PASS — 9 from Phase 1 plus 20 from Phase 2 (`test_run_result.py` 5, `test_http_get.py` 5, `test_script_executor.py` 5, `test_tool_loop_executor.py` 5) = 29 passed.

- [ ] **Step 2: Verify all new modules import cleanly**

Run: `python -c "from core.executors import RunResult; from core.executors.script_executor import make_script_runner; from core.executors.tool_loop_executor import make_tool_loop_runner; print('executors OK')"`
Expected: prints `executors OK`.

- [ ] **Step 3: Commit (if any fixes were needed)**

If steps 1-2 required fixes, commit them:

```bash
git add -A
git commit -m "fix: Phase 2 integration adjustments"
```

If no fixes were needed, skip this step.

---

## Phase 2 Complete

**Deliverables:**
- `RunResult` shared result type with `from_runner_output` normaliser.
- `http_get` tool in `function_executor` (read-only, size-capped).
- `make_script_runner` — subprocess executor with timeout/exit/no-json/missing-script handling.
- `make_tool_loop_runner` — Ollama tool-call loop with iteration cap, token budget, and tool whitelisting.
- `AgentBuilder` now requires generated scripts to return the structured `run()` dict.
- 29 passing tests total.

**Verification before moving to Phase 3:** `pytest tests/ -v` green, all executor modules import cleanly.

**Next:** Phase 3 (Scheduler) wires `AgentState` + the runner factories together with cron-like timing.
