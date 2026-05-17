# Wake-word engine replacement: Porcupine → openWakeWord

**Status:** design approved, ready for implementation plan
**Date:** 2026-05-17
**Owner:** Alfio

## Motivation

Plia's wake-word detection uses Picovoice Porcupine via RealtimeSTT. Porcupine
is accurate and efficient but closed-source: keywords are fixed to a built-in
list (`jarvis`, `computer`, `bumblebee`, …) and custom words require a paid
Picovoice Console workflow producing `.ppn` files. The Settings dropdown
("wake-word picker") is also non-functional — changing the value writes to
`voice.wake_word` but does not restart the recorder, so the running engine
keeps the old keyword.

We want:

1. A wake word that matches the project name — "Plia".
2. The ability to add and remove custom wake words at will.
3. A working picker — changing wake-word settings takes effect without an app
   restart.

## Decision

Fully replace Porcupine with **openWakeWord** (Apache-2.0, ONNX, runs locally,
no API key, supports custom trainable models). Run openWakeWord ourselves
rather than through RealtimeSTT's `wakeword_backend="oww"` so per-model
sensitivity thresholds work as intended. RealtimeSTT is retained for VAD and
transcription only.

Tradeoffs accepted vs Porcupine: ~5% extra CPU on one core; somewhat higher
false-positive rate in noisy environments (mitigated by per-model sensitivity
tuning and the cooldown). Gained: full ownership of the wake-word list,
trainable custom models ("Plia"), no third-party account.

## Scope

### In scope

- New `core/wake_detector.py` owning the microphone and running openWakeWord.
- Strip Porcupine from `core/stt.py`; RealtimeSTT runs with
  `use_microphone=False` and is fed audio via `feed_audio()`.
- Multi-select wake-word UI in Settings with per-model sensitivity sliders.
- Bundled `.onnx` models: `hey_jarvis`, `alexa`, `hey_mycroft`, `ok_nabu`,
  `hey_rhasspy`, `plia`.
- Train `models/wake/bundled/plia.onnx` and commit it.
- Custom model upload: file picker in Settings and folder-drop in
  `models/wake/custom/`, both auto-discovered.
- `scripts/train_wake_word.py` reproducible training pipeline (Piper synthetic
  speech → openWakeWord training → ONNX export).
- `models/wake/README.md` documenting how to train and add custom models.
- One-time migration: existing `voice.wake_word="jarvis"` →
  `["hey_jarvis", "plia"]` enabled; other Porcupine words → fallback +
  notification toast.

### Out of scope (deferred)

- Voice-activity-only mode (no wake word).
- Hot-switching enabled words by voice command.
- Cross-platform installer changes (existing build already ships `models/`).
- Per-model cooldown (single global 1.5s cooldown for V1).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  PyAudio mic stream (16kHz / 16-bit / mono / 1280-sample)    │
└────────────────────────────┬─────────────────────────────────┘
                             │
                             ▼
            ┌────────────────────────────────┐
            │   core/wake_detector.py        │
            │   WakeDetector (QThread)       │
            │   - owns the mic stream        │
            │   - openwakeword.Model         │
            │   - per-model thresholds       │
            │   - emits Signal(model_id)     │
            └────┬────────────────────┬──────┘
                 │                    │
       wake fired│           every    │ audio chunk
                 ▼                    ▼
       recorder.start()      recorder.feed_audio(chunk)
            ┌────────────────────────────────┐
            │  core/stt.py                   │
            │  AudioToTextRecorder           │
            │  use_microphone=False          │
            │  no wakeword_backend           │
            │  (transcription only)          │
            └────────────────────────────────┘
