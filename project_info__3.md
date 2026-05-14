# Plia — Codebase Overview & MCP Client Integration Gap (Explore Mode)

## Summary
Plia is a Python 3.11+ desktop assistant with a Fluent Qt (PySide6) UI, offline wake-word + speech-to-text, local LLM chat via Ollama, and a router→executor pipeline that turns natural language into concrete actions (timers, alarms, calendar, tasks, web search, desktop control, etc.). The core interaction loop is: **Chat/Voice input → FunctionGemmaRouter intent/function selection → FunctionExecutor backend execution → Qwen response streamed from Ollama → optional Piper TTS**. There is also an **Agent Builder** that generates standalone Python agent scripts and registers them in a local JSON registry for later execution.

This report documents the current architecture and pinpoints what must be added for your requested **MCP client** feature (“spawn MCP servers from `~/.plia/mcp.json`, expose their tools to the router”). A codebase scan found **zero existing MCP references**, so this is an integration gap rather than an extension of existing MCP code.

## Architecture

### Primary pattern
A **pipeline / command-routing** architecture:
1. **Intent routing** is done by a local fine-tuned FunctionGemma model (`core/router.py`).
2. **Action execution** is done by a centralized dispatcher (`core/function_executor.py`).
3. **Natural-language response** is produced by a chat model served by Ollama (`core/llm`/`gui/handlers.py`/`core/voice_assistant.py`).
4. **Voice I/O** is managed by dedicated modules (`core/stt.py`, `core/tts.py`, `core/voice_assistant.py`).

### Technology stack
- **Language**: Python 3.11+
- **UI**: PySide6 + qfluentwidgets (Fluent Windows-like UI)
- **Speech**:
  - STT/wake-word: RealTimeSTT (`core/stt.py`) with Porcupine wake words and WebRTC/Silero VAD fallbacks
  - TTS: Piper via `piper-tts` + `sounddevice` (`core/tts.py`)
- **LLM**: Ollama HTTP API (`/api/chat`, `/api/generate`) with models configured in `config.py` and persisted in `~/.plia/settings.json`
- **Routing model**: FunctionGemma (Hugging Face download into `merged_model/`) (`core/router.py`)
- **Data persistence**:
  - Chat sessions/messages: SQLite (`core/history.py`, `data/chat_history.db`)
  - Tasks/alarms: SQLite (`core/tasks.py`, `data/tasks.db`)
  - App settings: JSON (`core/settings_store.py`, `~/.plia/settings.json`)
  - Custom agents: JSON (`core/agent_registry.py`, `~/.plia_ai/custom_agents.json`)

### Execution start / runtime loop
- **Process entry**: `main.py`
  - Configures logging early (prevents RealtimeSTT from creating stray log files in the project root).
  - Starts Ollama (`start_ollama()`), then starts the Qt GUI.
- **Model preloading & persistence**:
  - `gui/app.py` starts a background `ModelPreloaderThread` calling `core/llm.preload_models()`.
  - For chat/voice, Qwen model loading/unloading is controlled by `core/model_persistence.py` (ensure/load, mark used, unload after inactivity).
- **User interaction loop**:
  - UI text input handled by `gui/handlers.py::ChatHandlers` and `ChatWorker`.
  - Voice input handled by `core/voice_assistant.py` (`VoiceAssistant`) calling the same underlying router/executor + streaming responses.

## Directory Structure (meaningful modules only)
```
project-root/
├── main.py                        — app entry; logging + Ollama bootstrap
├── config.py                      — model + router + audio config defaults
├── core/
│   ├── router.py                 — FunctionGemma router + tool schema extraction
│   ├── function_executor.py     — executes routed functions (timers, tasks, search, etc.)
│   ├── llm.py                    — router lazy-init + chat model preloading
│   ├── tts.py                    — Piper TTS engine + SentenceBuffer
│   ├── stt.py                    — RealTimeSTT listener + torchaudio/torch mismatch patching
│   ├── voice_assistant.py        — wake word → speech → router/executor → streamed chat + TTS
│   ├── model_persistence.py     — keep Qwen loaded for a while; unload on timeout
│   ├── ollama_paths.py           — canonical resolution of OLLAMA_HOST/OLLAMA_MODELS
│   ├── tasks.py                 — SQLite tasks + alarms
│   ├── history.py               — SQLite chat sessions/messages
│   ├── agent_builder.py         — generate runnable Python agent scripts with Ollama
│   ├── agent_registry.py        — persist custom agents; run in Ollama or as subprocess
│   ├── multi_agent.py           — Jarvis-like multi-agent runtime primitives (currently not wired into routing)
│   └── multi_hop_research.py   — multi-hop research with citations (special-case path)
└── gui/
    ├── app.py                    — Qt window; tab lazy loading; voice UI signal wiring
    ├── handlers.py              — ChatWorker pipeline (router → executor → Ollama chat)
    ├── tabs/                    — chat/planner/settings/agents/reading_files/etc.
    └── components/             — widgets used by streaming UI (thinking expander, search browser, etc.)
```

