# Plia — Installed vs Installable Capabilities (from your list)

## Summary
Plia is a **fully local desktop assistant** (Python 3.11+, PySide6 GUI) that already includes: **streaming local LLM chat via Ollama**, **file preview + “read aloud” + Q&A over extracted text**, **web search**, and **a FunctionGemma router** for function-calling. From your list, the codebase already implements **multi-hop research with citations**, and has an **MCP client bridge** (via the official `mcp` Python SDK) that can call tools exposed by MCP servers defined in `~/.plia/mcp.json`. Several items (diarization, redaction, Composio, WhatsApp/Instagram automation, Jetson packaging, etc.) are **not present in dependencies or code search results**—they’d require additional integrations and/or external services.

## Architecture (relevant for capability mapping)
- **Router & tool calling**
  - `core/router.py`: FunctionGemma (HF model) classifies prompts into a small set of callable functions (timers, web search, desktop control, system info, etc.).
  - `core/function_executor.py`: executes routed functions and returns `{success, message, data}`.
  - `core/mcp_client.py`: background asyncio loop that loads MCP servers from `~/.plia/mcp.json`, discovers tools, and executes them.
  - `core/router.py` + `core/function_executor.py`: expose a single stable `mcp_tool_call(tool_id, arguments)` bridge so MCP tool routing is possible without retraining the router.
- **LLM interaction**
  - `core/llm.py`, `gui/handlers.py`, `core/voice_assistant.py`: stream from Ollama `/api/chat` and feed results into TTS sentence buffering.
- **File reading / “RAG-ish” behavior**
  - `gui/tabs/reading_files.py`: extracts text from selected files (PDF/DOCX/CSV/XLSX/JSON/text/code) into in-app preview.
  - Chat “reading files” flow (voice + chat) can embed extracted file content into the prompt (no embedding index).

## Directory / module anchors (what I used)
- `requirements.txt`, `pyproject.toml`, `config.py`, `README.md`
- `gui/tabs/reading_files.py`
- `gui/handlers.py`, `core/multi_hop_research.py`
- `core/mcp_client.py`
- `core/router.py`, `core/function_executor.py`
- `core/network_tools.py`
- `core/voice_assistant.py`

## Installed (already present) vs Installable (missing but feasible)

### Quick checklist (mapped to your items)
Legend:
- **✅ Installed/Implemented** = code exists or dependency is already included and wired up.
- **🟡 Installable-by-config** = support exists but needs external servers/services/config.
- **❌ Not found in code/deps** = no evidence in installed Python deps or code searches for explicit integration.

