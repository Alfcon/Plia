from core.agent_reporting import ResultDispatcher
from core.agent_state import AgentState
from core.executors.run_result import RunResult


def _state(notify, role_id="r1"):
    return AgentState(
        role_id=role_id, instance_id="i1", display_name="GitHub Watcher",
        icon="🔍", executor="tool_loop", trigger="scheduled",
        persistence="persistent", notify=notify, status="active",
        created_at="2026-05-14T10:00:00",
    )


def test_report_always_emits_history_appended():
    d = ResultDispatcher(speak=lambda s: None)
    appended = []
    d.agent_history_appended.connect(appended.append)
    d.report(_state("comm_log"), RunResult(True, "ok", "d", items_found=1))
    assert appended == ["r1"]


def test_report_tts_speaks_summary_on_success():
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    d.report(_state("tts"), RunResult(True, "found 3 repos", "d", items_found=3))
    assert len(spoken) == 1
    assert "found 3 repos" in spoken[0]


def test_report_tts_says_nothing_new_when_empty():
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    d.report(_state("tts"), RunResult(True, "ran", "d", items_found=0))
    assert "nothing new" in spoken[0].lower()


def test_report_tts_announces_failure():
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    d.report(_state("tts"), RunResult(False, "x", "d", error="timeout"))
    assert "failed" in spoken[0].lower()
    assert "timeout" in spoken[0].lower()


def test_report_toast_card_emits_both_signals():
    d = ResultDispatcher(speak=lambda s: None)
    toasts, cards = [], []
    d.show_toast.connect(lambda t, b, ok: toasts.append((t, b, ok)))
    d.dashboard_card_added.connect(cards.append)
    d.report(_state("toast_card"), RunResult(True, "found 2", "d", items_found=2,
                                             items=[{"title": "a"}, {"title": "b"}]))
    assert toasts[0][0] == "GitHub Watcher"
    assert toasts[0][2] is True
    assert cards[0]["role_id"] == "r1"
    assert cards[0]["items_found"] == 2


def test_report_comm_log_emits_with_item_bullets():
    d = ResultDispatcher(speak=lambda s: None)
    logs = []
    d.comm_log_append.connect(lambda rid, title, body: logs.append((rid, title, body)))
    d.report(_state("comm_log"), RunResult(True, "found 1", "d", items_found=1,
                                           items=[{"title": "acme/repo"}]))
    rid, title, body = logs[0]
    assert rid == "r1"
    assert "GitHub Watcher" in title
    assert "acme/repo" in body


def test_report_tts_channel_does_not_emit_toast():
    d = ResultDispatcher(speak=lambda s: None)
    toasts = []
    d.show_toast.connect(lambda *a: toasts.append(a))
    d.report(_state("tts"), RunResult(True, "x", "d"))
    assert toasts == []


def test_report_chat_channel_emits_chat_message():
    d = ResultDispatcher(speak=lambda s: None)
    chats = []
    d.chat_message_append.connect(lambda rid, body: chats.append((rid, body)))
    d.report(_state("chat"), RunResult(True, "found 2 repos", "d", items_found=2,
                                       items=[{"title": "acme/repo"}, {"title": "foo/bar"}]))
    assert len(chats) == 1
    rid, body = chats[0]
    assert rid == "r1"
    assert "GitHub Watcher" in body
    assert "found 2 repos" in body
    assert "acme/repo" in body


def test_report_chat_channel_announces_failure():
    d = ResultDispatcher(speak=lambda s: None)
    chats = []
    d.chat_message_append.connect(lambda rid, body: chats.append(body))
    d.report(_state("chat"), RunResult(False, "x", "d", error="timeout"))
    assert "failed" in chats[0].lower()
    assert "timeout" in chats[0].lower()


def test_report_file_channel_writes_and_emits_path(tmp_path, monkeypatch):
    # Sandbox the output dir so we don't trample ~/.plia_ai/agent_results
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    d = ResultDispatcher(speak=lambda s: None)
    saved = []
    d.file_saved.connect(lambda rid, path: saved.append((rid, path)))
    d.report(_state("file"), RunResult(True, "found 1", "d", items_found=1,
                                       items=[{"title": "acme/repo"}]))
    assert len(saved) == 1
    rid, path = saved[0]
    assert rid == "r1"
    from pathlib import Path
    assert Path(path).exists()
    contents = Path(path).read_text(encoding="utf-8")
    assert "GitHub Watcher" in contents
    assert "found 1" in contents
    assert "acme/repo" in contents


def test_report_file_channel_appends_across_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    d = ResultDispatcher(speak=lambda s: None)
    d.report(_state("file"), RunResult(True, "run 1", "d", items_found=1))
    d.report(_state("file"), RunResult(True, "run 2", "d", items_found=2))
    from pathlib import Path
    log = tmp_path / ".plia_ai" / "agent_results" / "r1.log"
    text = log.read_text(encoding="utf-8")
    assert "run 1" in text and "run 2" in text


def test_report_multi_channel_fans_out_to_each(tmp_path, monkeypatch):
    """notify='tts,chat,file' should dispatch to all three channels."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    spoken = []
    d = ResultDispatcher(speak=spoken.append)
    chats = []
    d.chat_message_append.connect(lambda rid, body: chats.append(body))
    saved = []
    d.file_saved.connect(lambda rid, path: saved.append(path))

    d.report(_state("tts,chat,file"),
             RunResult(True, "found 1", "d", items_found=1,
                       items=[{"title": "acme/repo"}]))

    # All three channels fired exactly once.
    assert len(spoken) == 1
    assert len(chats) == 1
    assert len(saved) == 1
    assert "found 1" in spoken[0]
    assert "found 1" in chats[0]
    from pathlib import Path
    assert Path(saved[0]).exists()
