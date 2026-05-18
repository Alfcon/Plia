# In-App Wake-Word Trainer — Design Spec

**Status:** approved 2026-05-18
**Author:** Plia
**Related:** [`2026-05-17-openwakeword-replacement-design.md`](2026-05-17-openwakeword-replacement-design.md)

## 1. Purpose

Make wake-word training a first-class capability inside Plia. Today Plia
ships five bundled openWakeWord models and supports `.onnx` upload via
**Settings → Voice & Audio → + Add Model…**, but custom training requires
the user to leave the app, open openWakeWord's official Colab notebook,
download the resulting `.onnx`, and drop it in by hand. This spec replaces
that out-of-app round-trip with a local trainer that any of Plia's three
extension surfaces — Settings UI, plugin tool, agent — can invoke through a
single engine.

## 2. Goals & non-goals

**Goals**

- One Python entry point (`core.wake_trainer.train_wake_word`) usable from
  any Plia surface or test.
- Three thin frontends sharing that engine: Settings dialog, plugin tool,
  generated agent.
- Local-only compute (CPU or available GPU); training works offline once
  openWakeWord's negative-feature pack is cached.
- Cancellable, progress-reporting, with consistent error vocabulary across
  frontends.
- Output drops into `models/wake/custom/<word>.onnx`; existing
  `core/wake_models.py` discovery picks it up on the next reconcile.

**Non-goals**

- Cloud / Hugging Face Jobs training (chose local in brainstorming).
- Recorded-voice positives — synthetic-only via Piper TTS for now. Adding
  microphone capture is a separate, additive feature.
- Modifying bundled models in `models/wake/bundled/`. The trainer never
  writes there; only `custom/`.
- Retraining or fine-tuning existing models. Each run trains a fresh model
  from scratch — this matches the upstream notebook.

## 3. Architecture overview

```
                            ┌──────────────────────────────┐
                            │   core/wake_trainer.py       │
                            │   (the one engine)           │
                            │                              │
                            │   train_wake_word(           │
                            │     word, *, variants,       │
                            │     voices, on_progress,     │
                            │     should_cancel,           │
                            │   ) -> Path                  │
                            │                              │
   ┌─── frontends ────┐     │   Stages:                    │
   │                  │     │     1. synth positives (Piper)│
   │  Settings UI ─►──┼──►──┤     2. fetch neg features    │
   │                  │     │        (cached in ~/.plia/   │
   │  Plugin tool ──►─┼──►──┤        wake_trainer/         │
   │                  │     │        neg_features)         │
   │  Plia agent ───►─┼──►──┤     3. train PyTorch loop    │
   │                  │     │     4. export ONNX           │
   └──────────────────┘     │     5. drop in models/wake/  │
                            │        custom/<word>.onnx    │
                            └──────────────────────────────┘
```

Single core module, three thin frontends. Each frontend supplies its own
progress sink (Qt signal / chat log / agent stdout) via the `on_progress`
callback; the engine has no UI knowledge. `should_cancel` is a thunk the
engine polls between stages and between training epochs so any frontend
can stop a run.

## 4. Core engine — `core/wake_trainer.py`

