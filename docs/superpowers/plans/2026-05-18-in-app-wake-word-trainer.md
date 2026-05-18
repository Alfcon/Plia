# In-App Wake-Word Trainer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make openWakeWord training a first-class Plia capability via a single shared engine and three thin frontends (Settings dialog, plugin tool, generated agent).

**Architecture:** One `core/wake_trainer.py` module owns the full pipeline (Piper TTS positives → cached negative features → vendored PyTorch training loop → ONNX export → drop into `models/wake/custom/`). Three frontends adapt that engine to their own progress/cancellation primitives. All heavy deps are lazy-imported so Plia's normal startup stays free.

**Tech Stack:** Python 3.11+, PyTorch, openWakeWord 0.6+, Piper TTS, ONNX, PySide6, qfluentwidgets, `pytest`.

**Spec:** `docs/superpowers/specs/2026-05-18-in-app-wake-word-trainer-design.md`

---

## Conventions

- Test runner: `/home/alfcon/miniconda3/envs/plia/bin/pytest`.
- All file paths are relative to the repo root (`/home/alfcon/Projects/Plia`).
- TDD throughout: write the test, watch it fail, write code, watch it pass, commit.
- Each task ends with a single commit. Use the commit message template at the end of the task.

---

## Task 1: Module skeleton + exception classes

**Files:**
- Create: `core/wake_trainer.py`
- Create: `tests/test_wake_trainer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wake_trainer.py
"""Tests for core.wake_trainer — in-app openWakeWord training pipeline."""

import pytest


def test_module_exposes_public_surface():
    from core import wake_trainer

    assert hasattr(wake_trainer, "train_wake_word")
    assert hasattr(wake_trainer, "ensure_negative_features")
    assert hasattr(wake_trainer, "synthesize_positives")
    assert issubclass(wake_trainer.TrainCancelled, Exception)
    assert issubclass(wake_trainer.WakeTrainerError, Exception)
    # Defaults
    assert "en_US-lessac-medium" in wake_trainer.DEFAULT_VOICES


def test_train_wake_word_is_not_implemented_yet():
    from core.wake_trainer import train_wake_word, WakeTrainerError

    with pytest.raises(NotImplementedError):
        train_wake_word("plia")
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.wake_trainer'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# core/wake_trainer.py
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


# ── Callback types ────────────────────────────────────────────────────────
ProgressFn = Callable[[float, str], None]   # (pct 0-100, message)
CancelFn = Callable[[], bool]               # returns True to stop


# ── Exceptions ────────────────────────────────────────────────────────────
class TrainCancelled(Exception):
    """should_cancel() returned True between stages or epochs."""


class WakeTrainerError(Exception):
    """Anything else that prevented training from completing."""


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
    raise NotImplementedError("train_wake_word — see Task 8")
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): module skeleton + exception classes"
```

---

## Task 2: Input validation

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_wake_trainer.py`:

```python
import pytest


@pytest.mark.parametrize("bad_word", ["", "   ", "@@@", "a" * 33, "💩"])
def test_validate_word_rejects_invalid(bad_word):
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="word"):
        train_wake_word(bad_word)


@pytest.mark.parametrize("good_word", ["plia", "Hey Jarvis", "ok nabu"])
def test_validate_word_accepts_reasonable(good_word):
    """Validation must NOT raise for these. The function will still raise
    NotImplementedError because Task 8 hasn't wired the pipeline yet."""
    from core.wake_trainer import train_wake_word
    with pytest.raises(NotImplementedError):
        train_wake_word(good_word)


@pytest.mark.parametrize("bad_variants", [0, 100, 50000, -5])
def test_validate_variants_rejects_out_of_range(bad_variants):
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="variants"):
        train_wake_word("plia", variants=bad_variants)


def test_validate_voices_rejects_unknown():
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="voice"):
        train_wake_word("plia", voices=["en_ZZ-fake-medium"])
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: the `WakeTrainerError`-expecting tests FAIL (they hit `NotImplementedError` instead). The `good_word` test PASSES (it expects `NotImplementedError`).

- [ ] **Step 3: Add the validation helper and call it from `train_wake_word`**

In `core/wake_trainer.py`, insert near the top (after the constants):

```python
import re

_WORD_RE = re.compile(r"^[A-Za-z0-9 ]{1,32}$")


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
```

And update `train_wake_word` to call validation **before** the NotImplementedError:

```python
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): validate word/variants/voices inputs"
```

---

## Task 3: Slug derivation

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

- [ ] **Step 1: Append the failing tests**

```python
@pytest.mark.parametrize("word, expected", [
    ("plia", "plia"),
    ("Hey Jarvis", "hey_jarvis"),
    ("OK  nabu", "ok_nabu"),
    ("plia_v2", "plia_v2"),
])
def test_slugify_word(word, expected):
    from core.wake_trainer import _slugify
    assert _slugify(word) == expected


def test_slugify_empty_raises():
    from core.wake_trainer import _slugify, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="empty"):
        _slugify("   ")
```

- [ ] **Step 2: Run, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py::test_slugify_word -v`
Expected: FAIL with `ImportError: cannot import name '_slugify'`.

- [ ] **Step 3: Implement `_slugify`**

Append to `core/wake_trainer.py`:

```python
def _slugify(word: str) -> str:
    """Lower-case, collapse runs of non-[a-z0-9_] into '_', strip edges.
    Raises WakeTrainerError if the result is empty."""
    slug = re.sub(r"[^a-z0-9_]+", "_", word.lower()).strip("_")
    if not slug:
        raise WakeTrainerError(f"word {word!r} produced an empty slug")
    return slug
```

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): word→slug derivation"
```

---

## Task 4: `ensure_negative_features` — download + cache

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

**Context:** openWakeWord's training pipeline needs a precomputed bundle of negative-speech features. Upstream hosts it at a URL pinned per-release. We cache it under `~/.plia/wake_trainer/neg_features/`. After download, we extract and store a marker file `~/.plia/wake_trainer/neg_features/.ready` so subsequent calls short-circuit.

The exact URL + checksum is pinned during this task. As of openWakeWord 0.6, the bundle is published as an asset on the openWakeWord GitHub releases page; see `https://github.com/dscripka/openWakeWord/releases` for the current release and pick the latest features archive. If the executor cannot determine a stable URL, they should raise a question in the PR rather than guess.

