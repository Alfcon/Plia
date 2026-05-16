"""
plugins.py — User plugin loader for Plia.

Drop a `.py` file into ~/.plia_ai/plugins/ and Plia will expose any top-level
function whose name starts with ``tool_`` as an agent-callable tool. The
tool name is ``<plugin_filename>:<function_name_without_tool_prefix>`` so
multiple plugins can't accidentally collide.

Each tool function takes a single ``params: dict`` argument and returns the
standard Plia response shape::

    {
        "success": bool,
        "message": str,
        "data": Any | None,
    }

Example plugin (``~/.plia_ai/plugins/example.py``)::

    def tool_say_hello(params):
        \"\"\"Greet someone by name.\"\"\"
        name = (params or {}).get("name") or "world"
        return {"success": True, "message": f"Hello, {name}!",
                "data": {"greeting": f"Hello, {name}!"}}

After dropping that file, agents can call ``example:say_hello`` like any
other tool. Plugins are loaded on startup; call ``registry.reload()`` (or
the Settings tab's "Reload plugins" button) after editing them.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal


PLUGINS_DIR = Path.home() / ".plia_ai" / "plugins"


class _PluginRegistry(QObject):
    """Loads user plugins and exposes their tools to FunctionExecutor."""

    plugins_changed = Signal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        # tool_name -> (callable, plugin_name, docstring)
        self._tools: Dict[str, Tuple[Callable, str, str]] = {}
        # plugin_name -> list of error strings (last load attempt)
        self._errors: Dict[str, str] = {}
        self.reload()

    # ── Loading ──────────────────────────────────────────────────────────
    def reload(self) -> None:
        """Re-scan PLUGINS_DIR and re-register all ``tool_*`` functions.

        Idempotent and safe to call at runtime — replaces the current
        registry wholesale.
        """
        with self._lock:
            self._tools = {}
            self._errors = {}
            try:
                PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                print(f"[plugins] could not create {PLUGINS_DIR}: {exc}")
                self.plugins_changed.emit()
                return
            for py_file in sorted(PLUGINS_DIR.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue  # skip __init__.py, _private.py, etc.
                try:
                    module = self._import_module(py_file)
                except Exception:
                    err = traceback.format_exc()
                    print(f"[plugins] failed to load {py_file.name}:\n{err}")
                    self._errors[py_file.stem] = err
                    continue
                self._register_tools(module, py_file.stem)
        self.plugins_changed.emit()

    def _import_module(self, py_file: Path):
        # Use a distinctive prefix so plugin modules don't shadow project ones.
        mod_name = f"plia_plugin_{py_file.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, py_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not create import spec for {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module  # so importlib re-uses across reloads
        spec.loader.exec_module(module)
        return module

    def _register_tools(self, module, plugin_name: str) -> None:
        count = 0
        for attr_name in dir(module):
            if not attr_name.startswith("tool_") or attr_name == "tool_":
                continue
            fn = getattr(module, attr_name)
            if not callable(fn):
                continue
            tool_short = attr_name[len("tool_"):]
            tool_name = f"{plugin_name}:{tool_short}"
            doc = (inspect.getdoc(fn) or "").strip()
            self._tools[tool_name] = (fn, plugin_name, doc)
            count += 1
        if count:
            print(f"[plugins] {plugin_name}: registered {count} tool(s)")

    # ── Invocation ───────────────────────────────────────────────────────
    def call(self, tool_name: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Invoke a plugin tool. Returns None if ``tool_name`` is not a
        registered plugin tool (caller should fall through to other dispatch).
        """
        with self._lock:
            entry = self._tools.get(tool_name)
        if entry is None:
            return None
        fn, plugin_name, _doc = entry
        try:
            out = fn(params or {})
        except Exception as exc:
            return {
                "success": False,
                "message": f"plugin {tool_name!r} crashed: {exc}",
                "data": None,
            }
        # Be forgiving: wrap unexpected return shapes.
        if not isinstance(out, dict):
            return {
                "success": True,
                "message": f"{tool_name} returned {type(out).__name__}",
                "data": out,
            }
        if "success" not in out:
            out.setdefault("success", True)
            out.setdefault("message", "")
            out.setdefault("data", None)
        return out

    # ── Introspection ────────────────────────────────────────────────────
    def names(self) -> List[str]:
        with self._lock:
            return sorted(self._tools.keys())

    def info(self) -> List[Dict[str, Any]]:
        """Per-tool metadata for UI display."""
        with self._lock:
            return [
                {
                    "name": name,
                    "plugin": p,
                    "description": (doc.splitlines()[0] if doc else ""),
                }
                for name, (_fn, p, doc) in sorted(self._tools.items())
            ]

    def errors(self) -> Dict[str, str]:
        """Plugins that failed to load on the last reload (filename → traceback)."""
        with self._lock:
            return dict(self._errors)


# Process-wide singleton
registry = _PluginRegistry()
