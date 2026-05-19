"""Plia plugin — train a wake word from chat/agents.

Usage::

    {
        "tool": "wake_trainer:train_wake_word",
        "params": {"word": "plia", "variants": 5000, "voices": [...]}
    }
"""

from __future__ import annotations

from config import WAKE_TRAINER_ENABLED
from core.wake_trainer import (
    train_wake_word, WakeTrainerError, TrainCancelled, DEFAULT_VOICES,
)

_DISABLED_MSG = (
    "In-app wake-word training is currently paused. Train via openWakeWord's "
    "Colab notebook instead: "
    "https://github.com/dscripka/openWakeWord/blob/main/notebooks/"
    "automatic_model_training.ipynb — then drop the resulting .onnx into "
    "models/wake/custom/ and hit Settings → Voice & Audio → Wake Words → ↻ Reload."
)


def tool_train_wake_word(params: dict) -> dict:
    """Train an openWakeWord model. Long-running (~20–40 min on CPU)."""
    if not WAKE_TRAINER_ENABLED:
        return {"success": False, "message": _DISABLED_MSG, "data": None}

    params = params or {}
    word = (params.get("word") or "").strip()
    if not word:
        return {"success": False, "message": "word is required", "data": None}

    variants = int(params.get("variants") or 5000)
    voices = params.get("voices") or list(DEFAULT_VOICES)

    try:
        path = train_wake_word(
            word, variants=variants, voices=voices,
            on_progress=lambda pct, msg: print(f"[wake-trainer] {pct:5.1f}% {msg}"),
        )
    except TrainCancelled as exc:
        return {"success": False, "message": f"cancelled: {exc}", "data": None}
    except WakeTrainerError as exc:
        return {"success": False, "message": str(exc), "data": None}
    return {
        "success": True,
        "message": f"trained wake word {word!r} → {path}",
        "data": {"path": str(path)},
    }
