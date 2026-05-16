"""
mcp_servers.py — Sidebar tab for managing MCP (Model Context Protocol) servers.

Reads / writes ~/.plia/mcp.json via core.mcp_config and shows the running
MCPClient's view of each server (connection state + discovered tools).

Changes to server configs require a Plia restart for the running MCPClient
to pick them up (the async loop is set up at module-import time).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from qfluentwidgets import (
    BodyLabel, CaptionLabel, PrimaryPushButton, PushButton, ScrollArea,
    SubtitleLabel, TitleLabel, FluentIcon as FIF,
)

from core import mcp_config


class _ServerEditorDialog(QDialog):
    """Add / edit one MCP server entry. JSON-aware fields for args + env."""

    def __init__(self, entry: Dict[str, Any] = None, parent=None):
        super().__init__(parent)
        self._editing = entry is not None
        self._entry = dict(entry or {})
        self.setWindowTitle(
            f"Edit MCP server — {self._entry.get('id', '')}"
            if self._editing else "Add MCP server"
        )
        self.setMinimumSize(640, 540)
        self.resize(720, 600)
        self.setSizeGripEnabled(True)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(TitleLabel(self.windowTitle()))
        root.addWidget(CaptionLabel(
            "MCP servers are spawned via stdio. Provide the command and any "
            "arguments / environment variables. Restart Plia to apply changes."
        ))

        root.addWidget(QLabel("Server ID  (unique, e.g. 'github', 'fs-tools')"))
        self._id = QLineEdit(self._entry.get("id", ""))
        if self._editing:
            self._id.setReadOnly(True)
            self._id.setToolTip("Server ID is the primary key; can't be changed in edit mode.")
        root.addWidget(self._id)

        root.addWidget(QLabel("Command  (executable or script path)"))
        self._cmd = QLineEdit(self._entry.get("command", ""))
        self._cmd.setPlaceholderText("e.g. npx, uvx, /usr/bin/python, /path/to/server")
        root.addWidget(self._cmd)

        root.addWidget(QLabel("Arguments  (one per line, or JSON list)"))
        self._args = QPlainTextEdit()
        args = self._entry.get("args") or []
        if isinstance(args, list):
            self._args.setPlainText("\n".join(str(a) for a in args))
        else:
            self._args.setPlainText(str(args))
        self._args.setMaximumHeight(100)
        root.addWidget(self._args)

        root.addWidget(QLabel("Environment  (KEY=value, one per line)"))
        self._env = QPlainTextEdit()
        env = self._entry.get("env") or {}
        if isinstance(env, dict):
            self._env.setPlainText("\n".join(f"{k}={v}" for k, v in env.items()))
        self._env.setMaximumHeight(100)
        root.addWidget(self._env)

        # Timeouts on a single row
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("Connect timeout (s):"))
        self._connect_t = QLineEdit(str(self._entry.get("connect_timeout_seconds", 10.0)))
        self._connect_t.setMaximumWidth(80)
        t_row.addWidget(self._connect_t)
        t_row.addSpacing(20)
        t_row.addWidget(QLabel("Call timeout (s):"))
        self._call_t = QLineEdit(str(self._entry.get("call_timeout_seconds", 60.0)))
        self._call_t.setMaximumWidth(80)
        t_row.addWidget(self._call_t)
        t_row.addStretch(1)
        root.addLayout(t_row)

        root.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("Save")
        save.clicked.connect(self._on_save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        root.addLayout(btn_row)

    def _parse_args(self) -> List[str]:
        text = self._args.toPlainText().strip()
        if not text:
            return []
        # Accept a JSON list as a convenience.
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(a) for a in parsed]
            except json.JSONDecodeError:
                pass
        # Otherwise treat each non-empty line as one argument.
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    def _parse_env(self) -> Dict[str, str]:
        env: Dict[str, str] = {}
        for ln in self._env.toPlainText().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            env[k.strip()] = v.strip()
        return env

    def _on_save(self):
        sid = self._id.text().strip()
        cmd = self._cmd.text().strip()
        if not sid:
            QMessageBox.warning(self, "Missing ID",
                                "Server ID is required.")
            return
        if not cmd:
            QMessageBox.warning(self, "Missing command",
                                "The command field is required.")
            return
        try:
            self._entry = {
                "id":        sid,
                "transport": "stdio",
                "command":   cmd,
                "args":      self._parse_args(),
                "env":       self._parse_env(),
                "connect_timeout_seconds": float(self._connect_t.text() or 10.0),
                "call_timeout_seconds":    float(self._call_t.text() or 60.0),
            }
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid number", str(exc))
            return
        self.accept()

    def get_entry(self) -> Dict[str, Any]:
        return self._entry


class _ServerCard(QFrame):
    """Visualisation of a single configured MCP server."""

    def __init__(self, entry: Dict[str, Any], status: Dict[str, Any],
                 on_edit, on_delete, parent=None):
        super().__init__(parent)
        self.setObjectName("mcpServerCard")
        self.setStyleSheet(
            "QFrame#mcpServerCard { border: 1px solid #1b2236;"
            " border-radius: 8px; background: rgba(255,255,255,0.03);"
            " padding: 10px; }"
        )
        outer = QVBoxLayout(self)
        outer.setSpacing(4)

        connected = bool(status.get("connected"))
        dot = ("<span style='color:#4caf50'>● connected</span>"
               if connected else
               "<span style='color:#9aa0aa'>● not connected</span>")
        head = QLabel(
            f"<b>🔌 {entry.get('id', 'server')}</b>   {dot}"
        )
        head.setTextFormat(Qt.RichText)
        outer.addWidget(head)

        cmd_args = entry.get("command", "") + " " + " ".join(entry.get("args") or [])
        cmd_lbl = QLabel(f"<span style='color:#9aa0aa'>$ {cmd_args.strip()}</span>")
        cmd_lbl.setTextFormat(Qt.RichText)
        cmd_lbl.setWordWrap(True)
        outer.addWidget(cmd_lbl)

        tools = status.get("tools") or []
        if tools:
            tools_lbl = QLabel(
                f"<span style='color:#7d828c'>Discovered tools ({len(tools)}):</span>"
            )
            tools_lbl.setTextFormat(Qt.RichText)
            outer.addWidget(tools_lbl)
            for t in tools[:25]:
                desc = (t.get("description") or "").strip()
                if len(desc) > 110:
                    desc = desc[:107] + "…"
                row = QLabel(
                    f"  • <code>{t.get('tool_id', '')}</code> "
                    f"<span style='color:#7d828c'>— {desc}</span>"
                )
                row.setTextFormat(Qt.RichText)
                row.setWordWrap(True)
                outer.addWidget(row)
            if len(tools) > 25:
                more = QLabel(f"  …and {len(tools) - 25} more")
                more.setStyleSheet("color:#7d828c;")
                outer.addWidget(more)
        else:
            empty = QLabel(
                "<span style='color:#7d828c'>"
                "No tools discovered yet (server may still be starting or failed).</span>"
            )
            empty.setTextFormat(Qt.RichText)
            outer.addWidget(empty)

        # Action buttons
        btn_row = QHBoxLayout()
        edit_btn = PushButton(FIF.EDIT, "Edit")
        edit_btn.clicked.connect(lambda: on_edit(entry))
        btn_row.addWidget(edit_btn)
        del_btn = PushButton(FIF.DELETE, "Delete")
        del_btn.clicked.connect(lambda: on_delete(entry.get("id", "")))
        btn_row.addWidget(del_btn)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)


class MCPServersTab(QWidget):
    """List + manage MCP server entries from ~/.plia/mcp.json."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mcpServersView")
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 30, 30, 30)
        root.setSpacing(14)

        header = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(TitleLabel("MCP Servers", self))
        sub = BodyLabel(
            "Configure external tools that speak the Model Context Protocol. "
            "Plia spawns each server via stdio and exposes its tools to live "
            "agents through the 'mcp_tool_call' tool. Changes take effect on "
            "next Plia restart.",
            self,
        )
        sub.setStyleSheet("color:#9aa0aa;")
        sub.setWordWrap(True)
        col.addWidget(sub)
        header.addLayout(col)
        header.addStretch(1)

        add_btn = PrimaryPushButton(FIF.ADD, "Add Server")
        add_btn.clicked.connect(self._open_add)
        header.addWidget(add_btn)

        refresh_btn = PushButton(FIF.SYNC, "Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)

        root.addLayout(header)

        self._status_lbl = CaptionLabel("")
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)

        self._scroll = ScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(container)
        self._list_layout.setSpacing(10)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(container)
        root.addWidget(self._scroll, 1)

    def _clear_rows(self):
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def refresh(self):
        self._clear_rows()
        configs = mcp_config.load_servers()

        # Pull live status from the running MCPClient (if available).
        live_status_by_id: Dict[str, Dict[str, Any]] = {}
        ready = False
        err = None
        try:
            from core.mcp_client import mcp_client
            ready = mcp_client.is_ready()
            for s in mcp_client.list_servers():
                live_status_by_id[s.get("id", "")] = s
            err = mcp_client.discovery_error()
        except Exception as exc:
            err = str(exc)

        # Header status line
        if not configs:
            self._status_lbl.setText(
                "No MCP servers configured. Click 'Add Server' to add one — "
                "example commands: 'npx -y @modelcontextprotocol/server-github', "
                "'uvx mcp-server-fetch'."
            )
        else:
            connected = sum(1 for s in live_status_by_id.values() if s.get("connected"))
            self._status_lbl.setText(
                f"{len(configs)} configured · {connected} connected · "
                f"discovery {'ready' if ready else 'in progress'}"
                + (f" · error: {err}" if err else "")
            )

        if not configs:
            empty = SubtitleLabel("No MCP servers configured.")
            empty.setStyleSheet("color:#7d828c;")
            self._list_layout.addWidget(empty)
            return

        for entry in configs:
            sid = entry.get("id", "")
            status = live_status_by_id.get(sid, {})
            card = _ServerCard(entry, status, self._open_edit, self._on_delete)
            self._list_layout.addWidget(card)

    # ── Actions ──────────────────────────────────────────────────────────
    def _open_add(self):
        dlg = _ServerEditorDialog(parent=self)
        if not dlg.exec():
            return
        entry = dlg.get_entry()
        if not mcp_config.add_server(entry):
            QMessageBox.warning(
                self, "Could not add server",
                f"Server id {entry.get('id')!r} already exists or is invalid.",
            )
            return
        self._notify_restart_needed()
        self.refresh()

    def _open_edit(self, entry: Dict[str, Any]):
        sid = entry.get("id", "")
        dlg = _ServerEditorDialog(entry=entry, parent=self)
        if not dlg.exec():
            return
        if not mcp_config.update_server(sid, dlg.get_entry()):
            QMessageBox.warning(self, "Update failed",
                                f"Could not update server {sid!r}.")
            return
        self._notify_restart_needed()
        self.refresh()

    def _on_delete(self, server_id: str):
        if not server_id:
            return
        reply = QMessageBox.question(
            self, "Delete MCP server",
            f"Delete the MCP server entry {server_id!r}?\n\n"
            "The server config file will be updated. Restart Plia for the "
            "change to fully take effect (the running session will keep the "
            "current server connection until then).",
        )
        if reply != QMessageBox.Yes:
            return
        mcp_config.remove_server(server_id)
        self._notify_restart_needed()
        self.refresh()

    def _notify_restart_needed(self):
        """Inform the user that an MCP config change needs a restart."""
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(
                title="MCP config saved",
                content="Restart Plia for changes to take effect.",
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )
        except Exception:
            pass
