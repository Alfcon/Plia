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

import random
import re
import shutil
import time
import urllib.request
import wave
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


# ── Piper TTS helpers ─────────────────────────────────────────────────────
_PIPER_LENGTH_SCALES = (0.85, 1.0, 1.15, 1.3)


def _load_piper_voice(name: str):
    """Indirection so tests can monkey-patch without importing piper."""
    from piper.voice import PiperVoice
    return PiperVoice.load(name)


def synthesize_positives(
    word: str,
    voices: list[str],
    variants: int,
    out_dir: Path,
    on_progress: ProgressFn = lambda pct, msg: None,
    should_cancel: CancelFn = lambda: False,
) -> Path:
    """Render `variants` WAV files of `word` to `out_dir` using Piper.

    For each WAV: pick a random voice and length_scale, synthesize to a
    16 kHz mono PCM_S16LE WAV. Per-voice loading is cached; if a voice
    fails to load, it's skipped and the remaining voices keep going. If
    *all* voices fail, raises WakeTrainerError. Cancellation checked
    between WAVs."""
    out_dir.mkdir(parents=True, exist_ok=True)

    cache: dict[str, object] = {}
    usable: list[str] = []
    for v in voices:
        try:
            cache[v] = _load_piper_voice(v)
            usable.append(v)
        except Exception as exc:
            on_progress(10.0, f"piper: skipping {v}: {exc}")

    if not usable:
        raise WakeTrainerError("no usable Piper voice (all loads failed)")

    failures = 0
    for i in range(variants):
        if should_cancel():
            raise TrainCancelled("synth cancelled")
        voice_name = random.choice(usable)
        length_scale = random.choice(_PIPER_LENGTH_SCALES)
        wav_path = out_dir / f"{i:05d}.wav"
        try:
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                cache[voice_name].synthesize(word, wf, length_scale=length_scale)
        except Exception as exc:
            failures += 1
            wav_path.unlink(missing_ok=True)
            if failures > variants // 10:
                raise WakeTrainerError(
                    f"synth: >10% of WAVs failed (last error: {exc})"
                )
            continue

        # Progress 10 → 30 across the synthesis stage.
        pct = 10.0 + 20.0 * ((i + 1) / variants)
        if i % 100 == 0:
            on_progress(pct, f"synth: {i + 1}/{variants}")

    on_progress(30.0, f"synth: {variants - failures}/{variants} WAVs written")
    return out_dir


def _slugify(word: str) -> str:
    """Lower-case, collapse runs of non-[a-z0-9_] into '_', strip edges.
    Raises WakeTrainerError if the result is empty."""
    slug = re.sub(r"[^a-z0-9_]+", "_", word.lower()).strip("_")
    if not slug:
        raise WakeTrainerError(f"word {word!r} produced an empty slug")
    return slug


