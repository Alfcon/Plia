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


def test_tool_loop_extracts_items_from_json_envelope(monkeypatch):
    """When the LLM returns a JSON envelope (not the SUMMARY/ITEMS_JSON
    format), we should still extract the items list inside."""
    json_blob = (
        '{"success": true, "message": "Found 3 repos", '
        '"data": {"repositories": ['
        '{"title": "owner/jarvis", "url": "https://github.com/owner/jarvis"},'
        '{"title": "fork/jarvis", "url": "https://github.com/fork/jarvis"},'
        '{"title": "another/repo", "url": "https://github.com/another/repo"}'
        ']}}'
    )
    _stub_ollama(monkeypatch, [
        {"message": {"tool_calls": [{"function": {"name": "web_search",
                                                   "arguments": {"query": "x"}}}]},
         "prompt_eval_count": 1, "eval_count": 1},
        {"message": {"content": json_blob},
         "prompt_eval_count": 1, "eval_count": 1},
    ])
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.items_found == 3
    titles = [i["title"] for i in result.items]
    assert "owner/jarvis" in titles
    # Summary should come from the envelope's message field.
    assert result.summary == "Found 3 repos"


def test_tool_loop_extracts_items_from_fenced_json(monkeypatch):
    """Same as above but the LLM wraps the JSON in ```json fences."""
    json_blob = (
        "```json\n"
        '{"data": {"items": ['
        '{"name": "thing-1", "url": "https://example.com/1"},'
        '{"name": "thing-2", "url": "https://example.com/2"}'
        ']}}\n```'
    )
    _stub_ollama(monkeypatch, [
        {"message": {"tool_calls": [{"function": {"name": "web_search",
                                                   "arguments": {"query": "x"}}}]},
         "prompt_eval_count": 1, "eval_count": 1},
        {"message": {"content": json_blob},
         "prompt_eval_count": 1, "eval_count": 1},
    ])
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.items_found == 2
    assert result.items[0]["name"] == "thing-1"


def test_tool_loop_extracts_markdown_links_from_prose(monkeypatch):
    """Prose-only answers (no ITEMS_JSON) still surface clickable items by
    scraping markdown [title](url) links."""
    prose = (
        "Here are the top results:\n"
        "1. [acme/jarvis](https://github.com/acme/jarvis) — voice assistant\n"
        "2. [foo/bar](https://github.com/foo/bar) — chatbot\n"
        "Both look relevant.\n"
    )
    _stub_ollama(monkeypatch, [
        {"message": {"content": prose},
         "prompt_eval_count": 1, "eval_count": 1},
        # In case the no-tool guard fires, give a fallback that calls the tool.
        {"message": {"tool_calls": [{"function": {"name": "web_search",
                                                   "arguments": {"query": "x"}}}]},
         "prompt_eval_count": 1, "eval_count": 1},
        {"message": {"content": prose},
         "prompt_eval_count": 1, "eval_count": 1},
    ])
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.items_found == 2, f"expected 2 items, got {result.items_found}"
    titles = [i["title"] for i in result.items]
    urls = [i["url"] for i in result.items]
    assert "acme/jarvis" in titles and "foo/bar" in titles
    assert "https://github.com/acme/jarvis" in urls


def test_tool_loop_summary_falls_back_to_first_prose_line(monkeypatch):
    """No SUMMARY: line → summary is the first non-empty line (full, not truncated)."""
    prose = (
        "Here is a long answer about Jarvis-style repos.\n"
        "Details follow with multiple points and **markdown** formatting.\n"
    )
    _stub_ollama(monkeypatch, [
        {"message": {"content": prose},
         "prompt_eval_count": 1, "eval_count": 1},
        {"message": {"tool_calls": [{"function": {"name": "web_search",
                                                   "arguments": {"query": "x"}}}]},
         "prompt_eval_count": 1, "eval_count": 1},
        {"message": {"content": prose},
         "prompt_eval_count": 1, "eval_count": 1},
    ])
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    # First non-blank line of the prose, not truncated at 200 chars.
    assert result.summary == "Here is a long answer about Jarvis-style repos."


def test_tool_loop_nudges_retry_when_no_tool_and_empty(monkeypatch):
    """If the LLM returns 0 items without calling any tools, the loop nudges
    it once. After the nudge it calls a tool, then a final answer is accepted."""
    _stub_ollama(monkeypatch, [
        # Turn 1: model skips tools and returns empty result.
        {"message": {"content": "SUMMARY: nothing\nITEMS_FOUND: 0\nITEMS_JSON: []"},
         "prompt_eval_count": 1, "eval_count": 1},
        # Turn 2 (after nudge): model finally calls the tool.
        {"message": {"tool_calls": [
            {"function": {"name": "web_search", "arguments": {"query": "x"}}}]},
         "prompt_eval_count": 1, "eval_count": 1},
        # Turn 3: model answers with real items.
        {"message": {"content":
            "SUMMARY: found 1\nITEMS_FOUND: 1\nITEMS_JSON: [{\"title\": \"a\", \"url\": \"u\"}]"},
         "prompt_eval_count": 1, "eval_count": 1},
    ])
    monkeypatch.setattr(tle.function_executor, "execute",
                        lambda name, params: {"success": True, "data": []})
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.success is True
    assert result.items_found == 1
    # tool WAS called this time, so no warning marker
    assert result.error is None


def test_tool_loop_flags_no_tool_call_when_items_returned(monkeypatch):
    """If the LLM returns items without calling any tools, we accept the
    result but mark it as likely hallucinated."""
    _stub_ollama(monkeypatch, [
        {"message": {"content":
            "SUMMARY: from memory\nITEMS_FOUND: 1\nITEMS_JSON: [{\"title\": \"fake\", \"url\": \"u\"}]"},
         "prompt_eval_count": 1, "eval_count": 1},
    ])
    runner = tle.make_tool_loop_runner(
        allowed_tools=["web_search"], ollama_url="http://x/api",
        model="m", max_steps=8, token_budget=100_000)
    result = runner(agent=_FakeAgent(), task="t", context="")
    assert result.success is True
    assert result.items_found == 1
    assert result.error == "no_tool_call"
    assert "fabricated" in result.details.lower() or "did not call" in result.details.lower()


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
