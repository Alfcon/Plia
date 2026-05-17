# openWakeWord Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fully replace Picovoice Porcupine with openWakeWord as Plia's wake-word engine, with a multi-select Settings UI, per-model sensitivity sliders, bundled pre-trained models including a trained "Plia" model, custom `.onnx` upload, and one-time migration from the old single-string setting.

**Architecture:** A new `core/wake_detector.py` QThread owns the microphone, runs openWakeWord inference with per-model confidence thresholds, and emits a `wake_word_detected` Qt signal. RealtimeSTT runs with `use_microphone=False` (transcription only) and receives audio via its `feed_audio()` API. Settings UI replaces the old single-pick combo with a multi-select card; settings are reconciled with `models/wake/{bundled,custom}/*.onnx` discovery on startup.

**Tech Stack:** Python 3.11, PySide6, openwakeword, onnxruntime, RealtimeSTT, PyAudio, Piper TTS (training only), pytest.

**Reference spec:** `docs/superpowers/specs/2026-05-17-openwakeword-replacement-design.md`

---

## File map

**Create:**
- `core/wake_detector.py` — WakeDetector QThread, model loading, per-model thresholds, cooldown.
- `core/wake_models.py` — pure helpers: `discover_wake_models()`, `reconcile_with_settings()`, `models_dir()`.
- `models/wake/bundled/.gitkeep`
- `models/wake/custom/.gitkeep`
- `models/wake/bundled/hey_jarvis.onnx`
- `models/wake/bundled/alexa.onnx`
- `models/wake/bundled/hey_mycroft.onnx`
- `models/wake/bundled/ok_nabu.onnx`
- `models/wake/bundled/hey_rhasspy.onnx`
- `models/wake/bundled/plia.onnx`
- `models/wake/README.md`
- `scripts/train_wake_word.py`
- `requirements-train.txt`
- `tests/test_settings_migration.py`
- `tests/test_wake_models.py`
- `tests/test_wake_detector.py`

**Modify:**
- `core/settings_store.py` — new `voice.wake_models` default; migration in `_load()`.
- `core/stt.py` — remove `SUPPORTED_WAKE_WORDS`, `WAKE_WORDS`, `_get_wake_word()`, `_get_sensitivity()`; remove Porcupine init params; set `use_microphone=False`; expose `feed_audio(chunk)`.
- `core/voice_assistant.py` — instantiate `WakeDetector`; connect signal to `_on_wake_word`; remove old `wake_word` log line.
- `gui/tabs/settings.py` — remove `wake_word_card` + `wake_sensitivity_card`; add `MultiWakeWordCard` + `MultiWakeWordRow`.
- `gui/settings.py` — same replacement (parallel duplicate).
- `config.py` — remove `WAKE_WORD_DETECTION_METHOD`, `USE_PORCUPINE_WAKE_WORD`, `WAKE_WORD`, `WAKE_WORD_SENSITIVITY`, `WAKE_WORD_CONFIRMATION_COUNT`.
- `requirements.txt` — add `openwakeword>=0.6.0`, `onnxruntime>=1.16.0`; remove `pvporcupine`.
- `.gitignore` — ignore `models/wake/custom/*.onnx` (keep `.gitkeep`).

---

## Task 1: Dependencies and directory scaffolding

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-train.txt`
- Create: `models/wake/bundled/.gitkeep`
- Create: `models/wake/custom/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Update `requirements.txt`**

Find the line containing `pvporcupine>=1.9.0,<2` and replace the wake-word section with:

```
openwakeword>=0.6.0             # Open-source wake-word engine (replaces Porcupine)
onnxruntime>=1.16.0             # ONNX runtime backend for openwakeword
```

Remove the `pvporcupine>=1.9.0,<2` line.

- [ ] **Step 2: Create `requirements-train.txt`**

```
# Extra dependencies for scripts/train_wake_word.py
# Not needed to run Plia — only for training new wake-word models.
piper-tts>=1.2.0
openwakeword>=0.6.0
onnx>=1.15.0
torch>=2.0
```

- [ ] **Step 3: Create `models/wake/bundled/.gitkeep` and `models/wake/custom/.gitkeep`**

Run:
```bash
mkdir -p models/wake/bundled models/wake/custom
touch models/wake/bundled/.gitkeep models/wake/custom/.gitkeep
```

- [ ] **Step 4: Update `.gitignore`**

Append:
```
# User-uploaded wake-word models (bundled ones are committed)
models/wake/custom/*.onnx
!models/wake/custom/.gitkeep
```

- [ ] **Step 5: Install new dependencies in the active env**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pip install openwakeword onnxruntime`
Expected: installs without errors. Verify with `/home/alfcon/miniconda3/envs/plia/bin/python -c "import openwakeword, onnxruntime; print(openwakeword.__version__)"`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-train.txt .gitignore models/wake/bundled/.gitkeep models/wake/custom/.gitkeep
git commit -m "deps: add openwakeword + onnxruntime, scaffold models/wake/"
```

---

## Task 2: Settings schema + migration

**Files:**
- Modify: `core/settings_store.py`
- Test: `tests/test_settings_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_migration.py`:

