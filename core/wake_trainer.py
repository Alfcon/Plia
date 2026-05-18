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
import shutil
import time
import urllib.request
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

# Pinned during implementation. The executor verifies that the URL still
# resolves on PR day; if not, update both URL and SHA-256.
_NEG_FEATURES_URL = (
    "https://github.com/dscripka/openWakeWord/releases/download/"
    "v0.5.1/openwakeword_features_2022_09_05.tar.gz"
)
_NEG_FEATURES_SHA256 = "PIN_DURING_IMPLEMENTATION"

_RETRY_DELAYS = [1.0, 4.0, 16.0]   # exponential-ish, total ~21s wall


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


# ── Negative-feature download helpers ────────────────────────────────────
def _download_neg_features(dest: Path) -> None:
    """Download + verify + extract the neg-feature archive under dest.

    Marks success with a `.ready` file. Caller is responsible for clearing
    a half-written dest on exception.
    """
    import hashlib
    import tarfile
    import tempfile

    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz") as tmp:
        archive_path = Path(tmp.name)

    try:
        urllib.request.urlretrieve(_NEG_FEATURES_URL, archive_path)

        # Verify checksum.
        sha = hashlib.sha256()
        with archive_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                sha.update(chunk)
        if _NEG_FEATURES_SHA256 != "PIN_DURING_IMPLEMENTATION":
            if sha.hexdigest() != _NEG_FEATURES_SHA256:
                raise WakeTrainerError(
                    f"neg-features checksum mismatch: got {sha.hexdigest()}, "
                    f"expected {_NEG_FEATURES_SHA256}"
                )

        # Extract.
        with tarfile.open(archive_path, "r:gz") as tar:
            # filter='data' hardens against path traversal + special files,
            # and silences the DeprecationWarning on 3.12+.
            tar.extractall(dest, filter="data")
        (dest / ".ready").write_text("ok\n")
    finally:
        archive_path.unlink(missing_ok=True)


def ensure_negative_features(on_progress: ProgressFn = lambda pct, msg: None) -> Path:
    """Download + extract openWakeWord's negative-feature pack once.

    Cached at NEG_FEATURES_DIR/.ready. Subsequent calls return immediately.
    Raises WakeTrainerError after exhausting retries.
    """
    if (NEG_FEATURES_DIR / ".ready").exists():
        on_progress(10.0, "neg features: cached")
        return NEG_FEATURES_DIR

    on_progress(0.0, "neg features: downloading…")
    last_err: Exception | None = None
    for delay in [0.0] + _RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            _download_neg_features(NEG_FEATURES_DIR)
            on_progress(10.0, "neg features: ready")
            return NEG_FEATURES_DIR
        except Exception as exc:
            last_err = exc
            # Half-written dir gets wiped so the next attempt is clean.
            if NEG_FEATURES_DIR.exists():
                shutil.rmtree(NEG_FEATURES_DIR, ignore_errors=True)

    raise WakeTrainerError(
        f"neg features: download failed after {len(_RETRY_DELAYS) + 1} attempts: {last_err}"
    )


# ── Public stubs (filled in by later tasks) ───────────────────────────────
def synthesize_positives(
    word: str,
    voices: list[str],
    variants: int,
    out_dir: Path,
    on_progress: ProgressFn = lambda pct, msg: None,
    should_cancel: CancelFn = lambda: False,
) -> Path:
    raise NotImplementedError("synthesize_positives — see Task 5")


def _slugify(word: str) -> str:
    """Lower-case, collapse runs of non-[a-z0-9_] into '_', strip edges.
    Raises WakeTrainerError if the result is empty."""
    slug = re.sub(r"[^a-z0-9_]+", "_", word.lower()).strip("_")
    if not slug:
        raise WakeTrainerError(f"word {word!r} produced an empty slug")
    return slug


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
    word = word.strip() if isinstance(word, str) else word
    _validate_inputs(word, variants, voices or [])
    raise NotImplementedError("train_wake_word — see Task 8")
