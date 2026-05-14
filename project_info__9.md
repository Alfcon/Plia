# Plia — Feature Parity Check (Added vs Not Added)

## Summary
Plia is a fully local, Windows-focused desktop assistant with a Qt (PySide6) GUI, voice control (wake-word STT + Piper TTS), and an Ollama-backed LLM chat pipeline. The codebase already contains **multi-hop web research with strict citations** and **deterministic sensitive-data redaction before LLM calls**, plus an **MCP client/tool bridge** and a **daily scheduled morning digest**. The largest gaps versus your requested “open-jarvis/isair-style” feature list are **no local-file embedding index / RAG across many documents**, **no diarization / multi-person tracking**, and **no sign of major integrations** (Composio, Home Assistant, WhatsApp/Instagram, etc.).

---

## Architecture

### Primary pattern
**GUI-driven orchestration with background workers**:
- UI emits signals → `ChatWorker` (Qt QObject) runs in a `QThread` → calls into core modules (router/executor/multi-hop/mcp/redaction/tts/stt) → streams responses back to the UI.

### Technology stack
- **Language/Runtime**: Python 3.11+
- **GUI**: PySide6 + `qfluentwidgets`
- **Local LLM**: Ollama HTTP API (streaming `/api/chat`)
- **Intent/Tool routing**: “FunctionGemmaRouter” (fine-tuned “function calling” model downloaded from HF)
- **Web search**: `ddgs` (DuckDuckGo) via `core/function_executor.py`
- **Speech**: RealtimeSTT (Porcupine wake word) + Piper TTS (local)
- **Tooling protocol**: MCP client SDK (`mcp>=1.0.0`)

### Execution start (high level)
- `main.py` configures logging, starts Ollama if needed, then launches `gui/app.py` (`MainWindow`).
- For each user message:
  - `gui/handlers.py::ChatHandlers.send_message()` spawns a `QThread` and runs `ChatWorker.process()`.
  - `ChatWorker` decides: multi-hop (special keyword trigger) → else router routing → else direct “thinking/nonthinking”.
  - Action functions execute via `core/function_executor.py`, then the final answer streams via `core/llm`/Ollama.

---

## Directory Structure (only meaningful parts)

```text
project-root/
├── gui/                         # Qt GUI and UI event handlers
│   ├── handlers.py             # ChatWorker: routing, tool execution, streaming
│   └── tabs/
│       ├── reading_files.py   # Single-doc preview + on-demand extraction
│       ├── chat.py            # Session list + message UI
│       └── settings.py       # Settings including morning digest cards
├── core/                        # Core logic (routing/executor/research/STT/TTS/MCP)
│   ├── router.py               # FunctionGemma router (tool/function calling)
│   ├── function_executor.py   # Executes routed tools (timer, web_search, etc.)
│   ├── redaction.py            # Deterministic sensitive-data redaction
│   ├── multi_hop_research.py  # Planner loop + evidence + strict citations
│   ├── mcp_client.py           # MCP server discovery + stdio tool execution
│   ├── stt.py                  # RealTimeSTT listener + Porcupine wake word
│   └── voice_assistant.py     # Voice command parsing + orchestration
├── config.py                    # Central settings/defaults
├── data/                        # SQLite DBs/caches (tasks/calendar/chat history)
└── merged_model/               # Local router model storage (auto-downloaded)
```

---

## Key Abstractions

### `gui/tabs/reading_files.py::ReadingFilesTab`
- **File**: `gui/tabs/reading_files.py`
- **Responsibility**: Load files from disk, show a numbered list, extract content lazily on selection, and display a truncated preview in the UI.
- **Interface**: `read_option(n: int)`, `handle_user_command(text: str)`
- **Lifecycle**: Lives inside the GUI; content extraction happens in a background `threading.Thread` per selection.
- **Used by**: Voice/chat flow via `VoiceAssistant` → `read_file_requested` → `inject_file_and_respond()`.

**Meaning for your feature list**: This is **single-document preview**, and “AI Q&A” is driven by **embedding the full extracted document into a prompt at read time**, not by building a persistent embedding index.

---

### `gui/handlers.py::ChatWorker` (orchestration)
- **File**: `gui/handlers.py`
- **Responsibility**: Route user requests, execute tool functions, and stream final LLM responses into the UI. Also owns the multi-hop research trigger and the file-reading bypass pipeline.
- **Notable methods**:
  - `_is_multihop_request()` keyword gate
  - `_run_multihop_research_with_citations()`
  - `_generate_response_with_context()`
  - `_stream_qwen_response()` streaming chat
  - `inject_file_and_respond()` reads a selected file aloud and injects the document into the prompt, bypassing router.

