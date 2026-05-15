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
