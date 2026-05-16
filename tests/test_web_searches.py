"""Tests for the web_searches notify channel + log."""

from core.agent_creator import parse_notify_multi
from core.agent_reporting import ResultDispatcher
from core.agent_state import AgentState
from core.executors.run_result import RunResult


def _state(notify, role_id="r1"):
    return AgentState(
        role_id=role_id, instance_id="i1", display_name="Test Agent",
        icon="🔎", executor="tool_loop", trigger="on_demand",
        persistence="persistent", notify=notify, status="active",
        created_at="2026-05-16T10:00:00",
    )


def test_parse_notify_multi_recognises_web_searches():
    assert parse_notify_multi("web searches") == "web_searches"
    assert parse_notify_multi("search results") == "web_searches"
    assert parse_notify_multi("post to web searches") == "web_searches"


def test_parse_notify_multi_combines_web_searches_with_other_channels():
    out = parse_notify_multi("speak and post to web searches")
    # Order matters in our impl: file > web_searches > chat > tts > toast > comm_log
    assert "web_searches" in out
    assert "tts" in out


def test_web_searches_channel_appends_to_log(tmp_path, monkeypatch):
    """Verify the dispatcher routes to the WebSearchLog."""
    # Sandbox the log path so we don't pollute the real ~/.plia_ai dir.
    import core.web_search_log as wsl
    sandbox = tmp_path / "web_searches.json"
    fresh_log = wsl.WebSearchLog(path=sandbox)
    # Force the module-level log singleton (used by the dispatcher) to point
    # at our sandbox copy.
    monkeypatch.setattr(wsl, "log", fresh_log)

    d = ResultDispatcher(speak=lambda s: None)
    payloads = []
    d.web_search_logged.connect(payloads.append)

    d.report(
        _state("web_searches"),
        RunResult(True, "github JARVIS projects", "details",
                  items_found=2,
                  items=[
                      {"title": "jarvis-ai", "url": "https://github.com/topics/jarvis-ai",
                       "body": "topic"},
                      {"title": "OpenJarvis", "url": "https://open-jarvis.github.io"},
                  ]),
    )

    entries = fresh_log.all()
    assert len(entries) == 1
    e = entries[0]
    assert e["agent_name"] == "Test Agent"
    assert e["query"] == "github JARVIS projects"
    assert len(e["items"]) == 2
    assert e["items"][0]["title"] == "jarvis-ai"
    assert e["items"][0]["url"] == "https://github.com/topics/jarvis-ai"
    # The signal fired with the same payload
    assert len(payloads) == 1
    assert payloads[0]["query"] == "github JARVIS projects"


def test_web_searches_log_caps_size(tmp_path):
    """WebSearchLog caps at MAX_ENTRIES to avoid unbounded growth."""
    from core.web_search_log import WebSearchLog, MAX_ENTRIES

    log = WebSearchLog(path=tmp_path / "ws.json")
    # Insert MAX_ENTRIES + 5 and ensure the oldest 5 are dropped.
    for i in range(MAX_ENTRIES + 5):
        log.add(role_id=f"r{i}", agent_name=f"A{i}",
                query=f"q{i}", items=[])
    all_entries = log.all()
    assert len(all_entries) == MAX_ENTRIES
    # Oldest dropped → first stored entry is from i=5.
    assert all_entries[0]["query"] == "q5"
    assert all_entries[-1]["query"] == f"q{MAX_ENTRIES + 4}"


def test_web_searches_log_remove_single_entry(tmp_path):
    """remove(entry_id) drops just that entry and persists the result."""
    from core.web_search_log import WebSearchLog

    log = WebSearchLog(path=tmp_path / "ws.json")
    e1 = log.add(role_id="a", agent_name="A", query="q1", items=[])
    e2 = log.add(role_id="a", agent_name="A", query="q2", items=[])
    e3 = log.add(role_id="a", agent_name="A", query="q3", items=[])
    assert e1["id"] and e2["id"] and e3["id"]

    removed_ids = []
    log.entry_removed.connect(removed_ids.append)

    assert log.remove(e2["id"]) is True
    queries = [e["query"] for e in log.all()]
    assert queries == ["q1", "q3"]
    assert removed_ids == [e2["id"]]

    # Removing a non-existent id is a no-op.
    assert log.remove("not-a-real-id") is False

    # Persistence: reloading reads back the trimmed list.
    log2 = WebSearchLog(path=tmp_path / "ws.json")
    assert [e["query"] for e in log2.all()] == ["q1", "q3"]


def test_web_searches_log_backfills_ids_on_load(tmp_path):
    """Old entries (written before the id field) get ids assigned on load."""
    import json
    path = tmp_path / "ws.json"
    path.write_text(json.dumps([
        {"ts": "2026-05-16T01:00:00", "role_id": "r", "agent_name": "A",
         "query": "old", "items": []},
    ]))
    from core.web_search_log import WebSearchLog
    log = WebSearchLog(path=path)
    entries = log.all()
    assert len(entries) == 1
    assert entries[0].get("id")  # backfilled


def test_web_searches_log_persists_across_instances(tmp_path):
    """Reloading a WebSearchLog from disk recovers all entries."""
    from core.web_search_log import WebSearchLog

    path = tmp_path / "ws.json"
    log1 = WebSearchLog(path=path)
    log1.add(role_id="a", agent_name="A", query="q1",
             items=[{"title": "x", "url": "u"}])
    log1.add(role_id="a", agent_name="A", query="q2", items=[])

    log2 = WebSearchLog(path=path)
    assert [e["query"] for e in log2.all()] == ["q1", "q2"]