---

### `core/multi_hop_research.py` (planner + evidence + strict citations)
- **File**: `core/multi_hop_research.py`
- **Responsibility**: Generate multi-hop search queries (planner), gather evidence by running `web_search` tool per sub-query, then build a strict “citations only” synthesis context prompt.
- **Key functions**:
  - `plan_subqueries(...)`
  - `gather_evidence_for_queries(...)`
  - `build_citation_context_prompt(...)`
  - `research_with_citations_context(...)`

**Meaning for your feature list**: This corresponds to “multi-hop research with citations”.

---

### `core/redaction.py::redact_text`
- **File**: `core/redaction.py`
- **Responsibility**: Deterministic regex-based redaction of emails, phone numbers, OpenAI API keys (`sk-...`), generic secret-like key/value pairs, JWT-like strings, and (in “normal/strict”) long hex blobs.
- **Used by**: `gui/handlers.py` (redacts user text and tool context before LLM calls), and multihop final-synthesis prompts.

**Meaning for your feature list**: This corresponds to “Sensitive-data auto-redaction before LLM calls”.

---

### `core/mcp_client.py::MCPClient`
- **File**: `core/mcp_client.py`
- **Responsibility**: Read `~/.plia/mcp.json`, spawn MCP servers over **stdio**, discover tools, cache tool metadata, and synchronously execute tool calls via a background asyncio loop.
- **Integration contract** (used by router/executor):
  - Tool IDs: `<serverId>:<toolName>`
  - Execute result shape: `{success, message, data{tool_id, tool_name, output}}`

**Meaning for your feature list**: MCP exists, but the router “promptable” tool catalog is **hard-limited**:
- `DEFAULT_TOOL_CATALOG_MAX = 35`
- `DEFAULT_TOOL_CATALOG_MAX_CHARS = 1800`
So it is not designed to prompt the model with “500+ tool servers” worth of raw catalog content.

---

### `core/router.py::FunctionGemmaRouter`
- **File**: `core/router.py`
- **Responsibility**: Local function-calling router that decides which function to call (web_search, timers, system info, MCP bridge call, etc.).
- **Notable design**: Strictly **lazy-imports torch/transformers** in `FunctionGemmaRouter.__init__()` to avoid the torch import circularity crash noted in the file.

**Meaning for your feature list**:
- “Smart tool selection / auto-pruning so adding tools doesn't degrade routing” exists **only partially**:
  - MCP side has prompt-time pruning (`get_tool_catalog_text(user_prompt=...)`).
  - Function routing itself is not a large-tool catalog pruning system; it routes among a fixed set of tools in `core/router.py::TOOLS`.

---

### `core/network_tools.py`
- **File**: `core/network_tools.py`
- **Responsibility**: Public IP info, ping, DNS lookup, and a download-based “speed_test” method.
- **Meaning for your feature list**: “Internet speed test” code exists, but **it is not exposed in the routed tool layer** we inspected (`function_executor._network_tools` only supports `public_ip`, `public_ip_info`, `ping`, `dns_lookup`).

---

## Data Flow

1. **User/voice input**
   - Voice: `core/voice_assistant.py` parses commands and emits signals.
   - Text: `gui/tabs/chat.py` → `ChatHandlers.send_message()`.

2. **Spawn worker**
   - `gui/handlers.py::ChatHandlers.send_message()` creates a `QThread` and runs `ChatWorker.process()`.

3. **Special-case multi-hop research**
   - `ChatWorker._is_multihop_request()` checks for keywords like `citations` + `multi-hop/open-jarvis/isair`.
   - If matched: `ChatWorker._run_multihop_research_with_citations()` calls `core/multi_hop_research.py`.

4. **Tool routing & execution**
   - Otherwise: `core/router.py::route_query` selects a function schema.
   - If the function is an action: `core/function_executor.py::FunctionExecutor.execute()` runs it.
   - MCP tool calls: `FunctionExecutor._mcp_tool_call()` calls `core/mcp_client.py::mcp_client.execute()`.

5. **Redaction before LLM calls**
   - Before sending prompts or contexts: `core/redaction.py::redact_text()` is applied in `gui/handlers.py`.

6. **Streaming response**
   - `gui/handlers.py` streams from `POST {ollama_url}/api/chat` with `stream=True`.
   - UI receives chunks and optionally feeds them into TTS via `core/tts.py::SentenceBuffer`.

---

## Non-Obvious Behaviors & Design Decisions