## Key Abstractions

### FunctionGemmaRouter
- **File**: `core/router.py`
- **Responsibility**: Routes a user prompt to one of a fixed set of function names by running a local FunctionGemma model. It also precomputes tool schemas for the Hugging Face chat template via `transformers.utils.get_json_schema`.
- **Interface**:
  - `route(user_prompt) -> (func_name, args_dict)`
  - `route_with_timing(user_prompt) -> ((func_name, args_dict), elapsed_seconds)`
- **Lifecycle**:
  - Instantiated lazily on first `route_query()` call (see `core/llm.py`).
  - Loads the router model from local `LOCAL_ROUTER_PATH` or downloads from `HF_ROUTER_REPO`.
- **Used by**:
  - `core/llm.py::route_query()`
  - `gui/handlers.py` indirectly via `core/llm.route_query()`

### FunctionExecutor
- **File**: `core/function_executor.py`
- **Responsibility**: Given a routed `func_name` and `params`, executes concrete backends (SQLite task manager, web search via ddgs, desktop control, weather/news aggregation, etc.). Returns a structured result: `{success, message, data}`.
- **Interface**:
  - `execute(func_name: str, params: Dict[str, Any]) -> Dict[str, Any]`
- **Lifecycle**:
  - A global singleton `executor = FunctionExecutor()` created at import time.
  - Internally lazily constructs managers (TaskManager, CalendarManager, WeatherManager, NewsManager) during `FunctionExecutor.__init__`.
- **Used by**:
  - `gui/handlers.py::ChatWorker.process()`
  - `core/voice_assistant.py::VoiceAssistant._process_query()` (via the same executor)

### ChatWorker (UI orchestration)
- **File**: `gui/handlers.py`
- **Responsibility**: Runs in a Qt `QThread` and owns the conversation pipeline for typed chat:
  - special-case build-agent intent
  - special-case multi-hop research mode
  - router→executor for action functions
  - Ollama streaming response generation and optional TTS queueing
- **Interface**:
  - `process()` — the entire pipeline for one user message
- **Lifecycle**:
  - Created per user send, moved into a background `QThread`, destroyed after signals emit `done`.
- **Used by**:
  - `ChatHandlers.send_message()`

### VoiceAssistant (wake word → streaming voice chat)
- **File**: `core/voice_assistant.py`
- **Responsibility**: Runs wake-word STT and then applies a voice-specific intent interception layer (search pagination, weather window, help, reading files, desktop triggers). When appropriate, it routes via `core/llm.route_query()` and executes via `core/function_executor.py`, then streams Qwen responses and queues Piper TTS.
- **Interface**:
  - `initialize()`, `start()`, `stop()`
- **Lifecycle**:
  - Started from `gui/app.py` background thread depending on config + user setting (`VOICE_ASSISTANT_ENABLED` and `voice.auto_start`).
- **Used by**:
  - `gui/app.py` (signal wiring)
  - Internally depends on `STTListener`, `ensure_qwen_loaded`, `http_session`, and the TTS singleton.

### STTListener + torchaudio patching
- **File**: `core/stt.py`
- **Responsibility**: Provides real-time transcription with Porcupine wake-word detection using RealTimeSTT. Contains a *large, deliberate* compatibility layer to avoid crashes when `torch`/`torchaudio` are mismatched or partially imported.
- **Interface**:
  - `initialize() -> bool`
  - `start()`, `stop()`
