# Welcome to Plia

Plia is a **local-first AI assistant**: a voice-driven, multi-agent system that runs entirely on your machine via [Ollama](https://ollama.com). No cloud calls for the core features, no telemetry.

## The 30-second tour

| Tab | What it does |
|---|---|
| **Dashboard** | Live system stats + Communication Log + voice indicator |
| **Chat** | Conversational interface with persistent history |
| **Planner** | Calendar, tasks, alarms, timers |
| **Briefing** | RSS news feed + morning digest |
| **Active Agents** | System health: AI models, voice pipeline, function agents |
| **Agent List** | **Where you create and manage Live Agents** — the heart of Plia |
| **Web Searches** | Search-result-style output from agents |
| **MCP Servers** | Manage Model Context Protocol server connections |
| **Model Browser** | Hardware-aware LLM picker |
| **Reading Files** | Voice-friendly file reader |
| **Settings** | Voice, models, search backend, redaction, etc. |

## First 5 minutes

1. **Say "jarvis"** (or your configured wake word). Plia's voice indicator lights up.
2. Try a voice command: *"jarvis what's the weather?"* or *"jarvis open the chat"*.
3. **Create your first agent** by saying: *"jarvis create an agent that watches GitHub for AI assistant projects"*. Walk through the spoken wizard.
4. Or **type the same** in the Chat tab — the same wizard opens as a dialog.
5. Find your new agent in **Agent List** under "Live Agents". Click **▶ Run now** or **💬 Run with prompt…**.

## What makes Plia different

- **Live agents are first-class.** They have schedules (on-demand / scheduled / quota), tool whitelists, multi-channel notify (TTS, chat, comm-log, file, dashboard cards, the Web Searches tab — any combination), and per-agent chat sessions.
- **Agents can orchestrate agents** via the `list_agents` + `run_agent` tools (3-level recursion guard).
- **Plugins**: drop a `.py` file in `~/.plia_ai/plugins/` and your custom tool is callable by every agent.
- **MCP server support**: connect to any [Model Context Protocol](https://modelcontextprotocol.io) server via the MCP Servers tab.
- **Search backends**: Brave Search (with API key) or DuckDuckGo (no key); auto-fallback.
- **Hardware-aware**: idle responder model is auto-unloaded after 5 minutes to free VRAM (with TTS + log notification).

See the other Help pages for deep dives.
