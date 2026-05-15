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
    assert parse_notify("chat") == "chat"
    assert parse_notify("post to chat") == "chat"
    assert parse_notify("save to file") == "file"
    assert parse_notify("write to file") == "file"
    assert parse_notify("just save it") == "file"
    assert parse_notify("hmm") is None


def test_parse_quota():
    assert parse_quota("top 10") == {"limit": 10, "criterion": "top_rated"}
    assert parse_quota("the top 5 rated") == {"limit": 5, "criterion": "top_rated"}
    assert parse_quota("just 20") == {"limit": 20, "criterion": "any"}
    assert parse_quota("find 3 things") == {"limit": 3, "criterion": "any"}
    assert parse_quota("lots") is None
