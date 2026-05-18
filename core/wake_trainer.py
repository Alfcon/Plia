"""In-app openWakeWord trainer.

Public surface:
  train_wake_word(word, ...) -> Path        end-to-end training
  ensure_negative_features(on_progress)     idempotent neg-feature fetch
  synthesize_positives(...)                 Piper-based positive WAV synthesis

All heavy deps (torch, openwakeword.data, speechbrain, audiomentations,
torch_audiomentations, pronouncing, acoustics, mutagen) are lazy-imported
inside the functions that need them. Importing this module is free.

Output goes to <models_dir>/custom/<slug>.onnx where models_dir() is the
helper from core.wake_models — the same directory the existing wake-model
discovery scanner reads.

See docs/superpowers/specs/2026-05-18-in-app-wake-word-trainer-design.md
for the design rationale.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


# ── Constants ─────────────────────────────────────────────────────────────
WAKE_TRAINER_DIR = Path.home() / ".plia" / "wake_trainer"
NEG_FEATURES_DIR = WAKE_TRAINER_DIR / "neg_features"   # cached across runs

DEFAULT_VOICES = [
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-libritts-high",
    "en_GB-alba-medium",
    "en_GB-northern_english_male-medium",
]

_WORD_RE = re.compile(r"^[A-Za-z0-9 ]{1,32}$")


# ── Callback types ────────────────────────────────────────────────────────
ProgressFn = Callable[[float, str], None]   # (pct 0-100, message)
CancelFn = Callable[[], bool]               # returns True to stop


# ── Exceptions ────────────────────────────────────────────────────────────
class TrainCancelled(Exception):
    """should_cancel() returned True between stages or epochs."""


class WakeTrainerError(Exception):
    """Anything else that prevented training from completing."""


# ── Input validation ──────────────────────────────────────────────────────
def _validate_inputs(word: str, variants: int, voices: list[str]) -> None:
    """Raise WakeTrainerError if inputs are unusable. Voices may be empty,
    in which case the caller falls back to DEFAULT_VOICES."""
    if not isinstance(word, str) or not _WORD_RE.match(word.strip()):
        raise WakeTrainerError(
            f"word must be 1-32 chars, ASCII letters/digits/space; got {word!r}"
        )
    if not (500 <= variants <= 20000):
        raise WakeTrainerError(
            f"variants must be in [500, 20000]; got {variants}"
        )
    for v in voices:
        if v not in DEFAULT_VOICES:
            raise WakeTrainerError(
                f"voice {v!r} is not in DEFAULT_VOICES; pass one of "
                f"{DEFAULT_VOICES}"
            )


# ── Public stubs (filled in by later tasks) ───────────────────────────────
def ensure_negative_features(on_progress: ProgressFn = lambda pct, msg: None) -> Path:
    raise NotImplementedError("ensure_negative_features — see Task 4")


def synthesize_positives(
    word: str,
    voices: list[str],
    variants: int,
    out_dir: Path,
    on_progress: ProgressFn = lambda pct, msg: None,
    should_cancel: CancelFn = lambda: False,
) -> Path:
    raise NotImplementedError("synthesize_positives — see Task 5")


def train_wake_word(
    word: str,
    *,
    variants: int = 5000,
    voices: list[str] | None = None,
    output_dir: Path | None = None,
    on_progress: ProgressFn = lambda pct, msg: None,
    should_cancel: CancelFn = lambda: False,
    epochs: int = 100,
) -> Path:
    """End-to-end wake-word training. Fully implemented by Task 8."""
    _validate_inputs(word, variants, voices or [])
    raise NotImplementedError("train_wake_word — see Task 8")