### 1) “Reading Files” is not a RAG index—it's prompt injection at read time
Even though file extraction supports many formats, the system **does not create embeddings or a reusable retrieval index**.
- `ReadingFilesTab` caches extracted content only in memory and shows a truncated preview.
- `ChatHandlers.inject_file_and_respond()` injects the *full* file content into the prompt and bypasses router routing.

**Impact**: It scales poorly for large corpora compared to a true RAG index, and it cannot answer cross-document questions without reloading each document into context.

---

### 2) Multi-hop citations are strict-enforced at the final synthesis stage
`core/multi_hop_research.py` builds a prompt that says every factual claim MUST include `[n]` tokens and that sources must be listed under a `Sources:` section.  
Then `gui/handlers.py` validates citations with `validate_citations()` (range checking only, not claim-to-citation mapping).

**Impact**: Citations are structurally constrained, but the “validation” is not semantic (it won’t detect hallucinated claims with wrong evidence as long as `[n]` tokens are in-range).

---

### 3) Sensitive-data redaction is deterministic and regex-based
`core/redaction.py` avoids any ML redaction and uses conservative regex patterns. It can still over-redact or under-redact edge-case secrets, but it’s predictable and cheap.

**Impact**: Safer prompt payloads, but no guarantee of perfect coverage.

---

### 4) MCP tool selection is prompt-budgeted, not “catalog-wide”
`core/mcp_client.py::get_tool_catalog_text()` prunes the tool list to:
- top-N tools (default 35)
- and truncates by max chars (1800)

**Impact**: If your MCP setup truly has “500+ tool servers”, only a subset will be visible to the router prompt.

---

## Feature Parity: Your Requested Items (Added / Not Added)

Legend:
- **Added** = clearly implemented and wired into core/GUI flow we inspected.
- **Partial** = code exists but routing/exposure is unclear or limited.
- **Not added** = no evidence in codebase searches we performed for those capabilities.
- **Unknown** = not enough evidence during this pass.

### Items from your list

#### Reading Files / RAG / Local files
- **Document indexing + RAG over local files (open-jarvis) — Reading Files tab is single-doc preview, no embedding index.**  
  - **Added?** ✅ **Partial (single-doc only)**  
  - Evidence: `gui/tabs/reading_files.py` loads one file at a time and `inject_file_and_respond()` injects file text into a prompt; no embedding/index code found.

- **Multi-hop research with citations (open-jarvis, isair).**  
  - **Added** ✅  
  - Evidence: `gui/handlers.py::_run_multihop_research_with_citations()` + `core/multi_hop_research.py`.

#### Multi-person conversation tracking & diarisation
- **Multi-person conversation tracking (speaker diarisation) (isair/jarvis).**  
  - **Not added** ❌ (no diarisation hooks found; searches for diar/speaker didn’t hit any implementation)

#### Sensitive-data protection
- **Sensitive-data auto-redaction before LLM calls (isair/jarvis).**  
  - **Added** ✅  
  - Evidence: `core/redaction.py` + usage in `gui/handlers.py` before LLM calls and in multihop final synthesis.

#### MCP / tooling ecosystems
- **MCP client with 500+ tool servers (isair/jarvis) — biggest gap.**  
  - **Partial** ⚠️  
  - Evidence: MCP exists (`core/mcp_client.py`), but tool catalog for prompting is capped (`DEFAULT_TOOL_CATALOG_MAX=35`, max chars 1800). No evidence of designed support for “500+ tools visible at once” in router prompting.

- **Composio integration (isair/jarvis).**  
  - **Not added** ❌ (no Composio references found)

#### Skills marketplace / contributed tools
- **Skills marketplace (agentskills.io, Hermes, OpenClaw — open-jarvis).**  
  - **Not added** ❌ (no marketplace/skills loader references found)

#### Home automation integrations
- **Home Assistant integration (isair/jarvis).**  
  - **Not added** ❌ (no Home Assistant references found)

#### Smart routing / pruning
- **Smart tool selection / auto-pruning so adding tools doesn't degrade routing (isair/jarvis).**  
  - **Partial** ⚠️  
  - Evidence: MCP tool catalog relevance pruning exists in `core/mcp_client.py::get_tool_catalog_text(user_prompt)`.
  - Gap: Function routing is still bounded by the fixed router schema list, and tool catalog visibility is budget-limited (not “unbounded smart pruning”).

#### Scheduled agents / continuous background
- **Morning digest scheduled agent (open-jarvis).**  
  - **Added** ✅  
  - Evidence: `gui/app.py` contains morning digest timer loop (seen via search output) and `core/settings_store.py` defines `morning_digest`.

