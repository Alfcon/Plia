# Plia — Codebase Overview & README/requirements Sync Notes

## Summary
Plia (“Pocket Local Intelligent Assistant”) is a fully-local, privacy-focused Python desktop assistant with a Fluent/Qt GUI and a local LLM pipeline (router intent classification + Ollama-resident responder model + Piper TTS + RealTimeSTT wake-word + STT). The backend lives in `core/` and is orchestrated by `main.py` (starts logging, optionally starts Ollama, then launches the Qt `MainWindow`). A key architectural feature is the **FunctionGemma “router”** (`core/router.py`), which lazily imports PyTorch/Transformers to avoid startup crashes, then outputs a `call:<function>` response that the app maps to concrete tool executors.

This exploration specifically focused on **what a developer needs to know to update `README.md` and `requirements.txt` accurately**, because the current documentation and dependency manifests have drift.

---

## Architecture

### Primary pattern
A **layered / service-oriented pipeline**:
- `main.py` boots runtime (logging, Ollama availability, GUI)
- `core/router.py` classifies user prompts into one of many “function” tool schemas (Gemma router)
- `core/function_executor.py` executes the selected tool by calling the relevant manager(s)
- `core/llm.py` streams responses from Ollama
- `core/stt.py` + `core/voice_assistant.py` provide wake-word + speech input and run the router/LLM/TTS pipeline
- Optional integrations (MCP, calendar sync, desktop automation, web search, etc.) plug in behind the executor layer.

### Major subsystems (and how they connect)
- **Boot & environment**
  - `main.py` configures logging *before any third-party imports* to prevent stray logs and then ensures ALSA plugin behavior on Linux.
  - It uses `core/ollama_paths.py` (invoked in `main.py`) to align `OLLAMA_MODELS` between GUI and any spawned `ollama serve`.
- **Routing / tool selection**
  - `core/router.py` defines tool schemas (via `transformers.utils.get_json_schema`) and routes prompts using `FunctionGemmaRouter`.
  - `FunctionGemmaRouter.__init__()` lazily imports torch/transformers and downloads/ensures the router model from HF into `merged_model/`.
- **Execution**
  - `core/function_executor.py` exposes a `FunctionExecutor` with concrete implementations (timers, calendar, tasks, web search, system control, clipboard, file ops, etc.).
  - `router.py` also provides a generic bridge tool: `mcp_tool_call` for Model Context Protocol.
- **Speech pipeline**
  - `core/stt.py` wraps RealtimeSTT + wake-word configuration and also patches torchaudio if broken.
  - `core/voice_assistant.py` connects wake-word and speech input to `_process_query()` and streams the LLM response, then triggers `core/tts.py` (Piper) for speech output.
- **GUI**
  - `gui/app.py` hosts the main window; `gui/handlers.py` handles chat streaming / UI orchestration.

### Technology stack
- Language/runtime: **Python 3.11+**
- GUI: **PySide6** + **QFluentWidgets**
- Local AI:
  - Router: HF `nlouis/pocket-ai-router` via **Transformers + Torch**
  - Responder model: streamed from **Ollama** via `core/llm.py`
  - STT/wake word: **RealtimeSTT** (RealTimeSTT + Piper TTS + Porcupine optional)
  - TTS: **Piper** via `piper-tts`
- Integrations: DuckDuckGo via `ddgs`, MCP via `mcp` SDK, RSS via `feedparser`, etc.

---

## Directory Structure (annotated)
```
project-root/
├── main.py                     # runtime entry: logging + Ollama start + Qt app
├── config.py                   # all user-tunable constants (models, wake word, routing params)
├── requirements.txt           # full dependency manifest
├── pyproject.toml             # package metadata + a small dependency subset
├── README.md                  # installation + architecture + troubleshooting
├── core/
│   ├── router.py              # FunctionGemmaRouter + tool schema list + mcp_tool_call bridge
│   ├── function_executor.py  # tool execution logic
│   ├── llm.py                 # Ollama streaming interface + router/responder/voice loading helpers
│   ├── voice_assistant.py    # wake word → router → llm → tts pipeline
│   ├── stt.py                 # RealtimeSTT integration + torchaudio patching
│   ├── tts.py                 # Piper TTS engine and model downloading
│   ├── mcp_client.py         # MCP server discovery + tool execution (invoked by router)
│   └── ... (many managers)
├── gui/
│   ├── app.py                 # main window
│   ├── handlers.py            # streaming / UI handlers
│   └── tabs/                 # dashboard/chat/planner/etc.
├── merged_model/             # router model cache (downloaded from HF if missing)
├── log/                      # runtime logs (created by main.py)
└── data/                     # sqlite stores + caches
```