- **Lifecycle**:
  - Created by `VoiceAssistant.initialize()`.
  - `initialize()` re-reads wake word and sensitivity from settings to allow “settings apply without restart”.
- **Used by**:
  - `core/voice_assistant.py`

### VoiceEngine (Piper TTS) + SentenceBuffer
- **File**: `core/tts.py`
- **Responsibility**: Provides async sentence-based TTS playback with two critical concurrency guards:
  - serialization of ONNX synthesis
  - serialization of `sounddevice.sd.play()` to prevent PortAudio crashes on Windows
- **Interface**:
  - `toggle(enable: bool)`, `queue_sentence(sentence: str)`, `stop()`, `wait_for_completion()`
- **Lifecycle**:
  - A global singleton `tts = VoiceEngine()` created at import time; actual audio engine initialized when toggled on.
- **Used by**:
  - `gui/handlers.py`
  - `core/voice_assistant.py`
  - `gui/app.py` (connects TTS signals to voice indicators)

### AgentBuilder & AgentRegistry
- **Files**:
  - `core/agent_builder.py`
  - `core/agent_registry.py`
- **Responsibility**:
  - `agent_builder.py` uses Ollama to generate standalone Python agent scripts, or uses a hardcoded template for “search and download” intents.
  - `agent_registry.py` persists agent metadata to `~/.plia_ai/custom_agents.json` and can run agents either:
    - via Ollama using the stored system prompt, or
    - as subprocess for file-based agents built by AgentBuilder.
- **Used by**:
  - `gui/handlers.py` for chat-triggered agent creation/run

### MCP integration gap (current codebase)
- **Observation**: A regex search for `MCP`/`mcp` in Python files found **0 hits**.
- **Implication**: There is no existing MCP client, no dynamic MCP tool schema injection, and no dispatcher for “tool calls” originating from MCP servers.

## Data Flow (primary runtime paths)

1. **App startup**
   1. `main.py::_configure_logging()` pre-configures logging handlers.
   2. `main.py::start_ollama()` checks daemon health (`/api/tags`) and spawns `ollama serve` with a deterministic `OLLAMA_MODELS`.
   3. `gui/app.py::MainWindow` starts `ModelPreloaderThread` → `core/llm.preload_models()` warms router/responder/voice.

2. **Typed chat message**
   1. `gui/handlers.py::ChatHandlers.send_message()` creates a `ChatWorker` with current message context and launches it in a `QThread`.
   2. `ChatWorker.process()` handles high-priority bypass modes:
      - file-read bypass sets `bypass_router=True` and streams via `_stream_qwen_file_response()` (wide context, routing skipped)
      - multi-hop research runs before the router
      - agent-builder intents run before function routing
   3. For normal requests:
      1. `core/llm.route_query()` lazy-loads `FunctionGemmaRouter` and returns `(func_name, params)`.
      2. If `func_name` is in `ACTION_FUNCTIONS`, `FunctionExecutor.execute(func_name, params)` runs concrete side effects.
      3. `ChatWorker._generate_response_with_context()` appends system context derived from the function result and streams a Qwen reply from Ollama (`/api/chat`).
      4. Stream chunks are buffered by `SentenceBuffer`, and sentences are queued to Piper TTS.

3. **Voice request**
   1. `gui/app.py` starts `VoiceAssistant` in a background thread.
   2. `core/stt.py::STTListener` waits for wake word, then calls `VoiceAssistant._on_speech()`.
   3. `VoiceAssistant._process_query()` intercepts some voice phrases (weather/search/help/desktop/reading files).
   4. Remaining cases use the same router+executor path:
      - `route_query()` → `function_executor.execute()` → streamed `/api/chat` generation → TTS queue.

## Non-Obvious Behaviors & Design Decisions

### 1) Router avoids a known torch/torchaudio circular import crash
`core/router.py` deliberately performs **lazy imports** of `torch` and heavy `transformers` classes inside `FunctionGemmaRouter.__init__()`. This prevents a previously observed failure chain where `torch` is “poisoned” in `sys.modules`, later causing STT initialization to crash (the comments in `core/router.py` and `core/stt.py` document this).