| Your capability item | Plia status | Evidence / where it lives |
|---|---:|---|
| Document indexing + RAG over local files (open-jarvis) | 🟡 Partial (single-doc preview + prompt embedding) | `gui/tabs/reading_files.py` extracts text; chat/voice can embed file content into LLM context. No embeddings/vector index found in explored code. |
| Multi-hop research with citations (open-jarvis, isair) | ✅ Implemented | `core/multi_hop_research.py` + trigger logic in `gui/handlers.py` (strict citation validation loop). |
| Multi-person conversation tracking + diarisation | ❌ Not found | No diarization pipeline identified in the explored code/requirements. Likely absent. |
| Sensitive-data auto-redaction before LLM calls | ❌ Not found | No redaction module found in searches; no preprocessing layer observed. |
| MCP client w/ 500+ tool servers | 🟡 Installable (via config + external MCP servers) | `core/mcp_client.py` loads servers from `~/.plia/mcp.json` using `mcp>=1.0.0` in `requirements.txt`; router includes `mcp_tool_call` and injects MCP tool catalog text into router developer prompt. |
| Composio integration | ❌ Not found | No composio dependency or integration points found. |
| Skills marketplace (agentskills/Hermes/OpenClaw skills) | ❌ Not found | No “skills marketplace” loader found; agent system is present but no marketplace wiring found. |
| Home Assistant integration | ❌ Not found | No explicit Home Assistant client found. |
| Smart tool selection / auto-pruning so more tools don’t degrade routing | 🟡 Partially (router function selection exists; pruning not observed) | Router selects one function; MCP tool catalog is injected but there is no visible “pruning/embedding index of tools” mechanism beyond limiting catalog size (`core/mcp_client.py` has max tool catalog limits). |
| Morning digest scheduled agent | ❌ Not found as scheduled agent | `core/news.py` exists for briefing content, but no scheduler/cron-like agent flow found in explored files. |
| Deep research agent w/ multi-step planning | ✅ Multi-hop research exists | Implemented specifically as citations-based multi-hop; not necessarily a generalized “deep research agent” framework. |
| Continuous monitoring agent (long-running background watchers) | 🟡 Partially (model persistence timeout, but no watchers) | There is model “unload after inactivity” logic (`core/model_persistence.py` search hits). No generic “watchers” agent loop found in explored files. |
| ReAct reasoning loop | ❌ Not found explicitly | No explicit ReAct loop found; router uses function calling + LLM. |
| WhatsApp messaging incl. group chats | ❌ Not found | No WhatsApp integration found. |
| Instagram profile/content interaction | ❌ Not found | No Instagram integration found. |
| Google Maps queries beyond weather lat/lon | ❌ Not found | No Google Maps integration found. |
| Internet speed test | ✅ Implemented | `core/network_tools.py` has `speed_test()` (download test). |
| QR code generation | ❌ Not found | No QR generation found in code searches. |
| Phone-number geolocation lookup | ❌ Not found | No phone geolocation found; only IP geolocation (`public_ip_info`). |
| Screen recording w/ audio | ❌ Not found | Desktop agent screenshots exist, but not screen recording with audio. |
| Webcam capture & mobile-camera access | ❌ Not found | No webcam capture pipeline found. |
| Facial recognition login/auth | ❌ Not found | No face recognition found. |
| Gender-switchable voice persona | 🟡 Voice persona partially supported via TTS model selection | TTS is Piper-based (`config.py` includes `TTS_VOICE_MODEL`), but no explicit “male/female persona switching UI” found in explored code. |
| Jetson / embedded device packaging (microsoft/JARVIS style) | ❌ Not found | No Jetson build/packaging found. |
| Local trace data → fine-tuning loop | ❌ Not found | No training/finetune pipeline found. |
| Adaptive tone per context (code/business/wellness) | 🟡 Partially (prompt tuning; not a full tone system) | General system prompts exist; no explicit “tone classifier + persona routing” found in explored searches. |
| Location awareness via embedded GeoLite2 DB (MaxMind) | ❌ Not found | No GeoLite2/MaxMind integration found; only IP geolocation via `ip-api.com` in `core/network_tools.py`. |

## Key Abstractions (what matters for these capabilities)

### MCPClient (MCP tool bridge)
- **File**: `core/mcp_client.py`
- **Responsibility**: Reads `~/.plia/mcp.json`, spawns MCP servers (stdio transport only), discovers tool schemas, caches a tool catalog for prompt injection, and executes tool calls synchronously via `execute(tool_id, arguments)`.
- **Interface**:
  - `is_ready()`: signals when discovery completed (even if 0 tools).
  - `get_tool_catalog_text()`: returns short “tool_id → description” catalog (truncated for prompt size).
  - `execute(tool_id, arguments)`: normalizes arguments, runs MCP call on its event loop thread, returns `{success,message,data}`.
- **Lifecycle**: instantiates a module-level singleton `mcp_client = MCPClient()` at import time; discovery happens in a background thread/event loop.
- **Used by**:
  - `core/router.py` injects MCP tool catalog into router developer prompt (if ready).
  - `core/function_executor.py` implements `_mcp_tool_call()` which calls `mcp_client.execute()`.

### FunctionGemmaRouter (function calling via learned routing)
- **File**: `core/router.py`
- **Responsibility**: Classifies user input into one of a fixed set of function schemas (including `mcp_tool_call`), then parses model output into a `(func_name, params)` call.
- **Important design constraint**: torch imports are **lazy** inside `FunctionGemmaRouter.__init__()` to avoid circular-import startup crashes (explicitly documented in file header).
- **Used by**: `core/voice_assistant.py` and `gui/handlers.py` via `core/llm.py` routing.