```python
# All heavy deps lazy-imported inside functions so importing this module is free.
from pathlib import Path
from typing import Callable

WAKE_TRAINER_DIR = Path.home() / ".plia" / "wake_trainer"
NEG_FEATURES_DIR = WAKE_TRAINER_DIR / "neg_features"   # cached across runs

# Output location. Defers to core.wake_models.models_dir() so the trainer
# writes to the same directory the discovery scanner reads, regardless of
# the process's current working directory.
def _default_output_dir() -> Path:
    from core.wake_models import models_dir
    return models_dir() / "custom"

ProgressFn = Callable[[float, str], None]              # (pct 0-100, message)
CancelFn   = Callable[[], bool]                        # returns True to stop

DEFAULT_VOICES = [
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-libritts-high",
    "en_GB-alba-medium",
    "en_GB-northern_english_male-medium",
]


def ensure_negative_features(on_progress: ProgressFn) -> Path:
    """Download + extract openWakeWord's neg-feature pack on first use.
    Cached in NEG_FEATURES_DIR; ~hundreds of MB. No-op on subsequent calls."""


def synthesize_positives(
    word: str, voices: list[str], variants: int,
    out_dir: Path, on_progress: ProgressFn, should_cancel: CancelFn,
) -> Path:
    """Render <variants> Piper WAVs under out_dir. Returns out_dir."""


def train_wake_word(
    word: str, *,
    variants: int = 5000,
    voices: list[str] | None = None,
    output_dir: Path | None = None,    # defaults to _default_output_dir()
    on_progress: ProgressFn = lambda pct, msg: None,
    should_cancel: CancelFn = lambda: False,
    epochs: int = 100,
) -> Path:
    """End-to-end: synth → neg features → train → ONNX export.

    Returns the path to <output_dir>/<slug>.onnx, where slug = re.sub(
    r'[^a-z0-9_]+', '_', word.lower()).strip('_'). Raises ValueError-style
    WakeTrainerError if the slug ends up empty.

    Raises TrainCancelled if should_cancel() returns True between stages.
    Raises WakeTrainerError on anything else (validation, deps, IO, train).
    """


class TrainCancelled(Exception): ...
class WakeTrainerError(Exception): ...
```

**Internals** (private):

- `_train_loop(...)` — PyTorch loop vendored from openWakeWord's
  `notebooks/automatic_model_training.ipynb`, ~300–500 lines, since the
  upstream package doesn't export a stable training function.
- `_export_onnx(model, path)` — `torch.onnx.export` with the opset
  openwakeword's runtime expects (pinned during implementation to match
  what `openwakeword.Model` consumes today).
- `_verify_onnx_loads(path)` — round-trip the freshly written file through
  `openwakeword.Model(wakeword_models=[path])`; delete on failure.

**Why this surface**

- Pure-Python entry points, no Qt or Plia agent imports — engine fully
  isolated and unit-testable.
- `on_progress` carries fine-grained stage messages (`"synth: 1240/5000"`,
  `"train: epoch 7/100, loss=0.12"`); no shared global state.
- `should_cancel` polled *between stages* and *between epochs* (cheap;
  never mid-batch) so a run stops within seconds without trashing model
  state.
- Default `variants=5000` and `epochs=100` match the upstream notebook's
  recommendations.

## 5. Frontends

### 5a. Settings UI — `TrainWakeWordDialog`

A new `+ Train Model…` button next to the existing `+ Add Model…` button in
`MultiWakeWordCard` (`gui/tabs/settings.py`). Opens a modal:

```
┌─ Train new wake word ───────────────────────────────┐
│  Word:        [ plia            ]                   │
│  Variants:    [────●──────] 5000                    │
│  Voices:      [☑] en_US-lessac-medium               │
│               [☑] en_US-amy-medium     …            │
│                                                     │
│  Stage:       Synthesising positives                │
│  ┌────────────────────────────────┐                 │
│  │██████████░░░░░░░░░░░░░░░░░░░░░░│ 32%             │
│  └────────────────────────────────┘                 │
│  ETA: ~22 min                                       │
│                                                     │
│              [ Cancel ]   [ Train ]                 │
└─────────────────────────────────────────────────────┘
```

A `QThread` runs `train_wake_word(...)` with two adapters:

- `on_progress` → `Signal(float, str)` → dialog progress bar + label.
- `should_cancel` → a getter that reads the dialog's cancel-clicked flag.

On success, the dialog calls `MultiWakeWordCard._rebuild_rows()` so the new
entry appears immediately, then closes with a success toast.

### 5b. Plugin tool — `plugins/wake_trainer.py`

