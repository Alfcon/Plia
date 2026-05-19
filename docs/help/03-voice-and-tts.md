# Voice & TTS

Plia uses **openWakeWord** for wake-word detection, **RealTimeSTT (Whisper)** for speech-to-text, and **Piper** for text-to-speech. All local.

## Wake words

Plia supports **multiple wake words at once**. Bundled models that ship with the repo:

- **Hey Jarvis** (enabled by default)
- **Plia** (enabled by default *— but currently unavailable until the .onnx is committed; see below*)
- Alexa, Hey Mycroft, OK Nabu, Hey Rhasspy (disabled by default)

Toggle them on/off and tune per-model sensitivity in **Settings → Voice & Audio → Wake Words**. Use **+ Add Model…** to drop in any openWakeWord `.onnx`.

> **Plia wake word not firing on a fresh install?** The default settings list `bundled/plia.onnx` but the file is not yet committed to the repo — train your own via openWakeWord's [automatic_model_training notebook](https://github.com/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb) and drop the result into `models/wake/bundled/plia.onnx`. The in-app trainer is paused (see `config.WAKE_TRAINER_ENABLED`).

After any wake word fires you have a short window to speak your command. STT returns the text to the pipeline:
1. **Wake-trainer build intent** (e.g. *"train a wake word for plia"*) → currently announces it's paused
2. **Create-agent intent** → wizard starts (see Live Agents page)
3. **Active wizard** → your answer is routed to the wizard
4. **"read option N" / "open file N"** → opens that file from the last list
5. **Search browser controls** → "next page", "previous page", "open result N"
6. **Everything else** → routed to the FunctionGemma router, which picks a tool or replies via the LLM

## Multi-turn wizard

When you're in the middle of an agent-creation wizard, **STT is primed for follow-up between turns** — you don't have to say a wake word before each answer. Plia's TTS finishes speaking the next question, then immediately re-arms the microphone for your answer.

## TTS settings

In **Settings → Voice & Audio**:
- Voice (e.g. en_US-lessac-medium, en_GB-northern_english_male-medium)
- Speech length (50–200%, 100% is normal)
- Volume (0–100%)
- Mute TTS

Changes apply immediately to the running engine; values survive restart.

## Idle VRAM management

If the responder LLM (qwen3:8b by default) goes idle for 5 minutes, Plia unloads it from VRAM to give other things room. You'll get:
- A TTS announcement ("Responder model qwen3:8b unloaded after 300s idle to free VRAM. It will reload automatically on next use.")
- A 🧠 entry in the Dashboard Communication Log

Next time you invoke the LLM (chat, voice, agent run), it reloads transparently (~5–10 second warm-up on the first call after idle).

Configure the timeout in `config.py`:
```python
QWEN_TIMEOUT_SECONDS = 300  # 5 minutes
QWEN_KEEP_ALIVE      = "5m"
```