```python
"""Tests for one-time migration from voice.wake_word → voice.wake_models."""
import json
from pathlib import Path

import pytest

from core import settings_store


def _seed_old_config(tmp_path: Path, wake_word: str = "jarvis", sensitivity: float = 0.4) -> Path:
    cfg_dir = tmp_path / ".plia"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "settings.json"
    cfg_file.write_text(json.dumps({
        "voice": {
            "wake_word": wake_word,
            "sensitivity": sensitivity,
            "enabled": True,
        }
    }))
    return cfg_file


def _load(monkeypatch, tmp_path):
    """Force the singleton to use a fresh tmp_path config."""
    monkeypatch.setattr(settings_store, "Path", Path)  # ensure Path is the real one
    store = settings_store.SettingsStore.__new__(settings_store.SettingsStore)
    # re-init the way __init__ does, but pointing at tmp
    import threading
    store._lock = threading.RLock()
    store._settings = {}
    store._settings_dir = tmp_path / ".plia"
    store._settings_file = tmp_path / ".plia" / "settings.json"
    # QObject.__init__ requires explicit call
    from PySide6.QtCore import QObject
    QObject.__init__(store)
    store._load()
    return store


def test_jarvis_migrates_to_hey_jarvis_plus_plia(tmp_path, monkeypatch):
    _seed_old_config(tmp_path, wake_word="jarvis")
    store = _load(monkeypatch, tmp_path)

    models = store.get("voice.wake_models")
    assert isinstance(models, list)
    ids = [m["id"] for m in models]
    assert "hey_jarvis" in ids
    assert "plia" in ids
    enabled_ids = {m["id"] for m in models if m["enabled"]}
    assert enabled_ids == {"hey_jarvis", "plia"}

    # Old keys removed
    assert store.get("voice.wake_word") is None
    assert store.get("voice.sensitivity") is None


def test_unknown_word_falls_back_with_toast_flag(tmp_path, monkeypatch):
    _seed_old_config(tmp_path, wake_word="americano")
    store = _load(monkeypatch, tmp_path)

    enabled_ids = {m["id"] for m in store.get("voice.wake_models") if m["enabled"]}
    assert enabled_ids == {"hey_jarvis", "plia"}
    assert store.get("voice._migration_toast_pending") is True


def test_migration_is_idempotent(tmp_path, monkeypatch):
    _seed_old_config(tmp_path, wake_word="jarvis")
    store1 = _load(monkeypatch, tmp_path)
    snap1 = store1.get("voice.wake_models")

    store2 = _load(monkeypatch, tmp_path)
    snap2 = store2.get("voice.wake_models")
    assert snap1 == snap2


def test_existing_new_schema_left_alone(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".plia"
    cfg_dir.mkdir()
    custom_models = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.6, "builtin": True}
    ]
    (cfg_dir / "settings.json").write_text(json.dumps({
        "voice": {"wake_models": custom_models, "enabled": True}
    }))
    store = _load(monkeypatch, tmp_path)
    assert store.get("voice.wake_models") == custom_models
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_settings_migration.py -v`
Expected: all four tests FAIL (`voice.wake_models` doesn't exist yet).

- [ ] **Step 3: Update `DEFAULT_SETTINGS` in `core/settings_store.py`**

Replace the entire `"voice": { ... }` block (lines 52–59) with:

```python
    # ── Voice/STT settings ───────────────────────────────────────────────
    "voice": {
        # Multi-select wake-word models. Each entry:
        #   id:          stable identifier (filename stem of the .onnx)
        #   display:     human label shown in Settings
        #   path:        relative to models/wake/  (e.g. "bundled/plia.onnx")
        #   enabled:     bool — whether this model is loaded by WakeDetector
        #   sensitivity: 0.0–1.0 — openwakeword score threshold
        #   builtin:     True for ships-with-Plia models; False for user uploads
        "wake_models": [
            {"id": "hey_jarvis",  "display": "Hey Jarvis",  "path": "bundled/hey_jarvis.onnx",
             "enabled": True,  "sensitivity": 0.5, "builtin": True},
            {"id": "plia",        "display": "Plia",        "path": "bundled/plia.onnx",
             "enabled": True,  "sensitivity": 0.5, "builtin": True},
            {"id": "alexa",       "display": "Alexa",       "path": "bundled/alexa.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
            {"id": "hey_mycroft", "display": "Hey Mycroft", "path": "bundled/hey_mycroft.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
            {"id": "ok_nabu",     "display": "OK Nabu",     "path": "bundled/ok_nabu.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
            {"id": "hey_rhasspy", "display": "Hey Rhasspy", "path": "bundled/hey_rhasspy.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
        ],
        "enabled":                True,
        "auto_start":             True,
        "startup_greeting":       True,
        "stt_energy_threshold":   300,
    },
```

- [ ] **Step 4: Add migration function and call it from `_load`**

Add this method to `SettingsStore` class (right after `_deep_merge`, around line 192):

```python
    def _migrate_voice_wake_word(self):
        """One-time migration: voice.wake_word (str) → voice.wake_models (list).

        Runs when the loaded config still has the old single-string key. Maps
        the old default 'jarvis' to ['hey_jarvis', 'plia'] enabled; any other
        Porcupine keyword (which has no openWakeWord equivalent) gets the
        same default plus a flag so the UI can show a one-time toast.
        """
        voice = self._settings.get("voice", {})
        if "wake_word" not in voice:
            return  # Already migrated or never seen the old schema.

        old_word = voice.pop("wake_word", None)
        voice.pop("sensitivity", None)
        voice.pop("sensitivity_pct", None)

        # voice.wake_models comes pre-seeded from DEFAULT_SETTINGS via _deep_merge,
        # but a user with an old config may not have it — ensure it's present.
        if "wake_models" not in voice or not voice["wake_models"]:
            voice["wake_models"] = [
                m.copy() for m in DEFAULT_SETTINGS["voice"]["wake_models"]
            ]

        if old_word and old_word != "jarvis":
            voice["_migration_toast_pending"] = True

        self._settings["voice"] = voice
```

Modify `_load` to call it (insert the call before `self._save()` at line 160):

```python
    def _load(self):
        """Load settings from disk; missing keys are filled from defaults."""
        with self._lock:
            if self._settings_file.exists():
                try:
                    with open(self._settings_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    self._settings = self._deep_merge(DEFAULT_SETTINGS.copy(), loaded)
                    self._migrate_voice_wake_word()
                    self._save()
                except (json.JSONDecodeError, IOError) as exc:
                    print(f"[Settings] Error loading settings: {exc}. Using defaults.")
                    self._settings = DEFAULT_SETTINGS.copy()
                    self._save()
            else:
                self._settings = DEFAULT_SETTINGS.copy()
                self._save()
```

- [ ] **Step 5: Run the tests to confirm they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_settings_migration.py -v`
Expected: all four tests PASS.

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x --ignore=tests/test_wake_detector.py --ignore=tests/test_wake_models.py -q`
Expected: same number of pass/fail as before this task (188 passing).

- [ ] **Step 7: Commit**

```bash
git add core/settings_store.py tests/test_settings_migration.py
git commit -m "feat(settings): migrate voice.wake_word → voice.wake_models list"
```

---

## Task 3: Model discovery helper

**Files:**
- Create: `core/wake_models.py`
- Test: `tests/test_wake_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wake_models.py`:

```python
"""Tests for wake-model discovery and reconciliation."""
from pathlib import Path

import pytest

from core import wake_models


def _make_models_dir(tmp_path: Path) -> Path:
    base = tmp_path / "models" / "wake"
    (base / "bundled").mkdir(parents=True)
    (base / "custom").mkdir(parents=True)
    return base


def test_discover_finds_bundled_and_custom_onnx(tmp_path):
    base = _make_models_dir(tmp_path)
    (base / "bundled" / "hey_jarvis.onnx").write_bytes(b"x")
    (base / "custom" / "myword.onnx").write_bytes(b"x")
    (base / "bundled" / "README.md").write_text("ignore me")

    found = wake_models.discover_wake_models(base)
    by_id = {m["id"]: m for m in found}

    assert "hey_jarvis" in by_id
    assert by_id["hey_jarvis"]["builtin"] is True
    assert by_id["hey_jarvis"]["path"] == "bundled/hey_jarvis.onnx"

    assert "myword" in by_id
    assert by_id["myword"]["builtin"] is False
    assert by_id["myword"]["path"] == "custom/myword.onnx"


def test_reconcile_adds_new_file_with_enabled_false(tmp_path):
    base = _make_models_dir(tmp_path)
    (base / "custom" / "new.onnx").write_bytes(b"x")

    existing = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
    ]
    reconciled = wake_models.reconcile_with_settings(existing, base)
    by_id = {m["id"]: m for m in reconciled}

    assert "plia" in by_id
    assert by_id["plia"]["enabled"] is True  # untouched
    assert "new" in by_id
    assert by_id["new"]["enabled"] is False
    assert by_id["new"]["sensitivity"] == 0.5
    assert by_id["new"]["builtin"] is False


def test_reconcile_marks_missing_file_broken(tmp_path):
    base = _make_models_dir(tmp_path)
    # No files exist on disk.
    existing = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
    ]
    reconciled = wake_models.reconcile_with_settings(existing, base)
    plia = next(m for m in reconciled if m["id"] == "plia")
    assert plia.get("broken") is True
    # Settings row is preserved, not removed.
    assert len(reconciled) == 1


def test_reconcile_clears_broken_flag_when_file_returns(tmp_path):
    base = _make_models_dir(tmp_path)
    (base / "bundled" / "plia.onnx").write_bytes(b"x")
    existing = [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True, "broken": True},
    ]
    reconciled = wake_models.reconcile_with_settings(existing, base)
    plia = next(m for m in reconciled if m["id"] == "plia")
    assert plia.get("broken", False) is False


def test_discover_collision_suffix(tmp_path):
    """A custom .onnx with the same stem as a bundled one gets a _1 suffix."""
    base = _make_models_dir(tmp_path)
    (base / "bundled" / "plia.onnx").write_bytes(b"x")
    (base / "custom" / "plia.onnx").write_bytes(b"x")

    found = wake_models.discover_wake_models(base)
    ids = sorted(m["id"] for m in found)
    assert "plia" in ids
    assert "plia_1" in ids


def test_models_dir_resolves_under_project_root():
    p = wake_models.models_dir()
    assert p.name == "wake"
    assert p.parent.name == "models"
    assert p.is_absolute()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_wake_models.py -v`
Expected: all six tests FAIL (`core.wake_models` doesn't exist).

- [ ] **Step 3: Implement `core/wake_models.py`**

Create the file:

```python
"""Wake-word model discovery and reconciliation with settings.

The settings list (`voice.wake_models`) is the source of truth for *enabled*
and *sensitivity*. Discovery is a one-way reconciliation:
  - new files on disk → appended as disabled rows
  - settings rows whose file is missing → flagged broken (not removed)
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

DEFAULT_SENSITIVITY = 0.5


def models_dir() -> Path:
    """Absolute path to the project's models/wake/ directory."""
    # core/wake_models.py → parents[1] is the project root.
    return Path(__file__).resolve().parents[1] / "models" / "wake"


def _iter_onnx(base: Path) -> Iterable[tuple[Path, bool]]:
    """Yield (onnx_path, is_builtin) for every .onnx under base/{bundled,custom}/."""
    for subdir, builtin in (("bundled", True), ("custom", False)):
        d = base / subdir
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.onnx")):
            yield path, builtin


def discover_wake_models(base: Path) -> list[dict]:
    """Scan base/{bundled,custom}/*.onnx and return a list of model entries.

    If a custom file shares a stem with a bundled file, the custom entry's
    `id` is suffixed with `_1`, `_2`, … to disambiguate. Bundled wins the
    bare stem.
    """
    entries: list[dict] = []
    seen_ids: set[str] = set()

    # Two passes so bundled keeps the bare stem.
    bundled = [(p, True) for p, b in _iter_onnx(base) if b]
    custom = [(p, False) for p, b in _iter_onnx(base) if not b]

    for path, builtin in bundled + custom:
        stem = path.stem
        candidate = stem
        n = 1
        while candidate in seen_ids:
            candidate = f"{stem}_{n}"
            n += 1
        seen_ids.add(candidate)
        subdir = "bundled" if builtin else "custom"
        entries.append({
            "id": candidate,
            "display": stem.replace("_", " ").title(),
            "path": f"{subdir}/{path.name}",
            "enabled": False,
            "sensitivity": DEFAULT_SENSITIVITY,
            "builtin": builtin,
        })
    return entries


def reconcile_with_settings(existing: list[dict], base: Path) -> list[dict]:
    """Merge disk-discovered models with the settings list.

    - Files on disk not in settings → appended as disabled.
    - Settings rows whose path is missing on disk → `broken: True`.
    - Settings rows whose path exists → `broken` cleared if previously set.
    """
    out = [m.copy() for m in existing]
    by_path = {m["path"]: m for m in out}

    discovered = discover_wake_models(base)
    discovered_paths = {d["path"] for d in discovered}

    for m in out:
        full = base / m["path"]
        if full.exists():
            if m.get("broken"):
                m.pop("broken", None)
        else:
            m["broken"] = True

    for d in discovered:
        if d["path"] not in by_path:
            out.append(d)

    return out
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_wake_models.py -v`
Expected: all six tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/wake_models.py tests/test_wake_models.py
git commit -m "feat(wake): discovery + settings reconciliation for .onnx models"
```

---

## Task 4: Bundle pre-trained openWakeWord models

**Files:**
- Create: `models/wake/bundled/hey_jarvis.onnx`
- Create: `models/wake/bundled/alexa.onnx`
- Create: `models/wake/bundled/hey_mycroft.onnx`
- Create: `models/wake/bundled/ok_nabu.onnx`
- Create: `models/wake/bundled/hey_rhasspy.onnx`
- Create: `models/wake/README.md`

- [ ] **Step 1: Download openwakeword's pretrained model bundle into the package cache**

Run:
```bash
/home/alfcon/miniconda3/envs/plia/bin/python -c "import openwakeword; openwakeword.utils.download_models()"
```
Expected: prints "Downloaded model files to <path>". No errors.

- [ ] **Step 2: Locate the downloaded `.onnx` files and verify the expected set**

Run:
```bash
/home/alfcon/miniconda3/envs/plia/bin/python -c "import openwakeword, glob, os; d=os.path.join(os.path.dirname(openwakeword.__file__), 'resources','models'); print(sorted(glob.glob(os.path.join(d,'*.onnx'))))"
```
Expected output should include files matching: `alexa_v0.1.onnx` (or similar), `hey_jarvis_v0.1.onnx`, `hey_mycroft_v0.1.onnx`, `hey_rhasspy_v0.1.onnx`, `ok_nabu_v0.1.onnx`.

If filenames differ (versioned suffix), strip the suffix when copying so our `id` matches the design (`hey_jarvis`, not `hey_jarvis_v0.1`).

- [ ] **Step 3: Copy the five bundled models with normalized filenames**

Run:
```bash
PKG_DIR=$(/home/alfcon/miniconda3/envs/plia/bin/python -c "import openwakeword, os; print(os.path.join(os.path.dirname(openwakeword.__file__), 'resources','models'))")
for word in alexa hey_jarvis hey_mycroft hey_rhasspy ok_nabu; do
  src=$(ls "$PKG_DIR"/${word}*.onnx | head -1)
  cp "$src" "models/wake/bundled/${word}.onnx"
  echo "Copied $src -> models/wake/bundled/${word}.onnx"
done
ls -la models/wake/bundled/
```
Expected: five `.onnx` files in `models/wake/bundled/`, each between 100KB and 5MB.

- [ ] **Step 4: Verify the bundled models load via openwakeword**

Run:
```bash
/home/alfcon/miniconda3/envs/plia/bin/python -c "
import openwakeword
from openwakeword.model import Model
paths = ['models/wake/bundled/hey_jarvis.onnx','models/wake/bundled/alexa.onnx','models/wake/bundled/hey_mycroft.onnx','models/wake/bundled/hey_rhasspy.onnx','models/wake/bundled/ok_nabu.onnx']
m = Model(wakeword_models=paths, inference_framework='onnx')
print('Loaded:', list(m.prediction_buffer.keys()))
"
```
Expected: prints `Loaded: ['hey_jarvis', 'alexa', 'hey_mycroft', 'hey_rhasspy', 'ok_nabu']` (or similar normalized names).

If the prediction-buffer keys differ from our `id` values, adjust the bundled filenames so the openwakeword-derived key matches our id. The Model uses the filename stem when no explicit name is given.

- [ ] **Step 5: Create `models/wake/README.md`**

```markdown
# Wake-word models

Plia uses [openWakeWord](https://github.com/dscripka/openWakeWord) for wake-word
detection. Models live in two folders:

- `bundled/` — committed to the repo, ships with Plia.
- `custom/` — gitignored, user-supplied `.onnx` files.

## Bundled set

| File | Wake phrase | Source |
|---|---|---|
| `hey_jarvis.onnx` | "Hey Jarvis" | openWakeWord pretrained |
| `alexa.onnx` | "Alexa" | openWakeWord pretrained |
| `hey_mycroft.onnx` | "Hey Mycroft" | openWakeWord pretrained |
| `ok_nabu.onnx` | "OK Nabu" | openWakeWord pretrained |
| `hey_rhasspy.onnx` | "Hey Rhasspy" | openWakeWord pretrained |
| `plia.onnx` | "Plia" | Trained for this project — see below |

## Adding a custom wake word

Two ways:

1. **Settings UI** — open Settings → Voice & Audio → click "Add Model…",
   pick a `.onnx` file. Plia copies it into `models/wake/custom/` and
   refreshes the model list.
2. **Filesystem** — drop a `.onnx` file directly into `models/wake/custom/`
   and click "Reload" in the Settings UI.

The filename stem becomes the model id (e.g., `myword.onnx` → `myword`).

## Training your own model

```bash
python scripts/train_wake_word.py --word "plia" --output models/wake/bundled/plia.onnx
```

See `scripts/train_wake_word.py --help` for options. Requires the
`requirements-train.txt` extras (`pip install -r requirements-train.txt`).

The pipeline:

1. Generates ~5000 synthetic positive samples via Piper TTS.
2. Downloads openWakeWord's negative dataset (RIRs + noise + general speech).
3. Trains a custom binary classifier with openWakeWord's training helpers.
4. Exports the result to ONNX.

Training takes ~30 minutes on a modern CPU; less on a GPU.
```

- [ ] **Step 6: Commit**

```bash
git add models/wake/bundled/*.onnx models/wake/README.md
git commit -m "feat(wake): bundle 5 pretrained openWakeWord models + README"
```

---

## Task 5: WakeDetector skeleton + model loading

**Files:**
- Create: `core/wake_detector.py`
- Test: `tests/test_wake_detector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_wake_detector.py`:

```python
"""Tests for WakeDetector (mic-owning openWakeWord wrapper)."""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core import wake_detector


@pytest.fixture
def fake_oww_model():
    """A MagicMock standing in for openwakeword.model.Model.

    `.predict(chunk)` returns whatever was last set in `scores`.
    """
    fake = MagicMock()
    fake.scores = {"plia": 0.0, "hey_jarvis": 0.0}
    fake.predict = lambda chunk: dict(fake.scores)
    return fake


@pytest.fixture
def settings_two_models():
    return [
        {"id": "plia", "display": "Plia", "path": "bundled/plia.onnx",
         "enabled": True, "sensitivity": 0.5, "builtin": True},
        {"id": "hey_jarvis", "display": "Hey Jarvis", "path": "bundled/hey_jarvis.onnx",
         "enabled": True, "sensitivity": 0.6, "builtin": True},
    ]


def test_load_models_passes_only_enabled_paths(tmp_path, settings_two_models):
    """Disabled models must not be passed to openwakeword.Model."""
    settings_two_models[1]["enabled"] = False
    captured = {}

    def fake_model_ctor(wakeword_models, inference_framework):
        captured["paths"] = wakeword_models
        m = MagicMock()
        m.prediction_buffer = {"plia": []}
        return m

    with patch.object(wake_detector, "_oww_model_class", fake_model_ctor):
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()

    assert any(p.endswith("plia.onnx") for p in captured["paths"])
    assert all(not p.endswith("hey_jarvis.onnx") for p in captured["paths"])


def test_thresholds_populated_from_settings(tmp_path, settings_two_models):
    with patch.object(wake_detector, "_oww_model_class") as mock_ctor:
        mock_ctor.return_value = MagicMock(prediction_buffer={"plia": [], "hey_jarvis": []})
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()
    assert d.thresholds == {"plia": 0.5, "hey_jarvis": 0.6}


def test_load_models_skips_broken_onnx_and_keeps_others(tmp_path, settings_two_models):
    """If one .onnx fails to load, the other still works and a warning is emitted."""

    def fake_model_ctor(wakeword_models, inference_framework):
        # First call: raise. Second call (single model): succeed.
        if len(wakeword_models) > 1:
            raise RuntimeError("bad .onnx")
        m = MagicMock()
        m.prediction_buffer = {"plia": []}
        return m

    with patch.object(wake_detector, "_oww_model_class", fake_model_ctor):
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        errors = []
        d.error.connect(errors.append)
        d._load_models()

    assert "plia" in d.thresholds  # at least one model loaded
    assert any("could not load" in e.lower() or "skipped" in e.lower() for e in errors)
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_wake_detector.py -v`
Expected: all three tests FAIL (`core.wake_detector` doesn't exist).

- [ ] **Step 3: Implement `core/wake_detector.py` skeleton**

```python
"""WakeDetector — owns the microphone and runs openWakeWord inference.

RealtimeSTT is configured with use_microphone=False; the detector reads
PyAudio chunks, runs openWakeWord prediction, and either:
  - feeds the chunk to RealtimeSTT (when it's actively transcribing post-wake)
  - or emits wake_word_detected(model_id) when any enabled model crosses
    its sensitivity threshold.
"""
from __future__ import annotations

import time
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
        single_models = []
        for m in enabled:
            path = str(self._models_base / m["path"])
            try:
                model_class(wakeword_models=[path], inference_framework="onnx")
                single_models.append(path)
                working[m["id"]] = float(m["sensitivity"])
            except Exception as exc:
                self.error.emit(f"Could not load wake model '{m['id']}': {exc} — skipped.")
        if single_models:
            self._oww = model_class(wakeword_models=single_models, inference_framework="onnx")
            self.thresholds = working
        else:
            self._oww = None
            self.thresholds = {}

    def run(self) -> None:
        """Subclass hook — real implementation arrives in Task 6."""
        # Placeholder so the QThread doesn't error if started before Task 6.
        self._running = True
        while self._running:
            self.msleep(50)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_wake_detector.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/wake_detector.py tests/test_wake_detector.py
git commit -m "feat(wake): WakeDetector skeleton + resilient model loading"
```

---

## Task 6: WakeDetector audio loop, thresholding, cooldown

**Files:**
- Modify: `core/wake_detector.py`
- Modify: `tests/test_wake_detector.py`

- [ ] **Step 1: Append new failing tests to `tests/test_wake_detector.py`**

Append:

```python
import numpy as np


@pytest.fixture
def detector_with_fake_models(tmp_path, settings_two_models):
    with patch.object(wake_detector, "_oww_model_class") as mock_ctor:
        oww = MagicMock()
        oww.prediction_buffer = {"plia": [], "hey_jarvis": []}
        oww.scores = {"plia": 0.0, "hey_jarvis": 0.0}
        oww.predict = lambda chunk: dict(oww.scores)
        mock_ctor.return_value = oww
        d = wake_detector.WakeDetector(
            wake_models=settings_two_models,
            models_base=tmp_path,
            recorder=None,
        )
        d._load_models()
    return d, oww


def test_predict_above_threshold_emits_signal(detector_with_fake_models):
    d, oww = detector_with_fake_models
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.9, "hey_jarvis": 0.0}
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)

    assert emitted == ["plia"]


def test_predict_below_threshold_does_not_emit(detector_with_fake_models):
    d, oww = detector_with_fake_models
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.4, "hey_jarvis": 0.5}  # both below their thresholds
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)

    assert emitted == []


def test_cooldown_suppresses_second_trigger(detector_with_fake_models):
    d, oww = detector_with_fake_models
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.9}
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)
    d._process_chunk(chunk)
    assert emitted == ["plia"]   # only the first


def test_cooldown_expires(detector_with_fake_models, monkeypatch):
    d, oww = detector_with_fake_models
    fake_time = [1000.0]
    monkeypatch.setattr(wake_detector.time, "monotonic", lambda: fake_time[0])
    emitted = []
    d.wake_word_detected.connect(emitted.append)

    oww.scores = {"plia": 0.9}
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)
    fake_time[0] += wake_detector.COOLDOWN_SEC + 0.1
    d._process_chunk(chunk)
    assert emitted == ["plia", "plia"]


def test_chunk_fed_to_recorder_when_listening(detector_with_fake_models):
    d, oww = detector_with_fake_models
    recorder = MagicMock()
    recorder.is_listening = True
    d._recorder = recorder

    oww.scores = {"plia": 0.9}  # would otherwise fire
    chunk = np.zeros(wake_detector.CHUNK_SAMPLES, dtype=np.int16)
    d._process_chunk(chunk)

    recorder.feed_audio.assert_called_once()
    # predict() must NOT be consulted while listening — emit nothing
    emitted = []
    d.wake_word_detected.connect(emitted.append)
    assert emitted == []
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_wake_detector.py -v`
Expected: the five new tests FAIL (`_process_chunk` doesn't exist).

- [ ] **Step 3: Implement `_process_chunk` in `core/wake_detector.py`**

Replace the placeholder `run()` and add `_process_chunk`:

```python
    def _process_chunk(self, chunk) -> None:
        """Handle one PyAudio chunk: feed recorder OR run wake detection.

        Called both by the audio loop and directly by tests.
        """
        recorder = self._recorder
        if recorder is not None and getattr(recorder, "is_listening", False):
            # Transcription is in progress — pipe audio in, skip detection.
            recorder.feed_audio(chunk)
            return

        if self._oww is None or not self.thresholds:
            return

        if time.monotonic() < self._cooldown_until:
            return

        scores = self._oww.predict(chunk)
        for model_id, score in scores.items():
            threshold = self.thresholds.get(model_id)
            if threshold is None:
                continue
            if score >= threshold:
                self._cooldown_until = time.monotonic() + COOLDOWN_SEC
                self.wake_word_detected.emit(model_id)
                return  # one trigger per chunk

    def run(self) -> None:
        """Main audio loop. Opens PyAudio, reads chunks, calls _process_chunk."""
        import pyaudio
        import numpy as np

        self._running = True
        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(
                rate=SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=CHUNK_SAMPLES,
            )
        except Exception as exc:
            self.error.emit(f"Could not open microphone: {exc}")
            pa.terminate()
            return

        try:
            while self._running:
                try:
                    raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
                except OSError as exc:
                    self.error.emit(f"Mic read error: {exc}")
                    break
                chunk = np.frombuffer(raw, dtype=np.int16)
                self._process_chunk(chunk)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()
```

- [ ] **Step 4: Run all wake_detector tests**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/test_wake_detector.py -v`
Expected: all eight tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/wake_detector.py tests/test_wake_detector.py
git commit -m "feat(wake): audio loop, per-model thresholding, cooldown"
```

---

## Task 7: Strip Porcupine from `core/stt.py`; switch to external audio feed

**Files:**
- Modify: `core/stt.py`

- [ ] **Step 1: Remove the legacy wake-word constants**

Delete lines 137–168 in `core/stt.py` (the `SUPPORTED_WAKE_WORDS`,
`DEFAULT_WAKE_WORD`, `WAKE_WORDS`, and surrounding comments). Keep
`_setup_stt_logging` and what follows.

- [ ] **Step 2: Delete `_get_wake_word()` and `_get_sensitivity()` helpers**

In `core/stt.py`, delete the two functions around lines 408–430.

- [ ] **Step 3: Update `STTListener.__init__` and `initialize`**

Find the `__init__` and `initialize` methods (around lines 455 and 552
respectively). Remove the `_wake_word` and `_sensitivity` lookups. The
recorder now runs with `use_microphone=False` and no wake-word backend.

Replace the `AudioToTextRecorder(...)` call (lines 606–622) with:

```python
            try:
                self.recorder = AudioToTextRecorder(
                    model=REALTIMESTT_MODEL,
                    language="en",
                    device=device,
                    spinner=False,
                    use_microphone=False,         # WakeDetector owns the mic.
                    silero_sensitivity=silero_sens,
                    silero_deactivity_detection=silero_deact,
                    webrtc_sensitivity=3,
                    no_log_file=True,
                )
            finally:
```

Also remove the lines that print the wake word and sensitivity from
`__init__` and `initialize` (the `print(f"{CYAN}[STT] Wake word…)` lines
around 466 and 557). Replace with a single line in `initialize` after
recorder creation:

```python
            print(f"{CYAN}[STT] ✓ Recorder ready (transcription-only, mic owned by WakeDetector){RESET}")
```

- [ ] **Step 4: Expose `feed_audio` and `is_listening` passthroughs**

Add these methods to `STTListener` (anywhere after `initialize`):

```python
    def feed_audio(self, chunk) -> None:
        """Forward a PCM int16 numpy chunk into RealtimeSTT."""
        if self.recorder is not None:
            self.recorder.feed_audio(chunk.tobytes() if hasattr(chunk, "tobytes") else chunk)

    @property
    def is_listening(self) -> bool:
        """True while RealtimeSTT is actively transcribing post-wake."""
        return bool(self.recorder and getattr(self.recorder, "is_recording", False))
```

(`is_recording` is RealtimeSTT's attribute for "currently capturing speech";
adjust to the exact attribute name if RealtimeSTT changed it — grep
`audio_recorder.py` for `is_recording` vs `is_listening` and use what
matches.)

- [ ] **Step 5: Replace the wake-word callback with an explicit `start_listening()` trigger**

Find the part of `STTListener` that responded to a Porcupine wake-word
firing (around line 648, `_on_wakeword_detected`). Replace its body to
make it the public method WakeDetector will call after firing:

```python
    def start_listening(self) -> None:
        """Begin transcription. Called by WakeDetector after a wake fires."""
        print(f"\n{CYAN}[STT] 👂 Wake word detected — listening…{RESET}")
        if self.recorder:
            self.recorder.start()
        if self.wake_word_callback:
            self.wake_word_callback()
```

Remove the old `_on_wakeword_detected` if it remains.

- [ ] **Step 6: Run the full test suite**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x -q`
Expected: all tests pass (188 + new wake-detector and migration tests).

- [ ] **Step 7: Commit**

```bash
git add core/stt.py
git commit -m "refactor(stt): strip Porcupine, use_microphone=False, expose feed_audio"
```

---

## Task 8: Wire WakeDetector into VoiceAssistant

**Files:**
- Modify: `core/voice_assistant.py`

- [ ] **Step 1: Import WakeDetector and settings helpers**

At the top of `core/voice_assistant.py`, near the other `core` imports:

```python
from core.wake_detector import WakeDetector
from core.wake_models import models_dir, reconcile_with_settings
from core.settings_store import settings as app_settings
```

Remove `WAKE_WORD` from the `config` import line.

- [ ] **Step 2: Add `wake_detector` attribute and create it during `initialize`**

In `VoiceAssistant.__init__`, add (after `self.stt_listener: Optional[STTListener] = None`):

```python
        self.wake_detector: Optional[WakeDetector] = None
```

In `VoiceAssistant.initialize`, after the STT initialization succeeds and
before the TTS section, add:

```python
            # ── Wake detector ────────────────────────────────────────────
            print(f"{CYAN}[VoiceAssistant] Initializing wake detector…{RESET}")
            wake_models = app_settings.get("voice.wake_models", [])
            wake_models = reconcile_with_settings(wake_models, models_dir())
            app_settings.set("voice.wake_models", wake_models)

            self.wake_detector = WakeDetector(
                wake_models=wake_models,
                models_base=models_dir(),
                recorder=self.stt_listener,  # uses .is_listening and .feed_audio
            )
            self.wake_detector._load_models()
            self.wake_detector.wake_word_detected.connect(self._on_wake_model_fired)
            self.wake_detector.error.connect(lambda msg: print(f"{GRAY}[Wake] {msg}{RESET}"))
            print(f"{CYAN}[VoiceAssistant] ✓ Wake detector ready ({len(self.wake_detector.thresholds)} models loaded){RESET}")
```

- [ ] **Step 3: Add the model-id-aware callback and update the existing one**

Add a new method next to `_on_wake_word`:

```python
    def _on_wake_model_fired(self, model_id: str):
        """Called when the WakeDetector signals — pipes through to STT."""
        print(f"{CYAN}[VoiceAssistant] Wake model '{model_id}' fired.{RESET}")
        if self.stt_listener:
            self.stt_listener.start_listening()
```

- [ ] **Step 4: Start/stop the detector with the assistant**

Modify `VoiceAssistant.start` — replace lines that read `voice.wake_word`
(around line 126–128) with:

```python
        self.running = True
        self.stt_listener.start()
        if self.wake_detector:
            self.wake_detector.start()
        loaded = ", ".join(sorted(self.wake_detector.thresholds.keys())) if self.wake_detector else "(none)"
        print(f"{CYAN}[VoiceAssistant] Voice assistant started. Listening for: {GREEN}{loaded}{RESET}")
```

In `VoiceAssistant.stop`, add (before any existing recorder shutdown):

```python
        if self.wake_detector:
            self.wake_detector.stop()
            self.wake_detector = None
```

- [ ] **Step 5: Run the full test suite**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add core/voice_assistant.py
git commit -m "feat(voice): wire WakeDetector → STTListener.start_listening()"
```

---

## Task 9: Remove dead Porcupine constants in `config.py`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Delete the wake-word block in `config.py`**

Delete lines 48–54 in `config.py`:

```
WAKE_WORD_DETECTION_METHOD = "transcription"
...
USE_PORCUPINE_WAKE_WORD = False
WAKE_WORD = "jarvis"
WAKE_WORD_SENSITIVITY = 0.4
WAKE_WORD_CONFIRMATION_COUNT = 1
```

- [ ] **Step 2: Grep for any remaining references**

Run: `grep -rn "WAKE_WORD\|USE_PORCUPINE\|SUPPORTED_WAKE_WORDS\|_get_wake_word\|_get_sensitivity" --include='*.py' .`
Expected: no remaining matches (or only matches you intend to keep — e.g., in docs).

If any references remain (e.g., in `core/voice_assistant.py`'s old import), remove them.

- [ ] **Step 3: Run the full test suite + import Plia at the package level**

Run:
```bash
/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x -q
/home/alfcon/miniconda3/envs/plia/bin/python -c "import core.voice_assistant; import core.stt; import core.wake_detector; print('imports ok')"
```
Expected: tests pass, imports succeed.

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "chore: remove dead Porcupine constants from config.py"
```

---

## Task 10: Settings UI — MultiWakeWordRow widget

**Files:**
- Modify: `gui/tabs/settings.py`

- [ ] **Step 1: Add `MultiWakeWordRow` widget class**

Insert this class in `gui/tabs/settings.py` near the other Card classes
(after `SliderCard`, around line 220):

```python
class MultiWakeWordRow(QWidget):
    """One row in MultiWakeWordCard: checkbox | label | slider | (optional ✕)."""

    changed = Signal()        # any user edit
    delete_requested = Signal(str)  # custom-row delete; emits model_id

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self._entry = entry
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        self.check = QCheckBox(self)
        self.check.setChecked(bool(entry.get("enabled")))
        self.check.toggled.connect(self._on_toggle)
        layout.addWidget(self.check)

        label_text = entry.get("display", entry.get("id", "?"))
        if entry.get("broken"):
            label_text = f"⚠ {label_text}  (file not found)"
            self.check.setEnabled(False)
        self.label = QLabel(label_text, self)
        self.label.setMinimumWidth(140)
        layout.addWidget(self.label)

        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(float(entry.get("sensitivity", 0.5)) * 100)))
        self.slider.setEnabled(not entry.get("broken", False))
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider, 1)

        self.value_lbl = QLabel(f"{entry.get('sensitivity', 0.5):.2f}", self)
        self.value_lbl.setMinimumWidth(40)
        layout.addWidget(self.value_lbl)

        # 300ms debounce on slider writes.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self._flush_slider)

        if not entry.get("builtin", True) or entry.get("broken"):
            delete_btn = QPushButton("✕", self)
            delete_btn.setFixedWidth(28)
            delete_btn.clicked.connect(
                lambda: self.delete_requested.emit(entry["id"])
            )
            layout.addWidget(delete_btn)

    def _on_toggle(self, checked: bool):
        self._entry["enabled"] = bool(checked)
        self.changed.emit()

    def _on_slider(self, value: int):
        self.value_lbl.setText(f"{value / 100:.2f}")
        self._save_timer.start()

    def _flush_slider(self):
        self._entry["sensitivity"] = self.slider.value() / 100
        self.changed.emit()
```

Add the missing imports at the top of `gui/tabs/settings.py` (within the
existing `PySide6.QtWidgets` import — augment if needed):

```python
from PySide6.QtWidgets import (
    ..., QCheckBox, QSlider, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFileDialog,
)
from PySide6.QtCore import QTimer
```

(Adjust to merge with the existing import lines; do not duplicate names.)

- [ ] **Step 2: Run the tests**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x -q`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add gui/tabs/settings.py
git commit -m "feat(settings-ui): MultiWakeWordRow widget"
```

---

## Task 11: Settings UI — MultiWakeWordCard with Add/Reload

**Files:**
- Modify: `gui/tabs/settings.py`

- [ ] **Step 1: Add `MultiWakeWordCard` class**

Insert after `MultiWakeWordRow`:

```python
class MultiWakeWordCard(SettingCard):
    """Multi-select card listing all known wake-word models.

    The wrapped settings key is `voice.wake_models` (a list of dicts).
    Edits write back the whole list; emit `models_changed` after.
    """

    models_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(FIF.MICROPHONE, "Wake Words",
                         "Models that wake Plia when spoken. Toggle and tune per model.",
                         parent)
        # Convert default horizontal layout into vertical container.
        self.hBoxLayout.removeWidget(self.titleLabel)
        self.hBoxLayout.removeWidget(self.contentLabel)
        self._rows_layout = QVBoxLayout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.addWidget(self.titleLabel)
        outer.addWidget(self.contentLabel)
        outer.addLayout(self._rows_layout)

        # Footer buttons.
        footer = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Model…", self)
        self.reload_btn = QPushButton("↻ Reload", self)
        footer.addWidget(self.add_btn)
        footer.addWidget(self.reload_btn)
        footer.addStretch(1)
        outer.addLayout(footer)
        self.add_btn.clicked.connect(self._on_add_model)
        self.reload_btn.clicked.connect(self._on_reload)

        self._rebuild_rows()

    # ── Helpers ──────────────────────────────────────────────────────────
    def _rebuild_rows(self):
        # Remove existing rows.
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        from core.wake_models import models_dir, reconcile_with_settings
        models = settings.get("voice.wake_models", [])
        models = reconcile_with_settings(models, models_dir())
        settings.set("voice.wake_models", models)

        for entry in models:
            row = MultiWakeWordRow(entry, self)
            row.changed.connect(self._on_any_row_changed)
            row.delete_requested.connect(self._on_delete)
            self._rows_layout.addWidget(row)

    def _on_any_row_changed(self):
        # Each row mutated its dict in-place; persist the whole list and signal.
        models = []
        for i in range(self._rows_layout.count()):
            row = self._rows_layout.itemAt(i).widget()
            if isinstance(row, MultiWakeWordRow):
                models.append(row._entry)
        settings.set("voice.wake_models", models)
        self.models_changed.emit()

    def _on_add_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Add wake-word model", "", "ONNX models (*.onnx)"
        )
        if not path:
            return
        from core.wake_models import models_dir
        import shutil
        dest_dir = models_dir() / "custom"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(path).name
        shutil.copy2(path, dest)
        self._rebuild_rows()
        self.models_changed.emit()

    def _on_reload(self):
        self._rebuild_rows()
        self.models_changed.emit()

    def _on_delete(self, model_id: str):
        from core.wake_models import models_dir
        models = settings.get("voice.wake_models", [])
        for i, m in enumerate(list(models)):
            if m["id"] == model_id:
                # Custom files get unlinked; built-in rows can also be deleted
                # only if broken (file missing already).
                full = models_dir() / m["path"]
                if not m.get("builtin", True) or m.get("broken"):
                    if full.exists():
                        try:
                            full.unlink()
                        except OSError:
                            pass
                    models.pop(i)
                break
        settings.set("voice.wake_models", models)
        self._rebuild_rows()
        self.models_changed.emit()
```

Add `from pathlib import Path` near the top if it's not already imported.

- [ ] **Step 2: Run the tests**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x -q`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add gui/tabs/settings.py
git commit -m "feat(settings-ui): MultiWakeWordCard with add/reload/delete"
```

---

## Task 12: Replace old wake-word cards in the Settings tab and wire to WakeDetector

**Files:**
- Modify: `gui/tabs/settings.py`
- Modify: `gui/settings.py`
- Modify: `core/voice_assistant.py`

- [ ] **Step 1: In `gui/tabs/settings.py`, delete the old wake-word card creation**

Find lines 798–820 (currently `wake_word_card` and `wake_sensitivity_card`)
and replace with:

```python
        # Wake words — multi-select with per-model sensitivity
        self.wake_words_card = MultiWakeWordCard(self.voice_group)
        self.voice_group.addSettingCard(self.wake_words_card)
        try:
            from core.voice_assistant import voice_assistant_instance
            if voice_assistant_instance and voice_assistant_instance.wake_detector:
                self.wake_words_card.models_changed.connect(
                    lambda: voice_assistant_instance.wake_detector.reload(
                        settings.get("voice.wake_models", [])
                    )
                )
        except Exception:
            pass  # voice assistant not yet wired — settings still work standalone
```

Also delete the leftover duplicate `self.voice_group.addSettingCard(self.wake_sensitivity_card)` (the file currently has the same `addSettingCard` line twice — line 820 duplicates line 819).

- [ ] **Step 2: Mirror the change in `gui/settings.py`**

Find lines 402–412 and replace with the same `MultiWakeWordCard`
instantiation. If `MultiWakeWordCard` lives in `gui/tabs/settings.py`,
import it: `from gui.tabs.settings import MultiWakeWordCard` (or move
the class into a shared module if your linter complains about cross-tab
imports).

- [ ] **Step 3: Expose `voice_assistant_instance`**

In `core/voice_assistant.py`, add at the bottom of the file:

```python
voice_assistant_instance: Optional[VoiceAssistant] = None
```

In the application bootstrap (search `VoiceAssistant()` in `gui/app.py`),
right after the instance is created, add:

```python
import core.voice_assistant as va_module
va_module.voice_assistant_instance = <the local variable name>
```

Search and adjust accordingly (the exact location depends on the bootstrap
code in `gui/app.py`).

- [ ] **Step 4: Run the tests + launch the GUI smoke check**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -x -q`
Expected: pass.

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -c "from gui.tabs.settings import SettingsTab; print('ok')"`
Expected: no import error.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/settings.py gui/settings.py core/voice_assistant.py gui/app.py
git commit -m "feat(settings-ui): swap old wake-word card for MultiWakeWordCard"
```

---

## Task 13: Training script `scripts/train_wake_word.py`

**Files:**
- Create: `scripts/train_wake_word.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Train a custom openWakeWord model from synthetic Piper TTS speech.

Pipeline:
  1. Generate N synthetic positive samples of the target word using Piper
     with multiple voices, speaking rates, and small pitch perturbations.
  2. Use openWakeWord's built-in negative dataset (downloaded on first run)
     for hard negatives, RIRs, and general speech.
  3. Train a binary classifier with openwakeword.train.train_model.
  4. Export to ONNX.

Usage:
  python scripts/train_wake_word.py --word "plia" \
      --output models/wake/bundled/plia.onnx \
      --variants 5000
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

VOICES = [
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-libritts-high",
    "en_GB-alba-medium",
    "en_GB-northern_english_male-medium",
]
RATES = [0.85, 1.0, 1.15, 1.3]
DEFAULT_VARIANTS = 5000


def synthesize_positives(word: str, out_dir: Path, variants: int) -> None:
    """Render `variants` WAV files of `word` to out_dir using Piper."""
    try:
        from piper.voice import PiperVoice
    except ImportError as exc:
        sys.exit(
            f"piper-tts is required for training: {exc}\n"
            f"Install with: pip install -r requirements-train.txt"
        )
    import random
    import wave

    out_dir.mkdir(parents=True, exist_ok=True)
    voices = {v: PiperVoice.load(v) for v in VOICES}
    print(f"Generating {variants} synthetic positives for '{word}'…")
    for i in range(variants):
        v = random.choice(VOICES)
        rate = random.choice(RATES)
        text = word
        wav_path = out_dir / f"{i:05d}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            voices[v].synthesize(text, wf, length_scale=rate)
        if i % 250 == 0:
            print(f"  {i}/{variants}")


def train(word: str, output_onnx: Path, variants: int) -> None:
    try:
        from openwakeword.train import collect_neg_features, train_model
    except ImportError as exc:
        sys.exit(
            f"openwakeword's training helpers are required: {exc}\n"
            f"Install with: pip install -r requirements-train.txt"
        )

    with tempfile.TemporaryDirectory(prefix=f"oww_{word}_") as workdir:
        work = Path(workdir)
        positives = work / "positives"
        synthesize_positives(word, positives, variants)

        print("Collecting / downloading negative features (this may take a few minutes the first time)…")
        negative_features = collect_neg_features()

        print("Training model…")
        output_onnx.parent.mkdir(parents=True, exist_ok=True)
        train_model(
            positive_audio_dir=str(positives),
            negative_features=negative_features,
            output_path=str(output_onnx),
            wake_word=word,
        )
        print(f"Wrote {output_onnx}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--word", required=True, help="Target wake phrase (e.g. 'plia')")
    parser.add_argument("--output", type=Path, required=True, help="Output .onnx path")
    parser.add_argument("--variants", type=int, default=DEFAULT_VARIANTS,
                        help=f"Number of synthetic positives (default {DEFAULT_VARIANTS})")
    args = parser.parse_args()

    if args.output.suffix != ".onnx":
        sys.exit("--output must end in .onnx")
    train(args.word, args.output, args.variants)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the script imports cleanly**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python scripts/train_wake_word.py --help`
Expected: prints the argparse help; no `ImportError` on argparse itself.

- [ ] **Step 3: Commit**

```bash
git add scripts/train_wake_word.py
git commit -m "feat(wake): scripts/train_wake_word.py — Piper → openWakeWord trainer"
```

---

## Task 14: Train the Plia model and commit the artifact

**Files:**
- Create: `models/wake/bundled/plia.onnx`

- [ ] **Step 1: Install the training extras**

Run: `/home/alfcon/miniconda3/envs/plia/bin/pip install -r requirements-train.txt`
Expected: installs piper-tts and friends; may take 1–2 min.

- [ ] **Step 2: Run training**

Run:
```bash
/home/alfcon/miniconda3/envs/plia/bin/python scripts/train_wake_word.py \
    --word "plia" \
    --output models/wake/bundled/plia.onnx \
    --variants 5000
```
Expected: ~25–40 minutes wall time on CPU. Final line: `Wrote models/wake/bundled/plia.onnx`.

- [ ] **Step 3: Smoke-test the trained model**

```bash
/home/alfcon/miniconda3/envs/plia/bin/python -c "
from openwakeword.model import Model
m = Model(wakeword_models=['models/wake/bundled/plia.onnx'], inference_framework='onnx')
print('loaded:', list(m.prediction_buffer.keys()))
"
```
Expected: prints `loaded: ['plia']`.

- [ ] **Step 4: Commit the artifact**

```bash
git add models/wake/bundled/plia.onnx
git commit -m "feat(wake): bundle trained 'plia' wake-word model"
```

If the resulting model fires too often or never, lower or raise the
default `sensitivity` for `plia` in `DEFAULT_SETTINGS` (e.g., 0.4 or 0.6)
and amend with another commit. Document the chosen value in the README.

---

## Task 15: First-launch migration toast + manual integration test

**Files:**
- Modify: `core/voice_assistant.py`
- Modify: `gui/app.py` (or wherever the main window is built)

- [ ] **Step 1: Show the migration toast once**

In `core/voice_assistant.py`'s `initialize`, after the wake detector is
created, add:

```python
            if app_settings.get("voice._migration_toast_pending"):
                self.error_occurred.emit(
                    "Wake-word engine changed to openWakeWord. "
                    "Defaults: 'Hey Jarvis' + 'Plia'. Adjust in Settings → Voice."
                )
                app_settings.set("voice._migration_toast_pending", False)
```

The existing `error_occurred` signal is already wired to an `InfoBar`
toast in the main window; reuse it. Find the existing connection in
`gui/app.py` to confirm — if the toast uses red styling for errors, add
a new `info_occurred` signal instead and wire a green-styled toast.

- [ ] **Step 2: Manual smoke test — launch Plia**

Run the app:
```bash
/home/alfcon/miniconda3/envs/plia/bin/python plia.py
```

Verify:
1. Console prints "[VoiceAssistant] ✓ Wake detector ready (2 models loaded)".
2. Console prints "[VoiceAssistant] Voice assistant started. Listening for: hey_jarvis, plia".
3. Say "Hey Jarvis" — wake fires, transcription starts. Console prints
   "[Wake] model 'hey_jarvis' fired" then "[STT] 👂 Wake word detected".
4. Say "Plia" — same as above, with model id "plia".
5. Say something not a wake word — no trigger.
6. Open Settings → Voice & Audio:
   - The "Wake Word" combo is gone.
   - "Wake Words" card lists 6 rows with checkboxes + sliders.
   - Toggle "Alexa" on — console prints "[Wake] model 'alexa' loaded" (or
     similar reload message). Say "Alexa" — wakes Plia.
   - Click "+ Add Model…" — file dialog opens. Cancel.
7. Quit and re-launch — settings persist.

- [ ] **Step 3: Manual smoke test — custom model upload**

1. Find any third-party `.onnx` model online or copy `plia.onnx` to a
   different name (`/tmp/test_custom.onnx`).
2. In Settings → Voice & Audio → "+ Add Model…", select that file.
3. Verify a new row appears with the filename stem as the display name.
4. Verify the file now exists at `models/wake/custom/test_custom.onnx`.
5. Enable it, set sensitivity, restart app, confirm it loads.
6. Click the ✕ button on the custom row — file deleted, row removed.

- [ ] **Step 4: Run the full test suite one last time**

Run: `/home/alfcon/miniconda3/envs/plia/bin/python -m pytest tests/ -q`
Expected: all tests pass.

- [ ] **Step 5: Commit any final adjustments**

```bash
git add -A
git commit -m "chore(wake): migration toast + final wiring"
```

---

## Self-review checklist (for the reviewer)

- [ ] Spec section "Architecture" covered by tasks 5, 6, 7, 8.
- [ ] Spec section "Data model" covered by task 2.
- [ ] Spec section "Migration" covered by task 2 (`test_jarvis_migrates_*`).
- [ ] Spec section "WakeDetector behavior" covered by tasks 5 & 6 (load, threshold, cooldown, pause-while-listening, corrupt-model skip).
- [ ] Spec section "Settings UI" covered by tasks 10, 11, 12.
- [ ] Spec section "Custom upload" covered by task 11 (`_on_add_model`).
- [ ] Spec section "Training pipeline" covered by tasks 13 and 14.
- [ ] Spec section "Dependencies" covered by task 1.
- [ ] Spec section "Open risks — download_models()" covered by Task 4 Step 4 verification.
- [ ] No placeholders, all code blocks complete, all file paths exact.