A bundled plugin (committed to the repo and copied into
`~/.plia_ai/plugins/` on install) exposing:

```python
def tool_train_wake_word(params: dict) -> dict:
    """Train an openWakeWord model. Params: {word, variants?, voices?}.
    Long-running — emits progress to Plia's chat log via plugin_log().
    Returns {success, message, data: {path}}."""
```

It calls the same `core.wake_trainer.train_wake_word(...)` engine. The
`on_progress` callback writes through `core.plugins.plugin_log(...)` which
mirrors to the chat log. Cancellation comes from the existing stop-running-
tool mechanism.

### 5c. Plia agent — built via AgentBuilder

`core/agent_builder.py` gains a small `_WAKE_TRAINER_TEMPLATE` alongside
the existing `_SEARCH_DOWNLOAD_TEMPLATE`. When the user says "build me a
wake-word trainer" (or similar), `detect_build_intent` matches and the
builder writes a self-contained agent in `~/.plia_ai/agents/
wake_word_trainer.py` that imports and calls `tool_train_wake_word(...)`.
It registers in `custom_agents.json` like any other agent — Run / Stop /
Schedule all work, output streams via the standard `agent_runtime`
channels.

### Cross-cutting

- All three frontends call exactly the same engine. Bug fixes happen once.
- Only the Settings dialog blocks a UI; plugin and agent paths are
  inherently async via Plia's existing infrastructure.
- All three accept the same `word`, `variants`, `voices` parameters — same
  vocabulary across the app.

## 6. Data flow

```
                              user
                                │
                                ▼
        ┌───────────────────────┬────────────────────────────┐
        │                       │                            │
   Settings UI            Chat → tool_loop              Active Agents
   + Train Model…          dispatches to                   tab → Run
        │                  tool_train_wake_word               │
        │                       │                            │
        └──────────┬────────────┴────────────┬───────────────┘
                   ▼                         ▼
          train_wake_word(word, variants, voices,
                          on_progress, should_cancel)
                   │
                   ▼
   ┌──────────────────────────────────────────────────────────┐
   │ 1. Validate inputs                                       │
   │      - word: non-empty, ascii/space, ≤ 32 chars          │
   │      - variants: 500-20000                               │
   │      - voices: subset of DEFAULT_VOICES + Piper-installed│
   │      Raises WakeTrainerError on violation                │
   │                                                          │
   │ 2. ensure_negative_features(on_progress)                 │
   │      ~/.plia/wake_trainer/neg_features/                  │
   │      First call:  download + verify checksum + unpack    │
   │                   on_progress 0 → 10                     │
   │      Cached:      no-op                                  │
   │                                                          │
   │ 3. synthesize_positives(word, voices, variants, …)       │
   │      ~/.plia/wake_trainer/tmp_<word>_<ts>/positives/     │
   │      Per-WAV:  pick voice, random rate ∈ {0.85,1.0,1.15, │
   │                1.3}, Piper synth → 16 kHz mono WAV       │
   │      on_progress 10 → 30, message "synth: i/variants"    │
   │                                                          │
   │ 4. _train_loop(positives, neg_features, epochs)          │
   │      PyTorch loop vendored from oWW notebook             │
   │      on_progress 30 → 95, message "epoch e/E, loss=…"    │
   │      Cancellation: should_cancel() checked between epochs│
   │                                                          │
   │ 5. _export_onnx(model, output_dir / f"{slug}.onnx")      │
   │      torch.onnx.export, opset matching oWW runtime       │
   │      Verify load via openwakeword.Model(...)             │
   │      on_progress 95 → 100, message "exported"            │
   │                                                          │
   │ 6. Cleanup tmp dir (positives WAVs); keep neg_features   │
   └──────────────────────────────────────────────────────────┘
                   │
                   ▼
          returns Path to models/wake/custom/<word>.onnx
                   │
                   ▼
   Settings UI:       rebuild wake-words rows → new entry visible
   Plugin path:       return {success, data:{path}} to caller
   Agent path:        emit to agent_runtime log + reload signal
                   │
                   ▼
      Wake detector (already running): the next reconcile picks
      up the new file via models_dir() scan; user enables it and
      sets sensitivity in Settings.
```

