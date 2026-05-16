# Troubleshooting & FAQ

## "Active Agents shows the responder as 'not loaded'"

That's by design. The QwenManager auto-unloads the responder LLM after 5 minutes idle to reclaim ~5 GB of VRAM. Plia announces the unload (TTS + Communication Log). Your next chat / agent run reloads it transparently with a brief warm-up.

If you want it always loaded, edit `config.py`:
```python
QWEN_TIMEOUT_SECONDS = 999999
QWEN_KEEP_ALIVE      = "-1"  # Ollama: never unload
```

## "An agent returned 0 items and the chat is empty"

The tool-loop LLM probably skipped its `web_search` call. Plia tries to nudge it once but small models are unreliable. Options:
- Switch the chat model to `qwen3:8b` or `llama3.1:8b` in **Settings → AI Models** (or `models.chat` in `~/.plia/settings.json`). The Model Browser tab shows what fits your hardware.
- Edit the agent's task to be very explicit: *"You MUST call web_search first…"*
- The chat now also shows the LLM's full prose response when no items were extracted, so you'll at least see what it *did* say.

## "My agent posts to a chat session but I can't find it"

Check the chat sidebar — agents with `notify=chat` create their own per-agent session titled `🤖 <agent name>`. They're listed alongside your manual chats.

## "Voice wizard keeps asking the same question"

STT mis-heard your answer. Plia's parsers require recognisable keywords:
- Trigger: "scheduled", "on demand", "quota"
- Persistence: "persistent" / "survive restarts" / "session only"
- Notify: "speak"/"aloud" → tts, "chat", "communication log", "save to file", "web searches", "toast" — combinable
- Cadence: "every hour", "every 6 hours", "twice a day", "every Monday morning", etc.

Try a simpler phrasing. You can also type the same answer in the chat wizard.

## "MCP server shows ● not connected"

- Check the command runs from a normal terminal first (e.g. `npx -y @modelcontextprotocol/server-github`).
- Check the env vars are set (most MCP servers require an API token).
- Use **Reload Now** on the MCP Servers tab to retry.
- Check Plia's console output — `_async_serve_server` errors print there.

## "Agent crashed with 'no_json'"

The agent has `executor=script` but its script doesn't follow the JSON-output contract. Edit the agent and either:
- Change the executor to `tool_loop` (recommended — uses the LLM)
- Or rewrite the script so its final stdout line is a JSON object: `{"success": true, "summary": "...", "details": "...", "items_found": N, "items": [...]}`

## Shutdown crash / SIGABRT on close

That's been fixed. If you still see `QThread: Destroyed while thread '' is still running`, please re-pull `main` — the SystemMonitor and AgentStatus QThreads are now cleaned up in `MainWindow.closeEvent`.

## File locations

| Path | Purpose |
|---|---|
| `~/.plia/settings.json` | App settings (voice, models, search, etc.) |
| `~/.plia/mcp.json` | MCP server configs |
| `~/.plia_ai/agent_state.json` | Live agent persistent state |
| `~/.plia_ai/roles/*.yml` | Role definitions per agent |
| `~/.plia_ai/agent_results/*.log` | Per-agent file output (for `notify=file`) |
| `~/.plia_ai/web_searches.json` | Web Searches tab log |
| `~/.plia_ai/plugins/*.py` | User plugin files |