```

### Files added

- `core/wake_detector.py` — `WakeDetector` QThread; mic ownership, openWakeWord
  inference, per-model thresholds, Qt signals.
- `models/wake/bundled/` — committed `.onnx` files including `plia.onnx`.
- `models/wake/custom/` — user uploads; gitignored except `.gitkeep`.
- `models/wake/README.md` — training and add-custom-model docs.
- `scripts/train_wake_word.py` — Piper → openWakeWord training pipeline.
- `tests/test_wake_detector.py` — detector behavior tests.
- `tests/test_settings_migration.py` — migration tests.
- `tests/test_model_discovery.py` — model discovery tests.

### Files modified

- `core/stt.py` — remove `SUPPORTED_WAKE_WORDS`, `WAKE_WORDS`,
  `_get_wake_word()`; remove `wakeword_backend`/`wake_words` from recorder
  init; set `use_microphone=False`; ensure `recorder.feed_audio(chunk)` is
  callable from the WakeDetector thread.
- `core/voice_assistant.py` — instantiate `WakeDetector`, wire
  `wake_word_detected` signal to the existing `_on_wake_word` callback.
- `core/settings_store.py` — new `voice.wake_models` schema (list of dicts);
  migration from `voice.wake_word` + `voice.sensitivity_pct`; delete the old
  keys after migration.
- `gui/tabs/settings.py` — replace `wake_word_card` (ComboBoxCard) and
  `wake_sensitivity_card` (SliderCard) with `MultiWakeWordCard`; add
  `MultiWakeWordRow` widget; wire `models_changed` signal to
  `WakeDetector.reload()`.
- `config.py` — remove `USE_PORCUPINE_WAKE_WORD`, `WAKE_WORD`,
  `WAKE_WORD_SENSITIVITY`, `WAKE_WORD_CONFIRMATION_COUNT`,
  `WAKE_WORD_DETECTION_METHOD`.
- `requirements.txt` — add `openwakeword>=0.6.0`, `onnxruntime>=1.16.0`;
  remove `pvporcupine`.

## Data model

### Settings key: `voice.wake_models`

```json
"voice.wake_models": [
  {"id": "hey_jarvis",  "display": "Hey Jarvis",  "path": "bundled/hey_jarvis.onnx",  "enabled": true,  "sensitivity": 0.5, "builtin": true},
  {"id": "alexa",       "display": "Alexa",       "path": "bundled/alexa.onnx",       "enabled": false, "sensitivity": 0.5, "builtin": true},
  {"id": "hey_mycroft", "display": "Hey Mycroft", "path": "bundled/hey_mycroft.onnx", "enabled": false, "sensitivity": 0.5, "builtin": true},
  {"id": "ok_nabu",     "display": "OK Nabu",     "path": "bundled/ok_nabu.onnx",     "enabled": false, "sensitivity": 0.5, "builtin": true},
  {"id": "hey_rhasspy", "display": "Hey Rhasspy", "path": "bundled/hey_rhasspy.onnx", "enabled": false, "sensitivity": 0.5, "builtin": true},
  {"id": "plia",        "display": "Plia",        "path": "bundled/plia.onnx",        "enabled": true,  "sensitivity": 0.5, "builtin": true}
]
```

- `path` is relative to `models/wake/`.
- `sensitivity` is the openWakeWord confidence threshold (0.0–1.0). A score
  `>= sensitivity` triggers a wake event. Default `0.5`.
- `builtin: true` rows have the delete button hidden in the UI; custom rows
  (`builtin: false`) can be deleted.
- The list is the source of truth for which models are loaded and at what
  threshold. Discovery is a one-way reconciliation that adds new files found
  on disk but never removes settings rows.

### Deprecated keys (removed after migration)

- `voice.wake_word` (str)
- `voice.sensitivity_pct` (int 0–100)

### Migration

Runs once on first load if `voice.wake_models` is missing:

```
if voice.wake_word == "jarvis":  # the previous default
    seed with hey_jarvis + plia enabled, others disabled
else:
    seed with hey_jarvis + plia enabled
    queue a one-time toast: "Wake-word engine changed —
        your previous choice '<old word>' is no longer available.
        Defaulting to 'Hey Jarvis' + 'Plia'. Adjust in Settings."