**Meaning for developers:** Never “helpfully” move torch imports to module-level; routing and STT initialization order is fragile.

### 2) Logging is configured before any third-party imports
`main.py` configures root logging with a `NullHandler` before other imports, and it redirects the `realtimestt` logger into `log/realtimesst.log`. That is essential because RealTimeSTT can create stray log files in the project root when it thinks it owns logging.

### 3) TTS uses strict sd.play serialization to prevent PortAudio segfaults
`core/tts.py` uses separate locks for:
- ONNX synthesis (`self._lock`)
- audio playback (`self._play_lock`), plus it has a “do not initialize twice” guard to prevent multiple worker threads.

**Meaning for developers:** Any integration that triggers TTS initialization from multiple threads must follow the guard logic; otherwise the entire process can segfault (not just “TTS fails”).

### 4) Router tool schemas are precomputed but function dispatch is fixed
`FunctionGemmaRouter` uses Hugging Face `apply_chat_template(... tools=TOOLS ...)`, but dispatch is not dynamic:
- `_parse_function_call()` scans the raw model output for `call:<func_name>` among a **hardcoded** `VALID_FUNCTIONS` set.
- `FunctionExecutor.execute()` dispatches via a long `if/elif` chain keyed by `func_name`.

**Meaning for MCP:** “Expose MCP tools to the router” requires changes in **both**:
1) the router’s tool schema list used for chat-template prompting, and
2) the executor/dispatcher logic that actually runs tools and returns outputs.

### 5) Multi-hop research and build-agent are “priority escapes”
`ChatWorker.process()` runs multi-hop research before router routing, and it runs AgentBuilder before both routing and custom agent creation. This is an intentional ordering to prevent tool-schema/routing misclassification when the user requests code-building or research-citation flows.

## Suggested Reading Order (to work effectively)
1. `main.py` — startup ordering, logging, and Ollama daemon bootstrap
2. `gui/handlers.py` — ChatWorker pipeline + how router/executor are called + how streaming and TTS are wired
3. `core/router.py` — FunctionGemma router design (tool schemas, call parsing, lazy torch imports)
4. `core/function_executor.py` — execution contract and side-effect implementations
5. `core/stt.py` + `core/tts.py` — the concurrency/compatibility constraints that affect any new features in voice mode
6. `core/agent_builder.py` + `core/agent_registry.py` — how dynamically generated agents integrate into the UI

## Module Reference (one-liners)
| File | Purpose |
|---|---|
| `main.py` | Entry point; logging configuration + Ollama auto-start with aligned `OLLAMA_MODELS` |
| `gui/app.py` | Qt window; lazy tab loading; voice assistant signal wiring; TTS/STT bootstrap thread |
| `gui/handlers.py` | ChatWorker: special-case flows (agent builder, multi-hop research, file read bypass) + router→executor→Qwen streaming |
| `core/llm.py` | Router lazy-init and model preloading; also defines helper routing error fallback |
| `core/router.py` | FunctionGemma intent/function routing; tool schema generation; call parsing |
| `core/function_executor.py` | Executes routed functions and returns `{success,message,data}` |
| `core/voice_assistant.py` | Wake-word and voice command interception + streaming response with TTS |
| `core/stt.py` | RealTimeSTT + wake-word + torchaudio/torch mismatch crash-patching |
| `core/tts.py` | Piper TTS engine with sentence buffering and crash-safe playback serialization |
| `core/model_persistence.py` | Qwen keep-alive/unload timer logic for VRAM management |
| `core/tasks.py` | Tasks + alarms persistence layer (SQLite) |
| `core/history.py` | Chat sessions/messages persistence (SQLite) |
| `core/agent_builder.py` | Generates runnable agent scripts using Ollama; optional search+download template agent |
| `core/agent_registry.py` | Persists custom agent metadata + runs them via Ollama or subprocess |
| `core/multi_hop_research.py` | Evidence gathering + citation validation + streamed synthesis |

---

# MCP Client Feature: What’s missing and what must be integrated

Your request (per notes) is: implement an **MCP client** (likely `core/mcp_client.py`) that:
- spawns MCP servers based on a config like `~/.plia/mcp.json` (Claude-Desktop style),
- exposes their tools to the router,
- allows the router to call those tools, and the assistant to incorporate tool results.