- **Deep research agent with multi-step planning (open-jarvis).**  
  - **Added (related)** ✅  
  - Evidence: multi-hop research is a planner loop + evidence gathering + strict final synthesis.

- **Continuous monitoring agent (open-jarvis) — long-running background watchers.**  
  - **Unknown / likely partial** ❓  
  - No dedicated “watcher” framework found in the code we inspected. There are modules for email/news/calendar, but no explicit long-running monitoring agent pattern surfaced.

#### Reasoning loop
- **ReAct reasoning loop (open-jarvis).**  
  - **Not added** ❌  
  - Evidence absence: no explicit ReAct loop implementation; “thinking” mode streams reasoning text but is not a structured ReAct action/observation loop.

#### Messaging / social media / geospatial / device I/O
All of the following appeared to be **not added** (no hits in our searches for the relevant keywords and no wiring observed in the inspected router/tool layers):

- **WhatsApp messaging including group chats (BolisettySujith).** ❌
- **Instagram profile/content interaction (BolisettySujith).** ❌
- **Google Maps queries beyond weather lat/lon (GauravSingh).** ❌
- **Internet speed test (BolisettySujith).**  
  - **Partial** ⚠️ Code exists (`core/network_tools.speed_test()`), but not exposed in `FunctionExecutor._network_tools` actions we inspected.
- **QR code generation (BolisettySujith).** ❌
- **Phone-number geolocation lookup (BolisettySujith).** ❌
- **Screen recording with audio (BolisettySujith).** ❌
- **Webcam capture & mobile-camera access (IP cam) (BolisettySujith).** ❌
- **Facial recognition login / authentication (GauravSingh).** ❌
- **Gender-switchable voice persona (Jarvis male / Friday female) (GauravSingh).** ❌ (no persona switching found; only a single configured Piper voice model in `config.py`)
- **Jetson / embedded device packaging (microsoft/JARVIS).** ❌
- **Local trace data → model fine-tuning loop (open-jarvis).** ❌
- **Adaptive tone per context (code/business/wellness) (isair/jarvis).** ❌
- **Location awareness via embedded GeoLite2 DB (isair/jarvis).** ❌

---

## Module Reference (one-liners)

| File | Purpose |
|---|---|
| `gui/tabs/reading_files.py` | File loading + single-doc preview + extraction dispatch |
| `gui/handlers.py` | Orchestration: routing, tool execution, streaming, multi-hop trigger |
| `core/multi_hop_research.py` | Multi-hop planning + evidence gathering + strict citations |
| `core/redaction.py` | Regex-based sensitive data redaction before LLM prompts |
| `core/mcp_client.py` | MCP stdio client: discover tool catalog + execute tool calls |
| `core/router.py` | Local FunctionGemma router: choose which tool/function to call |
| `core/function_executor.py` | Executes routed functions + returns structured results |
| `core/stt.py` | RealTimeSTT with Porcupine wake word + torchaudio mismatch patching |
| `core/voice_assistant.py` | Voice command parsing + emits UI/worker actions |
| `core/network_tools.py` | Public IP, ping, DNS, and speed test helpers |

---

## Suggested Reading Order
1. `gui/handlers.py` — start here to see the end-to-end pipeline and special-case features (multi-hop + file reading bypass + redaction usage).
2. `core/router.py` — see how tool/function routing works and how MCP tool catalogs are injected into prompts.
3. `core/function_executor.py` — see which routed actions actually exist and how results are shaped for the LLM.
4. `core/multi_hop_research.py` — understand the planner/evidence/citation synthesis contract.
5. `core/redaction.py` — confirm what is redacted and where it’s applied.
6. `core/mcp_client.py` — understand MCP config format, discovery, and tool catalog pruning limits.

---

## Quick “What’s added vs not” answer (compressed list)

- ✅ Multi-hop research with citations: **added**
- ✅ Sensitive-data auto-redaction: **added**
- ✅ MCP client bridge: **added (but tool catalog is limited, not 500+ visible)**
- ✅ Morning digest scheduled agent: **added**
- ✅ Desktop agent (VLM-driven control): **present**
- ⚠️ Internet speed test: **code exists**, but **not confirmed as routable/exposed**
- ❌ Local-file embedding index/RAG: **not implemented (single-doc prompt injection only)**
- ❌ Speaker diarisation / multi-person tracking: **not implemented**
- ❌ Composio / Home Assistant / WhatsApp / Instagram / QR / facial recognition / etc.: **not implemented** (no evidence in code inspected/search)