---

## Key Abstractions (high impact for doc/deps updates)

### FunctionGemmaRouter
- **File**: `core/router.py` (main module; router class defined near bottom)
- **Responsibility**: Turns user prompts into a `call:<function>{...}` style response using a local Gemma router model, then extracts:
  - `func_name` from `VALID_FUNCTIONS`
  - `args` from the router’s custom argument encoding
- **Interface**:
  - `FunctionGemmaRouter.route(user_prompt) -> (function_name, args_dict)`
  - `FunctionGemmaRouter.route_with_timing(user_prompt) -> ((function_name, args), elapsed_seconds)`
- **Lifecycle**:
  - Constructed on demand inside the app (or `core/llm.py` preload helpers).
  - Internally keeps `self.tokenizer`, `self.model`, and a cached `torch` reference.
- **Used by**:
  - `core/voice_assistant.py` and chat handlers: to choose which executor function to run.
  - `router.py` also uses `core/mcp_client.py` opportunistically:
    - In `route()`, it checks `mcp_client.is_ready()` and if ready, appends MCP tool catalog text to `dev_content`.

### MCPClient
- **File**: `core/mcp_client.py` (definition list present; not fully read in this session)
- **Responsibility**: Discovers MCP servers and exposes a tool catalog to the router, then executes MCP tools when the router outputs `mcp_tool_call`.
- **Key coupling points**:
  - `core/router.py` imports `core.mcp_client` inside `route()` only when needed and tolerates failure with `try/except`.

### Requirements manifest vs. documentation (the drift)
This section is *not* an abstraction, but it’s the most actionable “developer needs to know” area for this task.

- `requirements.txt` contains dependency declarations that the current `README.md` does not fully describe (notably **MCP**).
- `README.md` contains at least one incorrect statement about install behavior (GPU setup / “torch lines commented out”), which conflicts with how `requirements.txt` is currently written.

---

## Data Flow (router → executor, plus MCP bridge)

1. User speaks or types a command
   - Voice: `core/voice_assistant.py` receives speech text and calls `_process_query(user_text)`
   - Chat: UI handlers feed user text to the same pipeline (via `core/llm.py` / executor helpers)
2. Intent routing
   - `FunctionGemmaRouter.route(user_prompt)` builds a developer message (`SYSTEM_MSG` + optionally MCP tool catalog), applies the tokenizer chat template with `tools=TOOLS`, generates router output, and parses out:
     - `func_name`
     - `args`
3. Function execution
   - `core/function_executor.py` executes `func_name` using `params` and returns a structured result dict.
4. LLM response + TTS
   - `core/llm.py` streams responder output from Ollama
   - `core/tts.py` speaks output through Piper (when voice enabled)
5. Optional MCP tool use
   - If MCP is available, `router.py` appends MCP catalog text to the router prompt.
   - If the router emits `mcp_tool_call`, `FunctionExecutor._mcp_tool_call()` (see function list) executes the referenced MCP tool.

---

## Non-Obvious Behaviors & Design Decisions (relevant to documentation accuracy)

### 1) Lazy torch imports are intentional (and brittle to “doc edits”)
`core/router.py` explicitly avoids torch/transformers imports at module import time. Any documentation that says “torch is only lazily imported” is correct, but the installation docs must still accurately describe **what gets installed** (because lazy import does not mean “optional dependencies”).

### 2) Logging is configured before 3rd-party imports to avoid stray log files
`main.py` configures logging early, including redirecting the `realtimestt` logger into `log/realtimesst.log` and deleting the occasional stray `realtimesst.log` in the project root. This is a subtle “why does this file exist?” behavior that belongs in developer docs—but also affects troubleshooting sections.

### 3) MCP integration is present in code, but absent from README search
`core/router.py` includes `mcp_tool_call()` in `TOOLS` and checks `mcp_client.is_ready()` during routing.
However, a text search in `README.md` for “mcp” returned no hits in this exploration session—meaning the docs likely under-explain MCP even though the dependency exists in `requirements.txt`.

---