def _train_loop(
    positives_dir: Path,
    neg_features_dir: Path,
    epochs: int,
    on_progress: ProgressFn,
    should_cancel: CancelFn,
) -> "torch.nn.Module":
    """Vendored PyTorch training loop from openWakeWord's
    notebooks/automatic_model_training.ipynb (and openwakeword/train.py).
    Returns the trained nn.Module. Raises TrainCancelled between epochs if
    should_cancel() returns True; raises WakeTrainerError for dep / NaN /
    unrecoverable train errors.

    Neg-feature pack layout expected in neg_features_dir:
        neg_features.npy  — shape (N, n_frames, 96) float32
        .ready            — presence marker

    Positive WAVs in positives_dir are embedded on-the-fly using
    openwakeword's AudioFeatures (ONNX melspec + embedding models).
    """
    # ── 1. Lazy-import + dep guard ────────────────────────────────────────
    import importlib.util as _iutil

    _required_pkgs = [
        "speechbrain", "audiomentations", "torch_audiomentations",
        "pronouncing", "acoustics", "mutagen",
    ]
    for _pkg in _required_pkgs:
        if _iutil.find_spec(_pkg) is None:
            raise WakeTrainerError(
                f"missing training dep: {_pkg!r}. "
                f"Run: pip install -r requirements.txt"
            )

    # speechbrain, audiomentations, torch_audiomentations, pronouncing,
    # and mutagen are imported by openwakeword internals; we don't need them
    # directly here but must confirm they're installed (done above).
    # acoustics.directivity has a broken scipy compat on newer scipy; mock it
    # so that acoustics.generator (the only submodule OWW uses) still loads.
    import sys as _sys
    import types as _types
    if "acoustics" not in _sys.modules:
        _sys.modules.setdefault(
            "acoustics.directivity",
            _types.ModuleType("acoustics.directivity"),
        )
    try:
        import speechbrain          # noqa: F401
        import audiomentations      # noqa: F401
        import torch_audiomentations  # noqa: F401
        import pronouncing          # noqa: F401
        import mutagen              # noqa: F401
    except ImportError as exc:
        raise WakeTrainerError(
            f"missing training dep: {exc.name!r}. "
            f"Run: pip install -r requirements.txt"
        ) from exc

    import numpy as np
    import torch
    from torch import optim
    from openwakeword.utils import AudioFeatures
    from openwakeword.train import Model as OWWModel

    on_progress(30.0, "train: computing positive features…")

    # ── 2. Compute features for positive WAVs ────────────────────────────
    import scipy.io.wavfile as wav_io

    F = AudioFeatures(device="cpu")

    pos_wav_paths = sorted(positives_dir.glob("*.wav"))
    if not pos_wav_paths:
        raise WakeTrainerError(f"no WAV files found in {positives_dir}")

    pos_clips = []
    for p in pos_wav_paths:
        sr, data = wav_io.read(str(p))
        if data.dtype != np.int16:
            data = (data * 32767).astype(np.int16)
        if data.ndim > 1:
            data = data[:, 0]
        pos_clips.append(data)

    # Pad / stack all clips to the same length
    clip_len = max(len(c) for c in pos_clips)
    clip_len = max(clip_len, 3200)  # at least 0.2s
    pos_array = np.zeros((len(pos_clips), clip_len), dtype=np.int16)
    for i, c in enumerate(pos_clips):
        pos_array[i, :len(c)] = c

    pos_features = F.embed_clips(pos_array, batch_size=len(pos_clips))  # (N, n_frames, 96)

    # ── 3. Load neg features ─────────────────────────────────────────────
    neg_npy = neg_features_dir / "neg_features.npy"
    if not neg_npy.exists():
        raise WakeTrainerError(
            f"neg_features.npy not found in {neg_features_dir}. "
            "Call ensure_negative_features() first."
        )
    neg_features = np.load(str(neg_npy))  # (N, n_frames, 96)

    # ── 4. Determine model input shape ───────────────────────────────────
    # openWakeWord models take (batch, n_frames, 96) where n_frames is the
    # number of embedding frames per example.  Normalise to whichever is
    # smaller so the positive/neg dims match.
    pos_n_frames = pos_features.shape[1]
    neg_n_frames = neg_features.shape[1]
    n_frames = min(pos_n_frames, neg_n_frames)
    if n_frames < 1:
        raise WakeTrainerError("computed n_frames < 1; audio clips may be too short")

    # Slice each feature matrix to n_frames along axis=1
    if pos_features.shape[1] > n_frames:
        pos_features = pos_features[:, :n_frames, :]
    if neg_features.shape[1] > n_frames:
        neg_features = neg_features[:, :n_frames, :]

    input_shape = (n_frames, 96)

    # ── 5. Build model (DNN, from openwakeword/train.py) ─────────────────
    oww = OWWModel(n_classes=1, input_shape=input_shape, model_type="dnn",
                   layer_dim=128, n_blocks=1)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    try:
        oww.model = oww.model.to(device)
    except RuntimeError as exc:
        if "out of memory" in str(exc).lower():
            on_progress(30.0, "CUDA OOM — falling back to CPU")
            torch.cuda.empty_cache()
            device = "cpu"
            oww.model = oww.model.to(device)
        else:
            raise

    optimizer = optim.Adam(oww.model.parameters(), lr=0.0001)
    loss_fn = torch.nn.functional.binary_cross_entropy

    # Build tensors — shape (N, n_frames, 96)
    X_pos = torch.from_numpy(pos_features).float()
    X_neg = torch.from_numpy(neg_features).float()
    y_pos = torch.ones(X_pos.shape[0], 1)
    y_neg = torch.zeros(X_neg.shape[0], 1)

    X_all = torch.cat([X_pos, X_neg], dim=0).to(device)
    y_all = torch.cat([y_pos, y_neg], dim=0).to(device)

    # ── 6. Epoch loop ─────────────────────────────────────────────────────
    for epoch in range(epochs):
        if should_cancel():
            raise TrainCancelled(f"cancelled before epoch {epoch + 1}")

        oww.model.train()

        # Shuffle
        perm = torch.randperm(X_all.shape[0])
        X_shuf = X_all[perm]
        y_shuf = y_all[perm]

        optimizer.zero_grad()
        preds = oww.model(X_shuf)
        loss = loss_fn(preds, y_shuf)

        if torch.isnan(loss):
            raise WakeTrainerError(f"training diverged at epoch {epoch}")

        loss.backward()
        optimizer.step()

        pct = 30.0 + 65.0 * (epoch + 1) / epochs
        on_progress(pct, f"epoch {epoch + 1}/{epochs}, loss={loss.item():.4f}")

    return oww.model


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
