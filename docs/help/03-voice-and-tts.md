# Voice & TTS

Plia uses **Porcupine** for wake-word detection, **RealTimeSTT (Whisper)** for speech-to-text, and **Piper** for text-to-speech. All local.

## Wake word

Default: **jarvis**. You can change it in **Settings → Voice → Wake Word** to one of the supported keywords (computer, terminator, alexa, etc.).

After the wake word fires you have a short window to speak your command. STT returns the text to the pipeline:
1. **Create-agent intent** → wizard starts (see Live Agents page)
2. **Active wizard** → your answer is routed to the wizard
3. **"read option N" / "open file N"** → opens that file from the last list
4. **Search browser controls** → "next page", "previous page", "open result N"
5. **Everything else** → routed to the Function Gemma router, which picks a tool or replies via the LLM

## Multi-turn wizard

When you're in the middle of an agent-creation wizard, **STT is primed for follow-up between turns** — you don't have to say "jarvis" before each answer. Plia's TTS finishes speaking the next question, then immediately re-arms the microphone for your answer.

## TTS settings

In **Settings → Voice**:
- Voice (e.g. en_US-lessac-medium, en_GB-northern_english_male-medium)
- Length scale (speech speed)
- Volume
- Mute toggle

The voice model is downloaded on first use.

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