## README.md ↔ requirements.txt drift discovered (for this task)

### A) README missing MCP documentation
- **Code evidence**:
  - `core/router.py` includes an MCP bridge tool: `mcp_tool_call(tool_id, arguments="{}")`
  - `core/router.py` dynamically loads MCP tool catalog text when `mcp_client.is_ready()`
  - `requirements.txt` includes `mcp>=1.0.0`
- **Documentation gap**:
  - `README.md` did not contain “mcp” (case-insensitive search for “mcp” in this session returned no matches).

**Impact**: A developer or user enabling MCP servers will not find relevant setup instructions or where MCP is described.

**Recommended README change** (example targets):
- Add an “MCP integration (optional)” subsection to either:
  - “Complete Dependencies Reference” (add `mcp>=1.0.0`)
  - or “Automatic tool integrations / Advanced features”
- Mention that MCP tool discovery is routed into the FunctionGemma router via `mcp_client` catalog text.

### B) README GPU setup note conflicts with current requirements behavior
- **README Quick Start** states:
  - “requirements.txt torch lines are commented out by default, so CPU PyTorch will be installed automatically…”
- **requirements.txt currently shows**:
  - `--extra-index-url .../cu124` is active (not commented)
  - `torch>=2.6.0` and `torchaudio>=2.6.0` are active (not commented)

**Impact**: The documentation is likely inaccurate. A CPU-only user could fail or pull a CUDA-specific build depending on wheel resolution, because the file currently *forces* the CUDA index in all installs.

**Recommended README change**:
- Replace the claim about torch lines being commented out with instructions that align to the top-of-file header in `requirements.txt`:
  - For CPU-only: remove `--extra-index-url https://download.pytorch.org/whl/cu124`
  - and remove or pin `torch/torchaudio` lines so pip resolves CPU wheels via transformers.

### C) requirements.txt header says “OpenAI package only required …”
- `requirements.txt` includes `openai>=2.0.0` **uncommented** (so it will always install).
- README says OpenAI is “optional—only required for Agent Builder agents that use GPT-4o”, and also says packages are included in `requirements.txt`.

**Impact**: This may be internally consistent at a “usage requires a key” level, but is slightly confusing. Decide whether OpenAI should remain an always-installed dependency, or be commented out by default.

**Recommended requirements/doc decision**:
- If “always install” is desired: keep as-is but adjust README wording to “installed by default; key only needed for GPT-4o agent runs”.
- If “truly optional” is desired: comment out `openai>=2.0.0` and update README accordingly.

---

## Module Reference (most relevant for doc/deps edits)
| File | Purpose |
|---|---|
| `README.md` | User-facing installation + dependency reference + architecture & troubleshooting |
| `requirements.txt` | Dependency manifest; contains an active CUDA wheel index and includes `mcp>=1.0.0` |
| `core/router.py` | Tool schema list; includes `mcp_tool_call` and optional MCP catalog injection |
| `core/mcp_client.py` | MCP server discovery/tool execution (enables the router bridge) |
| `main.py` | Starts Ollama and configures logging (important for troubleshooting docs) |
| `config.py` | Defines responder model and wake word/TTS/STT parameters |

---

## Suggested Reading Order (to safely update docs)
1. `requirements.txt` — read the top comments; they currently act like “documentation as source of truth” for optionality
2. `README.md` — locate the install and “Complete Dependencies Reference” sections and align them with `requirements.txt`
3. `core/router.py` — confirm how MCP is wired into routing so README instructions don’t mislead
4. `core/mcp_client.py` — verify what “MCP readiness” means operationally (where servers live, config keys, etc.)

---

## Suggested “Act Mode” change checklist (for updating README.md and requirements.txt)

- [ ] Fix README GPU setup statement to match `requirements.txt` behavior (CUDA index is active + torch lines are not commented)
- [ ] Add MCP to README documentation (dependencies table and/or new “MCP integration” subsection), matching `mcp_tool_call` routing behavior
- [ ] Decide whether OpenAI is “installed by default” vs “optional dependency”
  - [ ] If optional: comment out `openai>=2.0.0` in `requirements.txt` and update README accordingly
  - [ ] If always installed: adjust README phrasing to “installed; API key only needed when opting into GPT-4o”
- [ ] Validate README installation commands (CPU Linux vs Windows vs GPU) against the actual pip resolution strategy described in `requirements.txt` headers
