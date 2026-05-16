"""
mcp_config.py — Read/write helpers for ~/.plia/mcp.json.

The file format is consumed by MCPClient at startup::

    {
      "servers": [
        {
          "id":        "<unique-id>",
          "transport": "stdio",
          "command":   "<executable-or-script-path>",
          "args":      ["..."],
          "env":       {"KEY": "value"},
          "connect_timeout_seconds": 10.0,
          "call_timeout_seconds":    60.0
        }
      ]
    }

These helpers are pure I/O; the running MCPClient won't see changes until
Plia is restarted (or its async loop is told to reload — not implemented yet).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


PLIA_DIR = Path.home() / ".plia"
MCP_CONFIG_PATH = PLIA_DIR / "mcp.json"


def _safe_load(path: Path = MCP_CONFIG_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {"servers": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[mcp_config] could not parse {path}: {exc}")
        return {"servers": []}
    if not isinstance(raw, dict):
        return {"servers": []}
    if not isinstance(raw.get("servers"), list):
        raw["servers"] = []
    return raw


def load_servers(path: Path = MCP_CONFIG_PATH) -> List[Dict[str, Any]]:
    """Return the list of server entries. Always returns a list."""
    return [s for s in _safe_load(path).get("servers", []) if isinstance(s, dict)]


def save_servers(servers: List[Dict[str, Any]],
                 path: Path = MCP_CONFIG_PATH) -> None:
    """Atomically rewrite the entire `servers` list."""
    payload = {"servers": list(servers)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_server(entry: Dict[str, Any],
               path: Path = MCP_CONFIG_PATH) -> bool:
    """Append a new server entry; refuses to overwrite an existing id.

    Returns True on success, False if the id is taken or required fields
    are missing.
    """
    sid = (entry.get("id") or "").strip()
    cmd = (entry.get("command") or "").strip()
    if not sid or not cmd:
        return False
    servers = load_servers(path)
    if any(s.get("id") == sid for s in servers):
        return False
    servers.append(_normalise(entry))
    save_servers(servers, path)
    return True


def update_server(server_id: str, entry: Dict[str, Any],
                  path: Path = MCP_CONFIG_PATH) -> bool:
    """Replace an existing server entry by id. Returns True if found."""
    servers = load_servers(path)
    for i, s in enumerate(servers):
        if s.get("id") == server_id:
            new_entry = _normalise(entry)
            # Preserve the existing id if the caller didn't supply one.
            new_entry.setdefault("id", server_id)
            servers[i] = new_entry
            save_servers(servers, path)
            return True
    return False


def remove_server(server_id: str,
                  path: Path = MCP_CONFIG_PATH) -> bool:
    """Drop the server with this id. Returns True if something was removed."""
    servers = load_servers(path)
    new_servers = [s for s in servers if s.get("id") != server_id]
    if len(new_servers) == len(servers):
        return False
    save_servers(new_servers, path)
    return True


def get_server(server_id: str,
               path: Path = MCP_CONFIG_PATH) -> Optional[Dict[str, Any]]:
    """Return the entry with this id, or None."""
    for s in load_servers(path):
        if s.get("id") == server_id:
            return s
    return None


def _normalise(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce loose user input into the on-disk shape MCPClient expects."""
    out: Dict[str, Any] = {
        "id":        str(entry.get("id", "")).strip(),
        "transport": str(entry.get("transport", "stdio")).strip() or "stdio",
        "command":   str(entry.get("command", "")).strip(),
    }
    args = entry.get("args", [])
    if isinstance(args, str):
        # Allow a single-string convenience form.
        args = [a for a in args.split() if a]
    elif not isinstance(args, list):
        args = []
    out["args"] = [str(a) for a in args]

    env = entry.get("env", {})
    if not isinstance(env, dict):
        env = {}
    out["env"] = {str(k): str(v) for k, v in env.items()}

    out["connect_timeout_seconds"] = float(
        entry.get("connect_timeout_seconds", 10.0) or 10.0
    )
    out["call_timeout_seconds"] = float(
        entry.get("call_timeout_seconds", 60.0) or 60.0
    )
    return out
