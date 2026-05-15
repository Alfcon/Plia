"""
agent_reporting.py — Fans an agent RunResult out to notification channels.

ResultDispatcher.report(state, result) is the callback the AgentScheduler
invokes (as its `reporter`) after a run completes. The scheduler has already
appended the run to AgentState.history and persisted it; the dispatcher's job
is purely notification:

  - always:           emit agent_history_appended(role_id)  -> AgentsTab refresh
  - notify == tts:        speak a short summary
  - notify == toast_card: emit show_toast + dashboard_card_added
  - notify == comm_log:   emit comm_log_append

All cross-thread delivery happens via Qt queued signal connections.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QObject, Signal


def _item_label(item: Any) -> str:
    """Best-effort human label for an item returned by an agent.

    Different agents/LLMs use different field names. Try the common ones in
    order, fall back to stringifying the dict so the user never sees a bare
    '?' for non-empty items.
    """
    if not isinstance(item, dict):
        return str(item)[:200]
    for key in ("title", "name", "url", "link", "repo", "repository",
                "project", "headline", "summary", "description", "text"):
        v = item.get(key)
        if v:
            return str(v)[:200]
    # Last-ditch: stringify the whole dict so something useful shows.
    return str(item)[:200]


def _format_chat_item(item: Any) -> str:
    """Render an item for the chat tab. Prefers a markdown link if a URL is
    present so users can click through to the source."""
    if not isinstance(item, dict):
        return str(item)[:200]
    title = (item.get("title") or item.get("name") or item.get("repo")
             or item.get("repository") or item.get("project")
             or item.get("headline"))
    url = item.get("url") or item.get("link") or item.get("href")
    if title and url:
        return f"[{title}]({url})"
    if url:
        return str(url)
    return _item_label(item)


class ResultDispatcher(QObject):
    agent_history_appended = Signal(str)            # role_id
    show_toast = Signal(str, str, bool)             # title, body, success
    dashboard_card_added = Signal(dict)             # card payload
    comm_log_append = Signal(str, str, str)         # role_id, title, body
    chat_message_append = Signal(str, str)          # role_id, formatted_body
    file_saved = Signal(str, str)                   # role_id, file_path

    def __init__(self, *, speak: Optional[Callable[[str], None]] = None, parent=None):
        super().__init__(parent)
        self._speak = speak

    def report(self, state, result) -> None:
        """state: AgentState, result: RunResult.

        `state.notify` may be a single channel ("tts") or a comma-separated
        list ("tts,chat,file"); every channel mentioned is dispatched.
        """
        self.agent_history_appended.emit(state.role_id)
        channels = [c.strip() for c in (state.notify or "").split(",") if c.strip()]
        for ch in channels:
            if ch == "tts":
                self._report_tts(state, result)
            elif ch == "toast_card":
                self._report_toast_card(state, result)
            elif ch == "comm_log":
                self._report_comm_log(state, result)
            elif ch == "chat":
                self._report_chat(state, result)
            elif ch == "file":
                self._report_file(state, result)

    # ── channels ──────────────────────────────────────────────────────────
    def _speak_text(self, text: str) -> None:
        if self._speak is not None:
            self._speak(text)
            return
        try:
            from core.tts import tts
            tts.queue_sentence(text)
        except Exception as exc:
            print(f"[ResultDispatcher] TTS unavailable: {exc}")

    def _report_tts(self, state, result) -> None:
        if not result.success:
            msg = f"{state.display_name} failed. {result.error or 'unknown error'}."
        elif result.items_found == 0:
            msg = f"{state.display_name} ran. Nothing new."
        else:
            msg = f"{state.display_name}: {result.summary}"
        self._speak_text(msg)

    def _report_toast_card(self, state, result) -> None:
        title = state.display_name
        body = result.summary if result.success else f"Failed: {result.error}"
        self.show_toast.emit(title, body, bool(result.success))
        self.dashboard_card_added.emit({
            "role_id": state.role_id,
            "icon": state.icon,
            "title": state.display_name,
            "summary": result.summary,
            "items_found": result.items_found,
            "items": list(result.items[:5]),
            "success": bool(result.success),
        })

    def _report_comm_log(self, state, result) -> None:
        title = f"{state.icon} {state.display_name}"
        body = result.summary
        for item in (result.items or [])[:5]:
            body += f"\n  • {_item_label(item)}"
        self.comm_log_append.emit(state.role_id, title, body)

    def _report_chat(self, state, result) -> None:
        """Format a result as a chat message and emit for the chat tab to render.

        Items are rendered as markdown links when URLs are present so the user
        can click through directly to the source.
        """
        header = f"{state.icon} {state.display_name}"
        if not result.success:
            body = f"**{header}** — failed: {result.error or 'unknown error'}\n{result.details}"
        else:
            body = f"**{header}**\n{result.summary}"
            for item in (result.items or [])[:10]:
                body += f"\n  • {_format_chat_item(item)}"
        self.chat_message_append.emit(state.role_id, body)

    def _report_file(self, state, result) -> None:
        """Append a structured run entry to ~/.plia_ai/agent_results/<role_id>.log."""
        from datetime import datetime
        from pathlib import Path

        out_dir = Path.home() / ".plia_ai" / "agent_results"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            log_path = out_dir / f"{state.role_id}.log"
            stamp = datetime.now().isoformat(timespec="seconds")
            lines = [
                f"[{stamp}] {state.display_name} — {'OK' if result.success else 'FAIL'}",
                f"  summary: {result.summary}",
            ]
            if result.error:
                lines.append(f"  error: {result.error}")
            lines.append(f"  items_found: {result.items_found}")
            for item in (result.items or [])[:25]:
                lines.append(f"  • {_item_label(item)}")
            lines.append("")
            with log_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            self.file_saved.emit(state.role_id, str(log_path))
        except Exception as exc:
            print(f"[ResultDispatcher] file write failed: {exc}")
