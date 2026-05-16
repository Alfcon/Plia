"""Tests for the user plugin loader."""

import textwrap
from pathlib import Path

import core.plugins as plugins_mod
from core.function_executor import executor


def _setup_plugin_dir(monkeypatch, tmp_path):
    """Redirect PLUGINS_DIR to a sandbox so we don't touch the real ~/.plia_ai."""
    sandbox = tmp_path / "plugins"
    sandbox.mkdir()
    monkeypatch.setattr(plugins_mod, "PLUGINS_DIR", sandbox)
    return sandbox


def test_plugin_loader_registers_tool_functions(monkeypatch, tmp_path):
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "math_helper.py").write_text(textwrap.dedent("""
        def tool_double(params):
            return {"success": True, "message": "ok",
                    "data": {"result": (params or {}).get("n", 0) * 2}}

        def tool_square(params):
            n = (params or {}).get("n", 0)
            return {"success": True, "message": "ok", "data": {"result": n * n}}

        def helper_not_a_tool():
            return "ignored"
    """))

    reg = plugins_mod._PluginRegistry()  # fresh instance reads sandbox

    names = reg.names()
    assert "math_helper:double" in names
    assert "math_helper:square" in names
    # Non-`tool_` functions are NOT registered.
    assert all("helper_not_a_tool" not in n for n in names)


def test_plugin_call_dispatches_to_function(monkeypatch, tmp_path):
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "math_helper.py").write_text(textwrap.dedent("""
        def tool_double(params):
            return {"success": True, "message": "ok",
                    "data": {"result": (params or {}).get("n", 0) * 2}}
    """))
    reg = plugins_mod._PluginRegistry()
    out = reg.call("math_helper:double", {"n": 7})
    assert out["success"] is True
    assert out["data"]["result"] == 14


def test_plugin_call_returns_none_for_unknown_tool(monkeypatch, tmp_path):
    _setup_plugin_dir(monkeypatch, tmp_path)
    reg = plugins_mod._PluginRegistry()
    # No plugins loaded; unknown tool name -> None so caller can fall through.
    assert reg.call("not:a_real_plugin_tool", {}) is None


def test_plugin_crashing_does_not_propagate(monkeypatch, tmp_path):
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "boom.py").write_text(textwrap.dedent("""
        def tool_explode(params):
            raise RuntimeError("deliberate")
    """))
    reg = plugins_mod._PluginRegistry()
    out = reg.call("boom:explode", {})
    assert out is not None
    assert out["success"] is False
    assert "deliberate" in out["message"]


def test_plugin_load_error_is_isolated(monkeypatch, tmp_path):
    """A syntax-error plugin records an error but doesn't block other plugins."""
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "good.py").write_text(textwrap.dedent("""
        def tool_ping(params):
            return {"success": True, "message": "pong", "data": None}
    """))
    (sandbox / "broken.py").write_text("def tool_bad(params:  # SyntaxError\n")
    reg = plugins_mod._PluginRegistry()
    assert "good:ping" in reg.names()
    assert "broken" in reg.errors()


def test_function_executor_dispatches_to_plugin(monkeypatch, tmp_path):
    """executor.execute('<plugin>:<name>', ...) hits the registry."""
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "echo.py").write_text(textwrap.dedent("""
        def tool_echo(params):
            return {"success": True, "message": "echoed",
                    "data": {"got": params}}
    """))
    # Swap the singleton the executor reads from.
    monkeypatch.setattr(plugins_mod, "registry", plugins_mod._PluginRegistry())

    out = executor.execute("echo:echo", {"hello": "world"})
    assert out["success"] is True
    assert out["data"]["got"] == {"hello": "world"}


def test_plugin_wraps_non_dict_return(monkeypatch, tmp_path):
    """If a plugin returns a non-dict, the registry wraps it gracefully."""
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "weird.py").write_text(textwrap.dedent("""
        def tool_just_a_string(params):
            return "just a string"
    """))
    reg = plugins_mod._PluginRegistry()
    out = reg.call("weird:just_a_string", {})
    assert out["success"] is True
    assert out["data"] == "just a string"


def test_list_plia_features_includes_plugin_tools(monkeypatch, tmp_path):
    """The introspection tool surfaces plugin tools so agents can discover them."""
    sandbox = _setup_plugin_dir(monkeypatch, tmp_path)
    (sandbox / "mine.py").write_text(textwrap.dedent("""
        def tool_special(params):
            return {"success": True, "message": "", "data": None}
    """))
    monkeypatch.setattr(plugins_mod, "registry", plugins_mod._PluginRegistry())

    out = executor.execute("list_plia_features", {})
    assert "mine:special" in out["data"]["tools"]
