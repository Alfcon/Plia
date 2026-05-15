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

from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal


class ResultDispatcher(QObject):
    agent_history_appended = Signal(str)            # role_id
    show_toast = Signal(str, str, bool)             # title, body, success
    dashboard_card_added = Signal(dict)             # card payload
    comm_log_append = Signal(str, str, str)         # role_id, title, body

    def __init__(self, *, speak: Optional[Callable[[str], None]] = None, parent=None):
        super().__init__(parent)
        self._speak = speak

    def report(self, state, result) -> None:
        """state: AgentState, result: RunResult."""
        self.agent_history_appended.emit(state.role_id)
        if state.notify == "tts":
            self._report_tts(state, result)
        elif state.notify == "toast_card":
            self._report_toast_card(state, result)
        elif state.notify == "comm_log":
            self._report_comm_log(state, result)

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
            body += f"\n  • {item.get('title', '?')}"
        self.comm_log_append.emit(state.role_id, title, body)