### Multi-hop research with citations
- **File**: `core/multi_hop_research.py` + `gui/handlers.py`
- **Responsibility**:
  - Planner: generate N targeted web queries (non-streaming).
  - Evidence: run `web_search` per query, deduplicate by URL, truncate snippets.
  - Synthesis: enforce strict citation rules (`[n]` tokens only; a “Sources:” bibliography).
  - UI integration: `gui/handlers.py` streams the final synthesis and validates citations; retries up to `MULTIHOP_FINAL_CITATION_MAX_RETRIES`.
- **Why this matters**: it provides the “open-jarvis/isair style” research loop without needing a separate embedding store.

### Reading Files (local-file “RAG without embeddings”)
- **File**: `gui/tabs/reading_files.py` and the chat/voice flows in `gui/handlers.py` / `core/voice_assistant.py`
- **Responsibility**: Extract text from local files into memory for preview and for prompt embedding when the user chooses “read option N”.
- **Key implication**: it’s **single-document** context injection; no persistent vector index observed in the explored code.

### NetworkTools (internet speed test + IP geolocation)
- **File**: `core/network_tools.py`
- **Responsibility**: Implements:
  - `speed_test()` via a 10MB download test.
  - `public_ip_info()` using `ip-api.com`.
- **Used by**: `core/function_executor.py` exposes `network_tools` and related schemas.

## Data Flow (relevant paths)
1. **Chat/voice input → routing**
   - Chat: `gui/handlers.py` → `core/llm.py` → `core/router.py` → `(func_name, params)`
   - Voice: `core/voice_assistant.py` → `core/llm.py` routing
2. **Action execution**
   - `core/function_executor.py` dispatches the function name to concrete implementations.
3. **MCP tool execution**
   - Router prompt includes MCP tool catalog text from `core/mcp_client.py`.
   - LLM emits `mcp_tool_call(tool_id, arguments)` → executor calls `mcp_client.execute()`.
4. **Multi-hop research**
   - `gui/handlers.py` intercepts multi-hop + citations requests → `core/multi_hop_research.py`
   - Evidence collection uses `function_executor.execute("web_search", ...)`
   - Final synthesis streams from Ollama and validates citations with `validate_citations()`.

## Non-Obvious Behaviors & Gaps (based on your specific list)
- **MCP is “big gap filled”**: the codebase already includes an MCP bridge and router integration; the only real requirement is external MCP server availability and `~/.plia/mcp.json` configuration.
- **Local-file “RAG” is context injection**: no evidence of embeddings/storage; multi-document retrieval and semantic search are not present in the explored modules.
- **Strict citation loop exists only for multi-hop research**: citation validation is specialized to that workflow; general chat doesn’t enforce citations.
- **Many requested automation capabilities are absent**: WhatsApp/Instagram/Home Assistant/Maps/QR/screen recording/facial recognition require new third-party libraries and new UI/tooling entry points; nothing in current requirements or searches suggests they are already wired.

## Suggested Reading Order (to work effectively)
1. `main.py` — startup flow and Ollama bootstrap
2. `core/router.py` — routing + function schema and MCP tool-call bridge
3. `core/function_executor.py` — how routed functions become real actions
4. `core/mcp_client.py` — MCP server discovery + execution thread model
5. `core/multi_hop_research.py` + `gui/handlers.py` — the multi-hop citations pipeline
6. `gui/tabs/reading_files.py` — local file extraction strategy

## What I still could verify (if you want a second pass)
If you want this inventory to be 100% evidence-complete for the “❌ Not found” items (diarization, redaction, QR, QR, webcam/screen recording, etc.), I can do a deeper module-by-module read focused on:
- `core/stt.py` (diarization signals, redaction hooks)
- `gui/tabs/*` for any hidden integrations
- `core/agent_builder.py` for builder-generated tool availability
- Any “desktop agent” media capture code paths (screen/webcam)