**Data-flow notes**

- **No cross-process IPC.** Same Python process throughout. `on_progress`
  is a normal Python callable; each frontend wraps it into its own
  messaging primitive (Qt signal / log line / agent event).
- **Persistent vs ephemeral state.** Negative-feature pack is *persistent
  and cached* (`~/.plia/wake_trainer/neg_features/`) so the multi-hundred-
  MB download happens once per user. Synthesised positives are *ephemeral*
  — deleted on success or on cancel; they're tens of MB and trivially
  regeneratable.
- **The new `.onnx` lands in `custom/`, never `bundled/`.** `bundled/` is
  git-tracked and reserved for repo defaults; `custom/` is user-generated.
  The existing `core/wake_models.py` discovery already scans both. Settings
  UI triggers an immediate reconcile; plugin/agent paths leave it for the
  next Settings open or manual ↻ Reload.

## 7. Error handling

Five failure surfaces, each with explicit handling:

| Surface | Failure mode | Handling |
|---|---|---|
| **Dep imports** | `speechbrain` / `audiomentations` / etc. missing or version-mismatched | `train_wake_word()` lazy-imports each at use site. Catch `ImportError`, re-raise as `WakeTrainerError("missing dep: pip install …")` with a copy-paste install command. Settings dialog renders this in a red alert area; plugin returns `{success: False, message: …}`; agent writes to stdout. |
| **Negative-feature download** | Network down, checksum mismatch, disk full | `ensure_negative_features` retries 3× on transient network errors with exponential backoff, then raises `WakeTrainerError`. Partial downloads cleaned up in `finally`. Checksum verified before unpack. |
| **Piper synth** | Voice not installed, audio backend missing, disk full mid-batch | Wrap per-voice load in try/except; if a voice fails, log + skip and continue with the remaining voices. If *all* voices fail, raise `WakeTrainerError("no usable Piper voice")`. Per-WAV errors increment a counter; abort if > 10% of variants fail. |
| **Training loop** | CUDA OOM, NaN loss, hardware fault | OOM → automatic fallback to CPU + warn via `on_progress`. NaN loss → abort with `WakeTrainerError("training diverged at epoch N")`. Wrap each epoch in try; on unrecoverable error, raise with the epoch index so the user knows where it died. |
| **ONNX export / verify** | torch→ONNX op missing, openwakeword refuses to load the result | Catch `RuntimeError` during export → `WakeTrainerError("export failed: …")`. After export, smoke-test by loading the file via `openwakeword.Model(wakeword_models=[path])`. If load fails, delete the `.onnx` and raise. |

**Cancellation** raises `TrainCancelled` from the engine. Frontends treat
this distinctly from `WakeTrainerError`:

- Settings dialog: silent close, "Training cancelled" toast (info, not
  warning).
- Plugin: `{success: False, message: "cancelled", data: None}` — not an
  error.
- Agent: logs "Cancelled by user", returns clean.

**Partial files always get cleaned up.** The engine's outer `try/finally`
deletes the temporary positives directory and any half-written `.onnx` on
any exception, so a failed run never poisons `models/wake/custom/` or
leaves orphaned tmp dirs.

## 8. Dependencies

New entries in `requirements.txt` (≈150–300 MB on top of the existing
`torch`):

- `speechbrain` — used by openWakeWord's data preprocessing
- `audiomentations` — augmentation
- `torch-audiomentations` — GPU-friendly augmentation
- `pronouncing` — adversarial-text generation
- `acoustics` — audio analysis
- `mutagen` — audio metadata
- `torchinfo`, `torchmetrics` — already pulled in by openWakeWord's
  `train.py`; pin explicitly

