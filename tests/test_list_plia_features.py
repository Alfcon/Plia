"""Tests for the list_plia_features introspection tool."""

from core.function_executor import executor


def test_list_plia_features_returns_tools_and_capabilities():
    out = executor.execute("list_plia_features", {})
    assert out["success"] is True
    data = out["data"]
    assert data["name"] == "Plia"
    assert isinstance(data["tools"], list) and len(data["tools"]) > 0
    assert isinstance(data["capabilities"], dict) and len(data["capabilities"]) > 0
    # Spot-check expected categories
    for key in ("voice_pipeline", "live_agents", "search", "models"):
        assert key in data["capabilities"]
        assert len(data["capabilities"][key]) > 0


def test_list_plia_features_includes_known_tools_via_introspection():
    out = executor.execute("list_plia_features", {})
    tools = out["data"]["tools"]
    # Tools auto-discovered from execute()'s dispatch chain
    for expected in ("web_search", "http_get", "read_emails",
                     "mcp_tool_call", "get_stock_price"):
        assert expected in tools, f"{expected!r} missing from {tools}"
    # The introspection tool itself should NOT appear (it's not "external")
    assert "list_plia_features" not in tools


def test_list_plia_features_message_summarises_counts():
    out = executor.execute("list_plia_features", {})
    msg = out["message"]
    assert "tools" in msg.lower()
    assert "capabilities" in msg.lower()
