"""Tests for the MCP server config CRUD helper."""

from core import mcp_config


def test_load_servers_from_missing_file_returns_empty(tmp_path):
    path = tmp_path / "mcp.json"
    assert mcp_config.load_servers(path) == []


def test_round_trip_save_and_load(tmp_path):
    path = tmp_path / "mcp.json"
    payload = [
        {"id": "a", "transport": "stdio", "command": "/bin/echo",
         "args": ["hello"], "env": {"X": "1"},
         "connect_timeout_seconds": 10.0, "call_timeout_seconds": 60.0},
    ]
    mcp_config.save_servers(payload, path)
    loaded = mcp_config.load_servers(path)
    assert loaded == payload


def test_add_server_rejects_missing_required_fields(tmp_path):
    path = tmp_path / "mcp.json"
    assert mcp_config.add_server({"id": "", "command": "x"}, path) is False
    assert mcp_config.add_server({"id": "x", "command": ""}, path) is False
    assert mcp_config.load_servers(path) == []


def test_add_server_appends_and_rejects_duplicates(tmp_path):
    path = tmp_path / "mcp.json"
    assert mcp_config.add_server(
        {"id": "fs", "command": "/usr/bin/python", "args": ["-m", "mcp_server_fs"]},
        path,
    ) is True
    assert mcp_config.add_server(
        {"id": "fs", "command": "/elsewhere"},
        path,
    ) is False  # duplicate id
    servers = mcp_config.load_servers(path)
    assert len(servers) == 1
    assert servers[0]["id"] == "fs"
    assert servers[0]["transport"] == "stdio"   # filled by _normalise
    assert servers[0]["args"] == ["-m", "mcp_server_fs"]


def test_update_server_replaces_existing_entry(tmp_path):
    path = tmp_path / "mcp.json"
    mcp_config.add_server({"id": "g", "command": "old-cmd"}, path)
    ok = mcp_config.update_server(
        "g",
        {"id": "g", "command": "new-cmd", "args": ["--flag"], "env": {"K": "v"}},
        path,
    )
    assert ok is True
    e = mcp_config.get_server("g", path)
    assert e["command"] == "new-cmd"
    assert e["args"] == ["--flag"]
    assert e["env"] == {"K": "v"}


def test_update_server_unknown_id_is_noop(tmp_path):
    path = tmp_path / "mcp.json"
    assert mcp_config.update_server("nope", {"command": "x"}, path) is False


def test_remove_server(tmp_path):
    path = tmp_path / "mcp.json"
    mcp_config.add_server({"id": "a", "command": "x"}, path)
    mcp_config.add_server({"id": "b", "command": "y"}, path)
    assert mcp_config.remove_server("a", path) is True
    assert mcp_config.remove_server("a", path) is False  # already gone
    remaining = [s["id"] for s in mcp_config.load_servers(path)]
    assert remaining == ["b"]


def test_normalise_accepts_string_args_form(tmp_path):
    """A loose 'args': 'one two three' string is split on whitespace."""
    path = tmp_path / "mcp.json"
    mcp_config.add_server(
        {"id": "x", "command": "/bin/cmd", "args": "  --foo   bar  "},
        path,
    )
    assert mcp_config.get_server("x", path)["args"] == ["--foo", "bar"]


def test_load_with_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text("{not valid json")
    assert mcp_config.load_servers(path) == []
