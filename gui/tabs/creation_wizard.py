"""
creation_wizard.py — Chat-channel wizard for creating a live agent.

Drives the same WizardController as the voice path. Each wizard question is
shown as a single page (label + text input + Next button). On completion it
calls agent_runtime.commit_answers(...) and refreshes the Active Agents tab.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from core.agent_creator import WizardController, classify_executor
from core.agent_runtime import get_runtime
from config import OLLAMA_URL, RESPONDER_MODEL


class CreationWizardDialog(QDialog):
    def __init__(self, task: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create a Live Agent")
        self._task = task

        def _classify(t: str) -> str:
            try:
                from core.settings_store import settings as app_settings
                model = app_settings.get("models.chat", RESPONDER_MODEL)
            except Exception:
                model = RESPONDER_MODEL
            return classify_executor(t, OLLAMA_URL, model)

        self._wizard = WizardController(task, classify_fn=_classify)
        self._committed_state = None
        self._build()
        self._show_step(self._wizard.current_question())

    def _build(self):
        root = QVBoxLayout(self)
        self._intro = QLabel(f"Setting up a live agent to: {self._task}")
        self._intro.setWordWrap(True)
        root.addWidget(self._intro)

        self._question = QLabel("")
        self._question.setWordWrap(True)
        self._question.setStyleSheet("font-weight:600;")
        root.addWidget(self._question)

        self._examples = QLabel("")
        self._examples.setWordWrap(True)
        self._examples.setStyleSheet("color:#9aa0aa;")
        root.addWidget(self._examples)

        self._input = QLineEdit()
        self._input.returnPressed.connect(self._on_next)
        root.addWidget(self._input)

        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self._next_btn = QPushButton("Next")
        self._next_btn.clicked.connect(self._on_next)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(self._next_btn)
        root.addLayout(btn_row)

    def _show_step(self, step):
        self._question.setText(step.question)
        self._examples.setText(
            "Examples: " + ", ".join(step.examples) if step.examples else "")
        self._input.clear()
        self._input.setFocus()

    def _on_next(self):
        text = self._input.text().strip()
        if not text:
            return
        step = self._wizard.answer(text)
        if step.cancelled:
            self.reject()
            return
        if step.done:
            self._committed_state = get_runtime().commit_answers(step.answers)
            self.accept()
            return
        self._show_step(step)

    def get_committed_state(self):
        """Returns the AgentState created, or None if cancelled."""
        return self._committed_state
