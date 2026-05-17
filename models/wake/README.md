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