- [ ] **Step 1: Append the failing tests**

```python
def test_ensure_negative_features_is_idempotent(monkeypatch, tmp_path):
    """Second call must not re-download once the .ready marker is set."""
    from core import wake_trainer

    fake_root = tmp_path / "neg_features"
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", fake_root)

    download_calls = {"n": 0}
    def fake_download_and_unpack(dest: "Path") -> None:
        download_calls["n"] += 1
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".ready").write_text("ok\n")

    monkeypatch.setattr(
        wake_trainer, "_download_neg_features", fake_download_and_unpack
    )

    progress = []
    p1 = wake_trainer.ensure_negative_features(
        on_progress=lambda pct, msg: progress.append((pct, msg))
    )
    p2 = wake_trainer.ensure_negative_features(
        on_progress=lambda pct, msg: progress.append((pct, msg))
    )
    assert p1 == p2 == fake_root
    assert download_calls["n"] == 1, "second call must hit the cache"


def test_ensure_negative_features_retries_on_network_error(monkeypatch, tmp_path):
    """Three transient failures + one success → final call wins."""
    from core import wake_trainer

    fake_root = tmp_path / "neg_features"
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", fake_root)

    calls = {"n": 0}
    def flaky(dest: "Path") -> None:
        calls["n"] += 1
        if calls["n"] < 4:
            raise IOError("simulated network failure")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".ready").write_text("ok\n")
    monkeypatch.setattr(wake_trainer, "_download_neg_features", flaky)

    # _RETRY_DELAYS is shrunk for tests so this doesn't sleep for real.
    monkeypatch.setattr(wake_trainer, "_RETRY_DELAYS", [0.0, 0.0, 0.0])

    wake_trainer.ensure_negative_features()
    assert calls["n"] == 4


def test_ensure_negative_features_gives_up_after_retries(monkeypatch, tmp_path):
    from core import wake_trainer

    fake_root = tmp_path / "neg_features"
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", fake_root)
    monkeypatch.setattr(wake_trainer, "_RETRY_DELAYS", [0.0, 0.0, 0.0])
    monkeypatch.setattr(
        wake_trainer, "_download_neg_features",
        lambda dest: (_ for _ in ()).throw(IOError("nope"))
    )

    with pytest.raises(wake_trainer.WakeTrainerError, match="download"):
        wake_trainer.ensure_negative_features()
```

- [ ] **Step 2: Run, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k ensure_negative -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

Append to `core/wake_trainer.py`:

```python
import time
import urllib.request

# Pinned during implementation. The executor verifies that the URL still
# resolves on PR day; if not, update both URL and SHA-256.
_NEG_FEATURES_URL = (
    "https://github.com/dscripka/openWakeWord/releases/download/"
    "v0.5.1/openwakeword_features_2022_09_05.tar.gz"
)
_NEG_FEATURES_SHA256 = "PIN_DURING_IMPLEMENTATION"

_RETRY_DELAYS = [1.0, 4.0, 16.0]   # exponential-ish, total ~21s wall


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
            tar.extractall(dest)
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
    for attempt, delay in enumerate([0.0] + _RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            _download_neg_features(NEG_FEATURES_DIR)
            on_progress(10.0, "neg features: ready")
            return NEG_FEATURES_DIR
        except Exception as exc:
            last_err = exc
            # Half-written dir gets wiped so the next attempt is clean.
            import shutil
            if NEG_FEATURES_DIR.exists():
                shutil.rmtree(NEG_FEATURES_DIR, ignore_errors=True)

    raise WakeTrainerError(
        f"neg features: download failed after {len(_RETRY_DELAYS) + 1} attempts: {last_err}"
    )
```

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): ensure_negative_features with retry + cache"
```

---

## Task 5: `synthesize_positives` — Piper-based WAV rendering

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

- [ ] **Step 1: Append the failing tests**

```python
def test_synthesize_positives_writes_wav_files(monkeypatch, tmp_path):
    """Replaces PiperVoice.load with a fake so the test doesn't need a real
    voice model on disk."""
    from core import wake_trainer

    rendered: list[tuple[str, str]] = []

    class FakeVoice:
        def __init__(self, name: str):
            self.name = name

        def synthesize(self, text: str, wf, length_scale: float = 1.0):
            # WAV header + 0.2s of silence at 16 kHz mono.
            wf.writeframes(b"\x00\x00" * 3200)
            rendered.append((self.name, text))

    fake_loader = {"calls": 0}
    def fake_piper_load(name: str):
        fake_loader["calls"] += 1
        return FakeVoice(name)
    monkeypatch.setattr(wake_trainer, "_load_piper_voice", fake_piper_load)

    out_dir = tmp_path / "positives"
    wake_trainer.synthesize_positives(
        word="plia",
        voices=["en_US-lessac-medium", "en_US-amy-medium"],
        variants=12,
        out_dir=out_dir,
    )
    wavs = sorted(out_dir.glob("*.wav"))
    assert len(wavs) == 12, f"expected 12 wavs, got {len(wavs)}"
    # Both voices used at least once.
    voices_used = {name for name, _ in rendered}
    assert voices_used == {"en_US-lessac-medium", "en_US-amy-medium"}


def test_synthesize_positives_respects_cancellation(monkeypatch, tmp_path):
    """should_cancel() returning True between WAVs aborts cleanly."""
    from core import wake_trainer

    class FakeVoice:
        def synthesize(self, text, wf, length_scale=1.0):
            wf.writeframes(b"\x00\x00" * 3200)

    monkeypatch.setattr(wake_trainer, "_load_piper_voice", lambda n: FakeVoice())

    cancel_after = {"n": 3}
    def should_cancel():
        cancel_after["n"] -= 1
        return cancel_after["n"] <= 0

    with pytest.raises(wake_trainer.TrainCancelled):
        wake_trainer.synthesize_positives(
            word="plia",
            voices=["en_US-lessac-medium"],
            variants=100,
            out_dir=tmp_path / "p",
            should_cancel=should_cancel,
        )
```

- [ ] **Step 2: Run, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k synthesize -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement**

Append to `core/wake_trainer.py`:

```python
import random
import wave

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
```

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): synthesize_positives via Piper (with cancel/fail-soft)"
```

---

## Task 6: Vendored PyTorch training loop — `_train_loop`

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