delete voice.wake_word, voice.sensitivity_pct
```

The migration is idempotent: re-running it on an already-migrated config is a
no-op.

### Model discovery

On startup and on user "Reload":

- Scan `models/wake/bundled/*.onnx` and `models/wake/custom/*.onnx`.
- For each file not yet in `voice.wake_models`: append a row with
  `enabled: false`, `sensitivity: 0.5`, `builtin` set by directory, `display`
  defaulting to the filename stem.
- For each settings row whose file is missing on disk: do NOT remove it; mark
  it broken in the UI (warning icon, controls disabled, delete button shown
  for cleanup).
- Custom model with the same `id` as a built-in: discovery suffixes with
  `_1`, `_2`, … to disambiguate.

## WakeDetector behavior

### Lifecycle

```
VoiceAssistant.start()
   └── WakeDetector.start()                  # one-time on app launch
         ├── _open_mic_stream()              # PyAudio 16kHz / 16-bit / mono
         ├── _load_models()                  # reads enabled rows from settings
         │       └── openwakeword.Model(wakeword_models=[paths])
         └── _audio_loop()  (QThread.run)
               while running:
                 chunk = stream.read(1280, exception_on_overflow=False)
                 if recorder.is_listening:    # transcribing — feed audio only
                    recorder.feed_audio(chunk)
                    continue
                 scores = oww.predict(chunk)  # {model_id: float}
                 for model_id, score in scores.items():
                    if score >= self.thresholds[model_id]:
                       if cooldown_ok():
                          wake_word_detected.emit(model_id)
                          enter_cooldown(1.5s)
                          break               # don't fire multiple models on one utterance
```

### Key behaviors

- **No double-feed:** While RealtimeSTT is actively transcribing post-wake,
  audio is fed to the recorder and openWakeWord prediction is skipped. This
  prevents the detector firing on the user's own command speech.
- **Cooldown (1.5s):** Suppresses additional wake events for 1.5s after one
  fires. Single global cooldown — per-model cooldown is deferred.
- **Reload (no app restart):** `WakeDetector.reload()` re-reads settings,
  rebuilds the `openwakeword.Model` instance with the new set of paths and
  thresholds, and continues with the existing mic stream. Called when the
  user toggles any checkbox, moves any slider (debounced 300 ms), clicks
  "Reload", or adds/removes a model.
- **Empty enabled set:** Audio loop continues running but skips prediction.
  Settings UI shows "⚠ No wake words enabled — voice activation disabled."

### Signals

- `wake_word_detected = Signal(str)` — payload: the `model_id` that fired
  (e.g., `"plia"`). Consumed by `voice_assistant.py`'s existing
  `_on_wake_word` callback (and optionally logged for telemetry).
- `error = Signal(str)` — user-readable error for toast display.

### Error handling

- **Mic open fails** → emit `error` signal; thread exits cleanly; main window
  shows a toast and disables voice features.
- **One model's `.onnx` is corrupt** → openwakeword load fails for that
  model only. Implementation loads models one at a time and accumulates the
  working set. The broken model is flagged in the UI; other models keep
  working. Warning toast shown.
- **All models fail to load** → detector stays alive but inert (no
  prediction). Settings UI explains the situation.

## Settings UI

### `MultiWakeWordCard` layout

```
┌─ Voice & Audio ────────────────────────────────────────────────┐
│                                                                │
│  Wake Words                                                    │
│  Models that wake Plia when spoken. Toggle and tune per model. │
│                                                                │
│  ☑ Hey Jarvis        [sensitivity ━━━●━━━] 0.50                │
│  ☑ Plia              [sensitivity ━━●━━━━] 0.45                │
│  ☐ Alexa             [sensitivity ━━━●━━━] 0.50                │
│  ☐ Hey Mycroft       [sensitivity ━━━●━━━] 0.50                │
│  ☐ OK Nabu           [sensitivity ━━━●━━━] 0.50                │
│  ☐ Hey Rhasspy       [sensitivity ━━━●━━━] 0.50                │
│  ☐ Custom Wake       [sensitivity ━━━●━━━] 0.50      [✕]       │
│  ⚠ Missing Model     (file not found)                          │
│                                                                │
│  [ + Add Model... ]   [ ↻ Reload ]                             │
└────────────────────────────────────────────────────────────────┘
```

### Component sketch (in `gui/tabs/settings.py`)

```python
class MultiWakeWordCard(SettingCard):
    models_changed = Signal()           # → WakeDetector.reload()

    def __init__(self, parent):
        # Vertical layout (overrides default SettingCard hBoxLayout)
        # One MultiWakeWordRow per entry in voice.wake_models
        # Two footer buttons: "Add Model..." + "Reload"

    def _on_add_model(self):
        # QFileDialog filter="*.onnx" → copy to models/wake/custom/
        # Prompt for display name (default: filename stem)
        # Append to voice.wake_models with enabled=false
        # Refresh rows; emit models_changed

    def _on_reload(self):
        # discover_wake_models() → reconcile with voice.wake_models
        # Refresh rows; emit models_changed

class MultiWakeWordRow(QWidget):
    # Per-row: QCheckBox | label | QSlider | (optional ✕ for custom)
    # Slider 0–100 ↔ sensitivity 0.0–1.0; debounced 300ms before save
    # Edits write to voice.wake_models list at this row's index
```

### Wiring

- `models_changed` connects to `voice_assistant.wake_detector.reload()`.
- The old `wake_word_card` (ComboBoxCard) and `wake_sensitivity_card`
  (SliderCard) are removed entirely from `gui/tabs/settings.py` (and the
  parallel duplicate in `gui/settings.py`, lines 402–412).
- Migration runs in `core/settings_store.load()` before any UI reads the
  list, so the UI never observes the deprecated keys.

### UI edge cases

- **Missing file row:** warning icon, controls disabled, delete button shown.
- **All checkboxes off:** footer text "⚠ No wake words enabled — voice
  activation disabled."
- **Custom model with same `id` as a built-in:** discovery suffixes with
  `_1`, `_2`, ….

## Training pipeline

### `scripts/train_wake_word.py`

```
Usage:
  python scripts/train_wake_word.py --word "plia" --variants 5000 \
      --output models/wake/bundled/plia.onnx

Pipeline (single script, ~200 LOC):
  1. Generate positive samples via Piper (already used by Plia for TTS).
       - N=5000 utterances of the target word
       - Vary: 5 voices × multiple speeds/pitches × added silence
       - Output: WAV files at 16kHz mono → temp dir
  2. Download/cache openwakeword's negative dataset (RIRs + noise + speech)
       using openwakeword.train.collect_neg_features().
  3. Train via openwakeword.train.train_model(
        positive_audio_dir, negative_features, output_path, epochs=N).
  4. Export ONNX → models/wake/bundled/<word>.onnx.
  5. Print evaluation metrics (precision/recall on held-out set).
```

The same script produces `plia.onnx` for this release and is reusable for any
other custom word.

### `models/wake/README.md`

Short doc covering:

- Where models come from: `bundled/` (committed) vs `custom/` (user).
- Training your own: `python scripts/train_wake_word.py --word "<word>"`.
- Third-party `.onnx` sources (openWakeWord community registry link).
- Adding a custom model via Settings ("Add Model…") or by dropping a `.onnx`
  into `models/wake/custom/` and clicking "Reload".

## Dependencies

### Runtime (`requirements.txt`)

- Add: `openwakeword>=0.6.0`
- Add: `onnxruntime>=1.16.0`
- Remove: `pvporcupine>=1.9.0,<2`

### Training (`requirements-train.txt`, new)

Only needed by `scripts/train_wake_word.py`, not by the running app:

- `piper-tts` (or reuse existing Piper install)
- `torch` (already present)
- openWakeWord's training helpers ship in the main package.

## Testing

| Test file | Test | Covers |
|---|---|---|
| `test_wake_detector.py` | `test_threshold_fires` | Mock `oww.predict()` returns score above threshold → signal emits with correct `model_id` |
| `test_wake_detector.py` | `test_threshold_blocks` | Score below threshold → no signal |
| `test_wake_detector.py` | `test_cooldown` | Two consecutive triggers within 1.5s → only first emits |
| `test_wake_detector.py` | `test_no_detection_while_listening` | When `recorder.is_listening` → predict() not called, audio still fed |
| `test_wake_detector.py` | `test_corrupt_model_skipped` | One model load raises → detector loads others, emits warning |
| `test_settings_migration.py` | `test_jarvis_migrates_to_hey_jarvis` | Old `voice.wake_word="jarvis"` → new schema with hey_jarvis + plia enabled |
| `test_settings_migration.py` | `test_unknown_word_falls_back` | Old `voice.wake_word="americano"` → hey_jarvis + plia enabled, toast flag set |
| `test_settings_migration.py` | `test_idempotent` | Running migration twice produces the same result |
| `test_model_discovery.py` | `test_new_onnx_appended` | New file in `models/wake/custom/` → list grows on reload |
| `test_model_discovery.py` | `test_missing_file_marked_broken` | Settings row with deleted file → marked broken, not removed |

No GUI tests (matches existing repo convention — Settings widgets are not
unit tested).

## Open risks and mitigations

- **Microphone contention with other apps:** PyAudio's exclusive open is the
  same model Porcupine used; no behavioral change expected. If a user
  reports issues, fall back to shared/dmix is a follow-up.
- **Audio chunk size mismatch:** openWakeWord expects 1280-sample chunks
  (80 ms at 16 kHz). RealtimeSTT's `feed_audio()` accepts variable-size
  chunks. The mic loop reads 1280 samples and feeds the same chunks to both.
- **Plia model false-positive rate:** Will only be known after training.
  Mitigation: per-model sensitivity slider lets the user dial it down without
  re-training; if unusable, default `enabled: false` in V1 and ship as
  experimental.
- **openWakeWord first-run downloads:** `openwakeword.utils.download_models()`
  fetches the library's pretrained model bundle on first call. Since we
  instantiate `openwakeword.Model(wakeword_models=[explicit paths])` with
  our own bundled `.onnx` files, this call should not be needed; the
  implementation plan must verify that `Model.__init__` does not implicitly
  trigger `download_models()`. If it does, the install script needs to run
  it once during setup so the app works offline.
