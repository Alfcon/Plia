"""WakeDetector — owns the microphone and runs openWakeWord inference.

RealtimeSTT is configured with use_microphone=False; the detector reads
PyAudio chunks, runs openWakeWord prediction, and either:
  - feeds the chunk to RealtimeSTT (when it's actively transcribing post-wake)
  - or emits wake_word_detected(model_id) when any enabled model crosses
    its sensitivity threshold.
"""
from __future__ import annotations

import time  # noqa: F401  # consumed in Task 6 audio loop
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QThread, Signal

# Indirection so tests can monkeypatch the constructor without importing the
# heavy openwakeword module.
def _default_model_class():
    from openwakeword.model import Model
    return Model

_oww_model_class = None  # set lazily; tests patch this directly


SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280  # 80ms @ 16kHz — openwakeword's expected frame size
# Used by _process_chunk (Task 6).
COOLDOWN_SEC = 1.5


class WakeDetector(QThread):
    """QThread that owns mic + openWakeWord and signals when a wake word fires."""

    wake_word_detected = Signal(str)   # model_id
    error = Signal(str)

    def __init__(
        self,
        wake_models: list[dict],
        models_base: Path,
        recorder: Optional[Any] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._wake_models = wake_models
        self._models_base = Path(models_base)
        self._recorder = recorder
        self._running = False
        self._oww = None
        self.thresholds: dict[str, float] = {}
        # Used by _process_chunk (Task 6).
        self._cooldown_until = 0.0

    # ── Public API ───────────────────────────────────────────────────────

    def reload(self, wake_models: list[dict]) -> None:
        """Swap the model list without stopping the mic loop."""
        self._wake_models = wake_models
        self._load_models()

    # ── Internals ────────────────────────────────────────────────────────

    def _load_models(self) -> None:
        """Build the openwakeword.Model from currently-enabled, non-broken paths."""
        enabled = [
            m for m in self._wake_models
            if m.get("enabled") and not m.get("broken")
        ]
        if not enabled:
            self._oww = None
            self.thresholds = {}
            return

        paths = [str(self._models_base / m["path"]) for m in enabled]
        thresholds = {m["id"]: float(m["sensitivity"]) for m in enabled}

        model_class = _oww_model_class or _default_model_class()

        # Try the whole set first; if it fails, fall back to one-at-a-time so
        # a single corrupt .onnx doesn't take everything down.
        try:
            self._oww = model_class(wakeword_models=paths, inference_framework="onnx")
            self.thresholds = thresholds
            return
        except Exception as exc:
            self.error.emit(f"Wake-model bundle failed to load: {exc}. Retrying one-by-one.")

        working: dict[str, float] = {}
        single_models: list[str] = []
        last_single: tuple[str, Any] | None = None  # (model_id, Model instance)
        for m in enabled:
            path = str(self._models_base / m["path"])
            try:
                inst = model_class(
                    wakeword_models=[path], inference_framework="onnx"
                )
                single_models.append(path)
                working[m["id"]] = float(m["sensitivity"])
                last_single = (m["id"], inst)
            except Exception as exc:
                self.error.emit(
                    f"Could not load wake model '{m['id']}': {exc} — skipped."
                )
        if not single_models:
            self._oww = None
            self.thresholds = {}
            return
        if len(single_models) == 1:
            _, inst = last_single  # type: ignore[misc]
            self._oww = inst
            self.thresholds = working
            return
        # Multiple singles validated — try to combine them into one Model.
        try:
            self._oww = model_class(
                wakeword_models=single_models, inference_framework="onnx"
            )
            self.thresholds = working
        except Exception as exc:
            # Combined load still fails: keep only the last validated single
            # model rather than dropping all wake detection. The kept id and
            # Model instance must be the SAME entry, else threshold lookup
            # by model_id will miss every detection.
            kept_id, kept_inst = last_single  # type: ignore[misc]
            dropped = [k for k in list(working) if k != kept_id]
            for d_id in dropped:
                working.pop(d_id, None)
                self.error.emit(
                    f"Could not load wake model '{d_id}' in combined bundle: "
                    f"{exc} — skipped."
                )
            self._oww = kept_inst
            self.thresholds = working

    def run(self) -> None:
        """Subclass hook — real implementation arrives in Task 6."""
        # Placeholder so the QThread doesn't error if started before Task 6.
        self._running = True
        while self._running:
            self.msleep(50)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)