**Context:** This task vendors the openWakeWord training loop from upstream's `notebooks/automatic_model_training.ipynb`. We're not writing a new ML algorithm — we're copying their proven loop and adapting it to call `on_progress` / `should_cancel`. The executor should:

1. Open the notebook in a browser:
   `https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb`
2. Identify the cells that build the model, dataloaders, optimizer, and training loop.
3. Copy that code into a private `_train_loop(...)` function in `core/wake_trainer.py`, replacing notebook-globals with function parameters.
4. Inject a `should_cancel()` check between epochs and an `on_progress(pct, msg)` call once per epoch with the live loss.
5. Return the trained `torch.nn.Module` so Task 7 can export it.

The expected scope of the vendored code is ~200-400 lines of PyTorch. If the upstream notebook has changed in ways that break this assumption, raise a PR comment rather than improvise.

**Error handling (per spec §7) that the vendored body MUST include:**

- Each `import` of a non-stdlib dep (`speechbrain`, `audiomentations`,
  `torch_audiomentations`, `pronouncing`, `acoustics`, `mutagen`) should
  be wrapped in `try / except ImportError` that re-raises as:
  ```python
  raise WakeTrainerError(
      f"missing training dep: {exc.name!r}. "
      f"Run: pip install -r requirements.txt"
  ) from exc
  ```
- Wrap the device-placement of the model in `try / except RuntimeError`
  to catch CUDA OOM. On OOM, fall back to CPU and emit a warning via
  `on_progress(pct, "CUDA OOM — falling back to CPU")`. The training run
  continues, just slower.
- Detect `NaN` loss (`torch.isnan(loss)` in the inner loop) and raise
  `WakeTrainerError(f"training diverged at epoch {epoch}")` so the user
  gets a precise failure point.

- [ ] **Step 1: Append the failing test**

```python
def test_train_loop_returns_module_and_reports_progress(monkeypatch, tmp_path):
    """Tiny end-to-end: 4 positives + a 4-feature fake neg pack, 2 epochs.
    We don't care about model quality — only that the loop runs, reports
    progress, and returns a torch.nn.Module."""
    pytest.importorskip("torch")
    from core import wake_trainer
    import torch

    # Build a fake positives dir with 4 silent 0.2s WAVs.
    positives = tmp_path / "positives"
    positives.mkdir()
    import wave
    for i in range(4):
        with wave.open(str(positives / f"{i:05d}.wav"), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 3200)

    # Fake neg-feature pack: a tiny .npy file the loop knows how to load.
    neg = tmp_path / "neg"
    neg.mkdir()
    (neg / ".ready").write_text("ok\n")
    # The actual format/filename pinned in the vendoring step; the executor
    # adjusts this fixture to whatever _train_loop expects to find.

    progress: list[tuple[float, str]] = []
    model = wake_trainer._train_loop(
        positives_dir=positives,
        neg_features_dir=neg,
        epochs=2,
        on_progress=lambda pct, msg: progress.append((pct, msg)),
        should_cancel=lambda: False,
    )
    assert isinstance(model, torch.nn.Module)
    assert any(30.0 <= pct <= 95.0 for pct, _ in progress)
    assert any("epoch" in msg for _, msg in progress)


def test_train_loop_cancel_between_epochs(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    from core import wake_trainer

    positives = tmp_path / "positives"
    positives.mkdir()
    import wave
    for i in range(4):
        with wave.open(str(positives / f"{i:05d}.wav"), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 3200)
    neg = tmp_path / "neg"; neg.mkdir(); (neg / ".ready").write_text("ok\n")

    epoch_count = {"n": 0}
    def cancel_after_one_epoch():
        epoch_count["n"] += 1
        return epoch_count["n"] > 1

    with pytest.raises(wake_trainer.TrainCancelled):
        wake_trainer._train_loop(
            positives_dir=positives,
            neg_features_dir=neg,
            epochs=10,
            on_progress=lambda pct, msg: None,
            should_cancel=cancel_after_one_epoch,
        )
```

- [ ] **Step 2: Run, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k train_loop -v`
Expected: FAIL with `AttributeError: module 'core.wake_trainer' has no attribute '_train_loop'`.

- [ ] **Step 3: Vendor the training loop**

In `core/wake_trainer.py`, add a `_train_loop(...)` function that follows the structure described in the Context block above. The executor reads the upstream notebook and copies the cells, adjusting:

- All notebook globals → function parameters
- `print(...)` / `display(...)` → `on_progress(pct, msg)` calls
- Each `for epoch in ...:` body starts with `if should_cancel(): raise TrainCancelled(...)`
- Return the trained `torch.nn.Module` at the end

Progress mapping for this stage: `30.0 + 65.0 * (epoch + 1) / epochs`. So a 100-epoch run climbs 30 → 95 across training.

```python
def _train_loop(
    positives_dir: Path,
    neg_features_dir: Path,
    epochs: int,
    on_progress: ProgressFn,
    should_cancel: CancelFn,
) -> "torch.nn.Module":
    """Vendored PyTorch training loop from openWakeWord's
    notebooks/automatic_model_training.ipynb. Returns the trained
    nn.Module. Raises TrainCancelled if should_cancel() returns True
    between epochs.

    See task 6 of docs/superpowers/plans/2026-05-18-in-app-wake-word-trainer.md
    for the vendoring procedure.
    """
    # Lazy imports so importing core.wake_trainer is cheap.
    import torch
    from torch import nn, optim
    # ... vendored imports of openwakeword.data helpers, speechbrain, etc.
    raise NotImplementedError(
        "Vendor the training loop from the upstream notebook here. "
        "Step-by-step instructions in plan task 6."
    )