All of these are **lazy-imported inside `core/wake_trainer.py` functions**.
Importing `core.wake_trainer` itself stays free; the cost is paid only the
first time `train_wake_word()` is called. Plia startup is unaffected.

`requirements-train.txt` (currently a stub) is deleted — training is now
part of the main install.

## 9. Testing

Mix of unit (cheap, mocked), integration (medium, real Piper but tiny
variant count), and manual smoke.

**Unit tests** — `tests/test_wake_trainer.py`, ~10 tests, all under 1s:

- `test_validates_word_rejects_empty()` — empty word → `WakeTrainerError`
- `test_validates_word_rejects_oversize()` — 33-char word → raises
- `test_validates_variants_range()` — `variants=100`, `50000` → raise
- `test_validates_voices_subset()` — unknown voice → raises
- `test_ensure_negative_features_is_idempotent()` — second call is a no-op
  when cache present (tmp_path + monkeypatched `NEG_FEATURES_DIR`)
- `test_progress_callback_invoked_with_pct_and_message()` — fake engine
  stages, assert callback gets `(float 0-100, str)` tuples
- `test_should_cancel_raises_train_cancelled_between_stages()` —
  `should_cancel` returns True after stage 1; assert `TrainCancelled`
  raised, tmp dir cleaned
- `test_failed_export_deletes_onnx()` — patch `torch.onnx.export` to raise;
  assert no `.onnx` left in `custom/`
- `test_missing_dep_raises_with_install_hint()` — patch `import
  speechbrain` to fail; assert message contains `pip install`
- `test_smoke_load_rejects_corrupt_onnx()` — write 16 bytes of garbage to a
  fake `.onnx`, assert engine rejects + deletes

**Integration test** — `tests/test_wake_trainer_integration.py`, marked
`@pytest.mark.slow`, opt-in:

- `test_train_tiny_model_end_to_end()` — `variants=50, epochs=2`, no
  neg-feature download (mock to a tiny precomputed file). Asserts a
  loadable `.onnx` lands in a tmp `custom/` dir. ~30 s; gated by `RUN_SLOW=1`
  env var so CI and normal `pytest` skip it.

**Frontend tests**

- Settings dialog: extend `tests/test_settings_layout.py` with a test that
  the new `+ Train Model…` button exists, opens the dialog, the dialog has
  `Cancel` / `Train` buttons. Mocks the engine — never invokes real
  training.
- Plugin: `tests/test_plugins.py` (extend if it exists, else new) — assert
  `tool_train_wake_word` is registered after plugin load and rejects
  malformed params before reaching the engine.
- Agent: `tests/test_agent_builder.py` (extend) — assert the wake-trainer
  template renders to syntactically-valid Python for at least one
  happy-path call.

**Manual smoke (post-merge)**

- Open Settings → Voice & Audio → `+ Train Model…` → train word "plia"
  with `variants=500` (~5 min). Verify `models/wake/custom/plia.onnx`
  exists, loads in WakeDetector after Reload, and triggers on the spoken
  word.
- Same flow from chat: "Plia, train a wake word for 'plia'".
- Same flow via Active Agents tab.

## 10. Open questions

- **Negative-feature pack hosting.** openWakeWord's neg-feature archive
  lives on a non-trivial URL; the exact hosting and checksum need to be
  pinned during implementation. If upstream moves it, we'll need to mirror.
- **GPU detection inside the trainer.** Should defer to
  `core/gpu_info.read_gpu()` (already cross-vendor for NVIDIA/AMD) rather
  than re-inventing CUDA-only probing.
- **Voice picker UI.** The dialog mockup shows a multi-select voice list.
  The actual set of installed Piper voices on a given machine is dynamic;
  the dialog should discover them via Piper's voice cache rather than hard-
  coding `DEFAULT_VOICES`.