## What the current code can do (and cannot do)
### Can do
- A single local router model selects from a fixed set of “functions”.
- A single executor runs real backends for those functions and returns structured results to the chat model.
- The router prompt already supports **tool schema prompting** (via `TOOLS` list and `apply_chat_template`).

### Cannot do (today)
- No MCP server lifecycle management.
- No dynamic tool list generation from MCP server discovery.
- No tool-call dispatch path that can call “tool names” discovered at runtime.
- No mechanism to represent tool outputs in a way compatible with the existing call parsing and executor contract.

## Key integration points (where a new MCP client would plug in)

1. **Tool schema source for the router**  
   Currently: `core/router.py` hardcodes `TOOLS = [get_json_schema(set_timer), ...]`.  
   For MCP: this must become dynamic, likely:
   - load MCP tool schemas at startup (or lazy-first-use),
   - merge them into the tool list used in `apply_chat_template`.

2. **Function name parsing & dispatch**  
   Currently: `_parse_function_call()` scans raw output for `call:<func_name>` among `VALID_FUNCTIONS`.  
   For MCP: the router would need to emit calls to MCP tools using a stable naming scheme (e.g. `mcp.<server>.<tool>`), and:
   - expand `VALID_FUNCTIONS` accordingly (or remove the strict scan),
   - teach `FunctionExecutor.execute()` to route `mcp.*` calls to MCP tool invocations.

3. **Executor contract and returned data shape**  
   `ChatWorker._generate_response_with_context()` builds system context based on:
   - `get_system_info` expects `data` keys like timers/alarms/weather/news
   - `web_search` expects `data.results`
   - all other functions rely on `result["message"]` mostly.
   
   For MCP: tool outputs may be arbitrary JSON; you’ll need to decide how to present them:
   - either into `result["data"]` and have response-generation incorporate it,
   - or convert outputs to readable summaries for `result["message"]`.

4. **Config/path alignment**
   - The app currently uses `~/.plia_ai/` for agents/tasks/models and `~/.plia/settings.json` for UI settings (`core/settings_store.py`).
   - Your MCP note uses `~/.plia/mcp.json`.
   A careful implementation should avoid path inconsistencies by:
   - either reusing existing `~/.plia` config convention,
   - or extending the settings store with an `mcp` section.

## Likely invariants you must preserve while implementing MCP
- Keep **router torch lazy import behavior** untouched.
- Ensure **TTS initialization** doesn’t get called from multiple threads.
- Preserve `ChatWorker`’s special-case priority ordering (so multi-hop research and agent builder requests still bypass MCP routing if needed).
- Avoid blocking the Qt UI thread: MCP server I/O/discovery should be async or run in background threads.

## Checklist for MCP implementation (integration design, not code)
- [ ] Decide the MCP config file location and schema (`~/.plia/mcp.json` vs `~/.plia_ai/...`) and whether it should be managed by `SettingsStore`.
- [ ] Implement `core/mcp_client.py`:
  - [ ] spawn MCP servers from config (process lifecycle management)
  - [ ] connect to servers and discover available tools
  - [ ] expose a runtime API to “execute tool X with args”
- [ ] Update router tooling:
  - [ ] replace the static `TOOLS` list in `core/router.py` with a dynamic tool list that includes MCP tool schemas
  - [ ] adjust call parsing so MCP tool calls are recognized reliably (not just by scanning a fixed `VALID_FUNCTIONS` set)
- [ ] Update executor:
  - [ ] add a dispatch branch for MCP tool calls that invokes `core/mcp_client.py`
  - [ ] normalize tool results into `{success, message, data}` for downstream response generation
- [ ] UI/voice behavior:
  - [ ] ensure voice mode (`core/voice_assistant.py`) can trigger MCP tool calls through the same pipeline
  - [ ] ensure web search pagination/help/desktop interception still works correctly
- [ ] Add diagnostics:
  - [ ] surface “MCP server failed / tool discovery failed” in logs and (optionally) UI to avoid silent tool loss
- [ ] Add tests / smoke validation:
  - [ ] verify tool discovery and invocation with one small test server
  - [ ] verify streaming response still works with tool outputs included in context