```

The actual vendored body fills in below the imports. When done, `NotImplementedError` is gone.

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k train_loop -v`
Expected: 2 passed (may take 10–30 s on CPU for the tiny dataset).

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): vendor openWakeWord training loop"
```

---

## Task 7: ONNX export + verify

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

- [ ] **Step 1: Append the failing tests**

```python
def test_export_onnx_writes_loadable_file(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    from core import wake_trainer
    import torch

    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = torch.nn.Linear(96, 1)
        def forward(self, x):
            return self.fc(x)

    model = TinyModel()
    onnx_path = tmp_path / "tiny.onnx"

    # Bypass openwakeword.Model load by stubbing _verify_onnx_loads.
    monkeypatch.setattr(wake_trainer, "_verify_onnx_loads", lambda p: True)

    wake_trainer._export_onnx(model, onnx_path)
    assert onnx_path.exists()
    assert onnx_path.stat().st_size > 0


def test_export_onnx_deletes_file_on_verify_failure(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    from core import wake_trainer
    import torch

    class TinyModel(torch.nn.Module):
        def __init__(self): super().__init__(); self.fc = torch.nn.Linear(96, 1)
        def forward(self, x): return self.fc(x)

    monkeypatch.setattr(wake_trainer, "_verify_onnx_loads", lambda p: False)

    onnx_path = tmp_path / "tiny.onnx"
    with pytest.raises(wake_trainer.WakeTrainerError, match="verify"):
        wake_trainer._export_onnx(TinyModel(), onnx_path)
    assert not onnx_path.exists()
```

- [ ] **Step 2: Run, verify they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k export_onnx -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement**

Append to `core/wake_trainer.py`:

```python
# Opset matching the version openwakeword.Model consumes. Pin during impl;
# 17 is the current openwakeword runtime expectation as of 0.6.x.
_ONNX_OPSET = 17


def _verify_onnx_loads(path: Path) -> bool:
    """Try to load the freshly written ONNX through openwakeword's runtime.
    Returns True on success, False on any failure (so the caller can clean
    up without raising twice)."""
    try:
        from openwakeword.model import Model
        Model(wakeword_models=[str(path)], inference_framework="onnx")
        return True
    except Exception:
        return False


def _export_onnx(model: "torch.nn.Module", path: Path) -> None:
    """Export `model` to ONNX at `path`, then smoke-test it via
    openwakeword.Model. Deletes the file and raises WakeTrainerError if
    verification fails."""
    import torch
    path.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    # The exact dummy_input shape comes from the vendored training cell.
    # Adjust during Task 6 vendoring; for the tiny test model in Task 7
    # the input is (1, 96).
    dummy_input = torch.zeros(1, 96, dtype=torch.float32)
    try:
        torch.onnx.export(
            model, dummy_input, str(path),
            input_names=["input"], output_names=["output"],
            opset_version=_ONNX_OPSET,
        )
    except RuntimeError as exc:
        path.unlink(missing_ok=True)
        raise WakeTrainerError(f"onnx export failed: {exc}") from exc

    if not _verify_onnx_loads(path):
        path.unlink(missing_ok=True)
        raise WakeTrainerError(f"onnx export wrote {path} but verify load failed")
```

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k export_onnx -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): ONNX export with openwakeword load verify"
```

---

## Task 8: Wire everything together in `train_wake_word`

**Files:**
- Modify: `core/wake_trainer.py`
- Modify: `tests/test_wake_trainer.py`

- [ ] **Step 1: Append the failing test**

```python
def test_train_wake_word_end_to_end_with_mocks(monkeypatch, tmp_path):
    """All five stages are stubbed; we assert the orchestrator threads
    progress + cancel through correctly and returns the expected path."""
    from core import wake_trainer
    import torch

    out = tmp_path / "custom"
    monkeypatch.setattr(
        wake_trainer, "_default_output_dir", lambda: out
    )

    monkeypatch.setattr(
        wake_trainer, "ensure_negative_features",
        lambda on_progress=None: tmp_path / "neg",
    )

    def fake_synth(*, word, voices, variants, out_dir, on_progress=None, should_cancel=lambda: False):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "00000.wav").write_bytes(b"WAV")
        return out_dir
    monkeypatch.setattr(wake_trainer, "synthesize_positives", fake_synth)

    class TinyModel(torch.nn.Module):
        def __init__(self): super().__init__(); self.fc = torch.nn.Linear(96, 1)
        def forward(self, x): return self.fc(x)
    monkeypatch.setattr(
        wake_trainer, "_train_loop",
        lambda **kw: TinyModel(),
    )
    monkeypatch.setattr(wake_trainer, "_verify_onnx_loads", lambda p: True)

    progress: list[tuple[float, str]] = []
    result = wake_trainer.train_wake_word(
        "plia", variants=500, epochs=2,
        on_progress=lambda pct, msg: progress.append((pct, msg)),
    )
    assert result == out / "plia.onnx"
    assert result.exists()
    # Progress monotonically reaches 100.
    assert progress[-1][0] == 100.0
```

- [ ] **Step 2: Run, verify it fails**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py::test_train_wake_word_end_to_end_with_mocks -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement the orchestrator**

Replace the stub `train_wake_word` body in `core/wake_trainer.py` with:

```python
def _default_output_dir() -> Path:
    """Defers to core.wake_models so writes go where discovery reads."""
    from core.wake_models import models_dir
    return models_dir() / "custom"


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
    """End-to-end wake-word training. See module docstring."""
    voices = voices or list(DEFAULT_VOICES)
    _validate_inputs(word, variants, voices)
    slug = _slugify(word)
    output_dir = output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = output_dir / f"{slug}.onnx"

    import tempfile, shutil
    work = Path(tempfile.mkdtemp(prefix=f"wake_trainer_{slug}_"))
    positives_dir = work / "positives"

    try:
        if should_cancel(): raise TrainCancelled("cancelled before start")
        neg_features = ensure_negative_features(on_progress=on_progress)

        if should_cancel(): raise TrainCancelled("cancelled after neg features")
        synthesize_positives(
            word=word, voices=voices, variants=variants,
            out_dir=positives_dir,
            on_progress=on_progress, should_cancel=should_cancel,
        )

        if should_cancel(): raise TrainCancelled("cancelled before training")
        model = _train_loop(
            positives_dir=positives_dir,
            neg_features_dir=neg_features,
            epochs=epochs,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

        if should_cancel(): raise TrainCancelled("cancelled before export")
        _export_onnx(model, onnx_path)
        on_progress(100.0, f"done: {onnx_path}")
        return onnx_path
    except TrainCancelled:
        onnx_path.unlink(missing_ok=True)
        raise
    except WakeTrainerError:
        onnx_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        onnx_path.unlink(missing_ok=True)
        raise WakeTrainerError(f"unexpected failure: {exc}") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)
```

- [ ] **Step 4: Run, verify it passes**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -v`
Expected: every test in the file passes.

- [ ] **Step 5: Commit**

```bash
git add core/wake_trainer.py tests/test_wake_trainer.py
git commit -m "feat(wake-trainer): wire stages into train_wake_word with cleanup"
```

---

## Task 9: Cancellation regression tests

**Files:**
- Modify: `tests/test_wake_trainer.py`

These tests don't add new behaviour — they nail down the cancellation
contract so future refactors can't break it silently.

- [ ] **Step 1: Append**

```python
@pytest.mark.parametrize("cancel_after", ["before_start", "after_neg", "before_train", "before_export"])
def test_cancellation_at_each_stage(monkeypatch, tmp_path, cancel_after):
    from core import wake_trainer
    import torch

    out = tmp_path / "custom"
    monkeypatch.setattr(wake_trainer, "_default_output_dir", lambda: out)

    state = {"step": "before_start"}
    def should_cancel():
        return cancel_after == state["step"]

    def with_step(step, ret):
        def _(*a, **kw):
            state["step"] = step
            if should_cancel():
                raise wake_trainer.TrainCancelled(step)
            return ret
        return _

    monkeypatch.setattr(
        wake_trainer, "ensure_negative_features",
        with_step("after_neg", tmp_path / "neg"),
    )
    def synth_stub(*, word, voices, variants, out_dir, on_progress=None, should_cancel=lambda: False):
        out_dir.mkdir(parents=True, exist_ok=True)
        state["step"] = "before_train"
        if should_cancel():
            raise wake_trainer.TrainCancelled("synth")
        return out_dir
    monkeypatch.setattr(wake_trainer, "synthesize_positives", synth_stub)
    class TinyModel(torch.nn.Module):
        def __init__(self): super().__init__(); self.fc = torch.nn.Linear(96, 1)
        def forward(self, x): return self.fc(x)
    monkeypatch.setattr(
        wake_trainer, "_train_loop",
        with_step("before_export", TinyModel()),
    )
    monkeypatch.setattr(wake_trainer, "_verify_onnx_loads", lambda p: True)

    with pytest.raises(wake_trainer.TrainCancelled):
        wake_trainer.train_wake_word(
            "plia", variants=500, epochs=2,
            should_cancel=should_cancel,
        )

    # No half-written .onnx left behind.
    assert not (out / "plia.onnx").exists()
```

- [ ] **Step 2: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k cancellation_at_each_stage -v`
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wake_trainer.py
git commit -m "test(wake-trainer): cancellation at every stage boundary"
```

---

## Task 10: Cleanup-on-error regression test

**Files:**
- Modify: `tests/test_wake_trainer.py`

- [ ] **Step 1: Append**

```python
def test_failed_run_leaves_no_partial_files(monkeypatch, tmp_path):
    from core import wake_trainer
    out = tmp_path / "custom"
    monkeypatch.setattr(wake_trainer, "_default_output_dir", lambda: out)
    monkeypatch.setattr(
        wake_trainer, "ensure_negative_features",
        lambda on_progress=None: tmp_path / "neg",
    )
    def boom(**kw):
        raise wake_trainer.WakeTrainerError("synthetic failure")
    monkeypatch.setattr(wake_trainer, "synthesize_positives", boom)

    with pytest.raises(wake_trainer.WakeTrainerError):
        wake_trainer.train_wake_word("plia", variants=500)

    assert not (out / "plia.onnx").exists()
    # Temp work dirs cleaned: nothing matching wake_trainer_plia_*.
    import glob, tempfile, os
    leftovers = glob.glob(os.path.join(tempfile.gettempdir(), "wake_trainer_plia_*"))
    assert leftovers == [], f"orphan work dirs: {leftovers}"
```

- [ ] **Step 2: Run, verify it passes**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer.py -k failed_run_leaves_no_partial -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wake_trainer.py
git commit -m "test(wake-trainer): failed run cleans up partial files and tmp dirs"
```

---

## Task 11: Bundle training deps in `requirements.txt`; remove `requirements-train.txt`

**Files:**
- Modify: `requirements.txt`
- Delete: `requirements-train.txt`
- Modify: `README.md`
- Modify: `scripts/train_wake_word.py`

- [ ] **Step 1: Read current `requirements.txt`**

Run: `head -30 requirements.txt` to see the existing layout. The new deps go in a clearly labelled `# ── In-app wake-word trainer ──` section so it's obvious where they came from.

- [ ] **Step 2: Append the new section**

```
# ── In-app wake-word trainer (lazy-loaded by core/wake_trainer.py) ──
speechbrain>=1.0.0
audiomentations>=0.34.0
torch-audiomentations>=0.11.0
pronouncing>=0.2.0
acoustics>=0.2.6
mutagen>=1.47.0
torchinfo>=1.8.0
torchmetrics>=1.0.0
```

- [ ] **Step 3: Delete the now-redundant `requirements-train.txt`**

```bash
git rm requirements-train.txt
```

- [ ] **Step 4: Update `scripts/train_wake_word.py` to point at the in-app trainer**

Replace the body with:

```python
#!/usr/bin/env python3
"""CLI shim around core.wake_trainer.train_wake_word.

For most users the in-app paths (Settings → Voice & Audio → + Train Model…,
chat tool tool_train_wake_word, or the wake-word-trainer agent) are easier.
This script exists for headless / scripted use.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--word", required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--variants", type=int, default=5000)
    parser.add_argument("--epochs", type=int, default=100)
    args = parser.parse_args()

    from core.wake_trainer import train_wake_word, WakeTrainerError
    try:
        path = train_wake_word(
            args.word,
            variants=args.variants,
            epochs=args.epochs,
            output_dir=args.output,
            on_progress=lambda pct, msg: print(f"[{pct:5.1f}%] {msg}"),
        )
    except WakeTrainerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Update the README's "Adding a custom wake word" section**

Find the section currently pointing at the Colab notebook (`grep -n "Adding a custom wake word" README.md`) and rewrite step 2:

```markdown
2. **Train your own** without leaving Plia:
   - **GUI:** Settings → Voice & Audio → **+ Train Model…**, type the word,
     click Train, wait ~20–40 min on CPU. The new model appears in the
     Wake Words list automatically.
   - **Voice/chat:** say *"Plia, train a wake word for 'plia'"* — the
     `tool_train_wake_word` plugin handles it and reports progress in chat.
   - **Headless / scripted:** `python scripts/train_wake_word.py --word "plia"`.

   First run downloads openWakeWord's negative-feature pack (~hundreds of MB)
   and caches it in `~/.plia/wake_trainer/neg_features/`. Subsequent trainings
   skip that step.
```

- [ ] **Step 6: Install the new deps + run the full suite**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pip install -r requirements.txt`
Then: `/home/alfcon/miniconda3/envs/plia/bin/pytest -q`
Expected: all tests pass, no import errors.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt scripts/train_wake_word.py README.md
git rm requirements-train.txt
git commit -m "feat(wake-trainer): bundle training deps; retire requirements-train.txt stub"
```

---

## Task 12: Settings UI — `TrainWakeWordDialog`

**Files:**
- Create: `gui/components/train_wake_word_dialog.py`
- Create: `tests/test_train_wake_word_dialog.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_train_wake_word_dialog.py
"""TrainWakeWordDialog UI smoke tests."""

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_dialog_has_word_input_and_buttons(qapp):
    from gui.components.train_wake_word_dialog import TrainWakeWordDialog
    dlg = TrainWakeWordDialog()
    assert dlg.word_input is not None
    assert dlg.variants_slider is not None
    assert dlg.train_btn is not None
    assert dlg.cancel_btn is not None
    assert dlg.progress_bar is not None


def test_dialog_train_emits_started_signal(qapp, monkeypatch):
    """Clicking Train with a valid word kicks off the worker thread.
    We mock the worker so the test doesn't actually train."""
    from gui.components.train_wake_word_dialog import TrainWakeWordDialog
    dlg = TrainWakeWordDialog()
    dlg.word_input.setText("plia")

    started = {"n": 0}
    monkeypatch.setattr(
        dlg, "_start_worker", lambda: started.__setitem__("n", started["n"] + 1)
    )
    dlg.train_btn.click()
    assert started["n"] == 1


def test_dialog_rejects_empty_word(qapp):
    from gui.components.train_wake_word_dialog import TrainWakeWordDialog
    dlg = TrainWakeWordDialog()
    dlg.word_input.setText("")
    dlg.train_btn.click()
    qapp.processEvents()
    # Train button stays enabled; an inline error label is shown.
    assert dlg.error_label.text() != ""
    assert dlg.train_btn.isEnabled()
```

- [ ] **Step 2: Run, verify failure**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_train_wake_word_dialog.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the dialog**

```python
# gui/components/train_wake_word_dialog.py
"""Modal that runs core.wake_trainer.train_wake_word in a QThread."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSlider,
    QPushButton, QProgressBar, QListWidget, QListWidgetItem, QFrame,
)

from core.wake_trainer import (
    DEFAULT_VOICES, train_wake_word, TrainCancelled, WakeTrainerError,
)


class _Worker(QObject):
    progress = Signal(float, str)
    finished = Signal(object)   # Path on success, None on cancel/error
    error = Signal(str)

    def __init__(self, word: str, variants: int, voices: list[str]):
        super().__init__()
        self._word = word
        self._variants = variants
        self._voices = voices
        self._cancel = False

    def request_cancel(self):
        self._cancel = True

    @Slot()
    def run(self):
        try:
            path = train_wake_word(
                self._word,
                variants=self._variants,
                voices=self._voices,
                on_progress=lambda pct, msg: self.progress.emit(pct, msg),
                should_cancel=lambda: self._cancel,
            )
            self.finished.emit(path)
        except TrainCancelled:
            self.finished.emit(None)
        except WakeTrainerError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"unexpected: {exc}")


class TrainWakeWordDialog(QDialog):
    """Modal: type a word, click Train, watch progress, get an .onnx."""

    trained = Signal(object)   # Path of the new model; emitted on success

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Train new wake word")
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)

        # Word input
        outer.addWidget(QLabel("Word:", self))
        self.word_input = QLineEdit(self)
        self.word_input.setPlaceholderText("e.g. plia")
        outer.addWidget(self.word_input)

        # Variants slider
        row = QHBoxLayout()
        row.addWidget(QLabel("Variants:", self))
        self.variants_slider = QSlider(Qt.Horizontal, self)
        self.variants_slider.setRange(500, 20000)
        self.variants_slider.setValue(5000)
        self.variants_label = QLabel("5000", self)
        self.variants_slider.valueChanged.connect(
            lambda v: self.variants_label.setText(str(v))
        )
        row.addWidget(self.variants_slider, 1)
        row.addWidget(self.variants_label)
        outer.addLayout(row)

        # Voices multi-select
        outer.addWidget(QLabel("Voices:", self))
        self.voice_list = QListWidget(self)
        for v in DEFAULT_VOICES:
            item = QListWidgetItem(v)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.voice_list.addItem(item)
        self.voice_list.setMaximumHeight(120)
        outer.addWidget(self.voice_list)

        # Progress
        self.stage_label = QLabel("", self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        outer.addWidget(self.stage_label)
        outer.addWidget(self.progress_bar)

        # Inline error
        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #ef5350;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)

        # Buttons
        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel", self)
        self.train_btn = QPushButton("Train", self)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.train_btn)
        outer.addLayout(btn_row)

        self.train_btn.clicked.connect(self._on_train)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

    # ── Handlers ──────────────────────────────────────────────────────────
    def _selected_voices(self) -> list[str]:
        out = []
        for i in range(self.voice_list.count()):
            item = self.voice_list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.text())
        return out

    def _on_train(self):
        word = self.word_input.text().strip()
        if not word:
            self.error_label.setText("Word is required.")
            return
        voices = self._selected_voices()
        if not voices:
            self.error_label.setText("Select at least one voice.")
            return
        self.error_label.setText("")
        self.train_btn.setEnabled(False)
        self._start_worker()

    def _start_worker(self):
        word = self.word_input.text().strip()
        variants = self.variants_slider.value()
        voices = self._selected_voices()

        self._thread = QThread(self)
        self._worker = _Worker(word, variants, voices)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, pct: float, msg: str):
        self.progress_bar.setValue(int(pct))
        self.stage_label.setText(msg)

    def _on_finished(self, path):
        self._thread.quit()
        self._thread.wait()
        if path is None:
            # cancelled
            self.reject()
        else:
            self.trained.emit(path)
            self.accept()

    def _on_error(self, msg: str):
        self._thread.quit()
        self._thread.wait()
        self.error_label.setText(msg)
        self.train_btn.setEnabled(True)

    def _on_cancel(self):
        if self._worker is not None:
            self._worker.request_cancel()
        else:
            self.reject()
```

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_train_wake_word_dialog.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add gui/components/train_wake_word_dialog.py tests/test_train_wake_word_dialog.py
git commit -m "feat(wake-trainer): Settings dialog with QThread worker"
```

---

## Task 13: Wire `+ Train Model…` button into `MultiWakeWordCard`

**Files:**
- Modify: `gui/tabs/settings.py`
- Modify: `tests/test_settings_layout.py`

- [ ] **Step 1: Append the failing test**

In `tests/test_settings_layout.py`, append:

```python
def test_multi_wake_word_card_has_train_button(qapp):
    host, tab = _build_tab(qapp)
    card = tab.wake_words_card
    assert hasattr(card, "train_btn"), "missing + Train Model… button"
    assert card.train_btn.text().startswith("+ Train"), card.train_btn.text()
```

- [ ] **Step 2: Run, verify it fails**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_settings_layout.py::test_multi_wake_word_card_has_train_button -v`
Expected: FAIL with `AttributeError: ... train_btn`.

- [ ] **Step 3: Add the button to `MultiWakeWordCard`**

In `gui/tabs/settings.py`, locate the `MultiWakeWordCard.__init__` footer
section (search for `+ Add Model…`):

```python
        footer = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Model…", self)
        self.reload_btn = QPushButton("↻ Reload", self)
        footer.addWidget(self.add_btn)
        footer.addWidget(self.reload_btn)
```

Change to:

```python
        footer = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Model…", self)
        self.train_btn = QPushButton("+ Train Model…", self)
        self.reload_btn = QPushButton("↻ Reload", self)
        footer.addWidget(self.add_btn)
        footer.addWidget(self.train_btn)
        footer.addWidget(self.reload_btn)
```

Wire its click handler near the other `clicked.connect` lines:

```python
        self.train_btn.clicked.connect(self._on_train_model)
```

And add the method on the class:

```python
    def _on_train_model(self):
        from gui.components.train_wake_word_dialog import TrainWakeWordDialog
        dlg = TrainWakeWordDialog(self)
        dlg.trained.connect(lambda _path: self._rebuild_rows())
        dlg.trained.connect(lambda _path: self.models_changed.emit())
        dlg.exec()
```

- [ ] **Step 4: Run, verify it passes**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_settings_layout.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/settings.py tests/test_settings_layout.py
git commit -m "feat(settings-ui): + Train Model… button opens TrainWakeWordDialog"
```

---

## Task 14: Bundled plugin — `plugins/wake_trainer.py`

**Files:**
- Create: `plugins/wake_trainer.py`
- Create: `tests/test_plugin_wake_trainer.py`

**Context:** Plia auto-loads `tool_*` functions from `~/.plia_ai/plugins/`. We commit the source at `plugins/wake_trainer.py` in the repo; the existing plugin loader copies / discovers them on launch (see `core/plugins.py:64-115`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin_wake_trainer.py
"""Plugin tool sanity tests — no real training, just contract."""

from pathlib import Path

import pytest


def test_tool_train_wake_word_validates_word():
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "plugins_wake_trainer",
        Path(__file__).parent.parent / "plugins" / "wake_trainer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    result = mod.tool_train_wake_word({"word": ""})
    assert result["success"] is False
    assert "word" in result["message"].lower()


def test_tool_train_wake_word_delegates_to_core(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "plugins_wake_trainer",
        Path(__file__).parent.parent / "plugins" / "wake_trainer.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    captured = {}
    def fake_train(word, **kwargs):
        captured["word"] = word
        captured["variants"] = kwargs.get("variants")
        return Path("/tmp/fake.onnx")

    monkeypatch.setattr(mod, "train_wake_word", fake_train)
    result = mod.tool_train_wake_word({"word": "plia", "variants": 1000})
    assert result["success"] is True
    assert captured["word"] == "plia"
    assert captured["variants"] == 1000
    assert result["data"]["path"].endswith("fake.onnx")
```

- [ ] **Step 2: Run, verify failure**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_plugin_wake_trainer.py -v`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Write the plugin**

```python
# plugins/wake_trainer.py
"""Plia plugin — train a wake word from chat/agents.

Usage:
    {
        "tool": "wake_trainer:train_wake_word",
        "params": {"word": "plia", "variants": 5000, "voices": [...]}
    }
"""

from __future__ import annotations

from pathlib import Path

from core.wake_trainer import (
    train_wake_word, WakeTrainerError, TrainCancelled, DEFAULT_VOICES,
)


def tool_train_wake_word(params: dict) -> dict:
    """Train an openWakeWord model. Long-running (~20-40 min on CPU)."""
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
```

- [ ] **Step 4: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_plugin_wake_trainer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add plugins/wake_trainer.py tests/test_plugin_wake_trainer.py
git commit -m "feat(wake-trainer): plugin tool tool_train_wake_word"
```

---

## Task 15: Agent template in `core/agent_builder.py`

**Files:**
- Modify: `core/agent_builder.py`
- Create or modify: `tests/test_agent_builder_wake_trainer.py`

- [ ] **Step 1: Read the existing template pattern**

Run: `grep -n "_SEARCH_DOWNLOAD_TEMPLATE\|detect_build_intent" core/agent_builder.py | head -10`
Read the `_SEARCH_DOWNLOAD_TEMPLATE` literal and `detect_build_intent` function so the new template follows the same shape.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_agent_builder_wake_trainer.py
"""Agent template for wake-word trainer renders to valid Python."""

import ast


def test_wake_trainer_template_renders_to_valid_python():
    from core.agent_builder import _WAKE_TRAINER_TEMPLATE
    src = _WAKE_TRAINER_TEMPLATE.format(
        slug="wake_word_trainer",
        timestamp="2026-05-18 12:00:00",
        word="plia",
        variants=5000,
        file_path="/tmp/wake_word_trainer.py",
    )
    ast.parse(src)   # raises SyntaxError on invalid template


def test_detect_build_intent_matches_train_a_wake_word():
    from core.agent_builder import detect_build_intent
    intent = detect_build_intent("train a wake word for plia")
    assert intent is not None
    assert intent.get("kind") == "wake_trainer"
```

- [ ] **Step 3: Run, verify failure**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_agent_builder_wake_trainer.py -v`
Expected: FAIL on import — `_WAKE_TRAINER_TEMPLATE` does not exist.

- [ ] **Step 4: Add the template + intent matcher**

In `core/agent_builder.py`, add a new template literal alongside `_SEARCH_DOWNLOAD_TEMPLATE`:

```python
# ── Wake-word trainer template ─────────────────────────────────────────────
_WAKE_TRAINER_TEMPLATE = '''\
"""
Agent: {slug}
Built by Plia AgentBuilder on {timestamp}
Task: Train an openWakeWord model for the wake phrase "{word}".
Run standalone: python "{file_path}"
"""

import sys
from pathlib import Path

# Plia repo root is the parent of this agent's directory.
THIS = Path(__file__).resolve()
REPO_ROOT = THIS.parents[2]   # adjust if your layout differs
sys.path.insert(0, str(REPO_ROOT))

from core.wake_trainer import train_wake_word, WakeTrainerError


WORD = "{word}"
VARIANTS = {variants}


def run(**kwargs) -> str:
    """Entry point. Returns a human-readable status string."""
    word = kwargs.get("word", WORD)
    variants = int(kwargs.get("variants", VARIANTS))
    try:
        path = train_wake_word(
            word, variants=variants,
            on_progress=lambda pct, msg: print(f"[{{pct:5.1f}}%] {{msg}}"),
        )
        return f"Trained wake word {{word!r}} → {{path}}"
    except WakeTrainerError as exc:
        return f"Training failed: {{exc}}"


if __name__ == "__main__":
    print(run())
'''
```

Add a pattern for wake-word intent in `_BUILD_PATTERNS`:

```python
# (existing patterns above) …
# wake-word trainer
r"(?:train|build|make)\s+(?:a\s+)?wake[- ]?word\s+(?:for\s+|named\s+)?[\"']?([A-Za-z0-9 ]+)[\"']?",
```

In `detect_build_intent`, after the existing pattern matching, add a fast-path that classifies these matches under `kind="wake_trainer"` with the captured word:

```python
def detect_build_intent(text: str) -> dict | None:
    # ... existing logic ...
    # Wake-word trainer fast path:
    import re as _re
    m = _re.search(
        r"\b(?:train|build|make)\s+(?:a\s+)?wake[- ]?word\s+"
        r"(?:for\s+|named\s+)?[\"']?([A-Za-z0-9 ]+)[\"']?",
        text, _re.IGNORECASE,
    )
    if m:
        return {"kind": "wake_trainer", "word": m.group(1).strip()}
    return None
```

Wire the template into the build dispatch (the place that branches on `intent["kind"]`):

```python
if intent.get("kind") == "wake_trainer":
    src = _WAKE_TRAINER_TEMPLATE.format(
        slug=slug, timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        word=intent["word"], variants=5000, file_path=str(file_path),
    )
    # ... reuse the existing write+register path
```

- [ ] **Step 5: Run, verify they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_agent_builder_wake_trainer.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add core/agent_builder.py tests/test_agent_builder_wake_trainer.py
git commit -m "feat(wake-trainer): AgentBuilder template + 'train a wake word…' intent"
```

---

## Task 16: Slow integration test

**Files:**
- Create: `tests/test_wake_trainer_integration.py`

- [ ] **Step 1: Write the slow test**

```python
# tests/test_wake_trainer_integration.py
"""End-to-end wake-trainer test. Slow (~30-60 s); gated by RUN_SLOW=1."""

import os
import shutil
import wave
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SLOW") != "1",
    reason="set RUN_SLOW=1 to run the slow wake-trainer integration test",
)


def test_train_tiny_wake_model_end_to_end(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    from core import wake_trainer

    # 1. Fake neg features so we don't download hundreds of MB in CI.
    neg = tmp_path / "neg"
    neg.mkdir()
    (neg / ".ready").write_text("ok\n")
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", neg)
    # If _train_loop expects specific files under NEG_FEATURES_DIR, the
    # executor populates them here using a minimal openwakeword precomputed
    # feature stub (~few MB committed under tests/fixtures/wake_trainer/).

    # 2. Tiny output dir.
    out = tmp_path / "custom"
    monkeypatch.setattr(wake_trainer, "_default_output_dir", lambda: out)

    # 3. Train with a tiny variant count + 2 epochs.
    path = wake_trainer.train_wake_word(
        "plia", variants=500, epochs=2,
        on_progress=lambda pct, msg: print(f"[{pct:5.1f}%] {msg}"),
    )

    assert path == out / "plia.onnx"
    assert path.exists()
    assert path.stat().st_size > 1024   # at least 1 KB

    # 4. Loadable by openwakeword.
    from openwakeword.model import Model
    m = Model(wakeword_models=[str(path)], inference_framework="onnx")
    assert "plia" in m.prediction_buffer
```

- [ ] **Step 2: Run with `RUN_SLOW=1` to verify**

Run: `RUN_SLOW=1 /home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer_integration.py -v`
Expected: 1 passed (slow). If the fixture neg-features pack isn't suitable, the test fails with a clear error pointing at the fixture path.

Run again without the env var: `/home/alfcon/miniconda3/envs/plia/bin/pytest tests/test_wake_trainer_integration.py -v`
Expected: 1 skipped.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wake_trainer_integration.py tests/fixtures/wake_trainer/
git commit -m "test(wake-trainer): opt-in end-to-end integration test"
```

---

## Done Criteria

- `core/wake_trainer.py` exposes `train_wake_word`, `ensure_negative_features`, `synthesize_positives`, `TrainCancelled`, `WakeTrainerError`, and `DEFAULT_VOICES`.
- ~13 unit tests + 1 dialog test + 2 plugin tests + 2 agent-template tests pass on the fast path; integration test passes with `RUN_SLOW=1`.
- `requirements.txt` bundles the 8 training deps; `requirements-train.txt` deleted.
- Settings → Voice & Audio → **+ Train Model…** opens `TrainWakeWordDialog`, runs training in a `QThread`, drops the new model into `models/wake/custom/`, and reloads the wake-words list on success.
- `tool_train_wake_word` is registered as a plugin and callable via chat/agents.
- `AgentBuilder` matches "train a wake word for X" and writes a standalone agent that calls `train_wake_word`.
- Manual smoke (post-merge): train word "plia" with `variants=500` from each of the three entry points; verify the resulting `.onnx` loads in WakeDetector and triggers on the spoken word.
