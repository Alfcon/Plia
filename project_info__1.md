# Plia — Codebase Overview & “Multi-hop research with citations” implementation guide

## Summary
Plia is a **local, privacy-focused desktop assistant** with a **Qt (PySide6) GUI**, voice pipeline (RealtimeSTT + Piper TTS), and an **LLM/router-based orchestration** where user messages are classified by a **local FunctionGemma router** and executed by a central **FunctionExecutor**. Web search currently works as a **single-step** flow: the router routes to `web_search`, the executor fetches results (DuckDuckGo via `ddgs`/fallback), and the chat worker asks Qwen (via Ollama) to synthesize an answer using the returned snippets/URLs. There is **no existing multi-hop planner loop** and **no citation formatting layer**—citations would need to be added to the reasoning/synthesis step and to the data plumbing between search iterations and final synthesis.

## Architecture

### Primary pattern
**Router → FunctionExecutor → LLM synthesis (with streaming)** plus a **Qt-threaded worker** for background generation.

### Major subsystems
- **GUI / interaction**
  - `gui/app.py`, `gui/handlers.py`, and tab widgets drive user input, show streaming output, and show web search results in a floating panel.
- **Intent routing**
  - `core/router.py` contains `FunctionGemmaRouter`, a local fine-tuned model that emits a function name + arguments in a custom `call:<func>{...}` format.
- **Function execution**
  - `core/function_executor.py` executes the routed function: timers, alarms, calendar ops, notes, and importantly `web_search`.
- **LLM chat + streaming**
  - `gui/handlers.py`’s `ChatWorker` streams responses from Ollama (`/api/chat`) and updates the UI / TTS / history.
- **Custom agent infrastructure**
  - `core/agent_builder.py` and `core/agent_registry.py` allow creating scripts dynamically, but this feature request targets the core “web_search + synthesis” pipeline rather than the agent builder.

### Technology stack
- Python 3.11+
- GUI: **PySide6** + **QFluentWidgets**
- Local LLM runtime: **Ollama** HTTP API (`/api/chat`, streaming)
- Intent router: **Transformers** + **HF model** (`nlouis/pocket-ai-router`) loaded locally with lazy imports to avoid torch import issues
- Web search: **ddgs** (DuckDuckGo) with a fallback import
- Persistence: SQLite for chat history + tasks; JSON registry for custom agents

### Execution entry point
- `main.py` starts Ollama if missing, sets up Qt, then launches `gui/app.py` where the chat worker is triggered.
- For a chat request, execution path is:
  1. UI sends text → `gui/handlers.py:ChatHandlers.send_message()`
  2. Background `ChatWorker.process()` runs:
     - optional build-agent / custom-agent handling
     - router call: `core/llm.py:route_query()`
     - function execution: `core/function_executor.py:executor.execute()`
     - synthesis: `ChatWorker._generate_response_with_context()` streams via Ollama

## Directory Structure (annotated)
```text
project-root/
├─ core/
│  ├─ router.py                 # FunctionGemmaRouter (intent classification)
│  ├─ llm.py                    # router wrapper + Ollama streaming payload helpers
│  ├─ function_executor.py     # executes routed actions; includes web_search
│  ├─ agent_builder.py         # LLM-generated “programmable” agent scripts
│  ├─ agent_registry.py        # stores custom agents in ~/.plia_ai/custom_agents.json
│  ├─ history.py               # SQLite chat session/message storage
│  ├─ tasks.py                 # SQLite task manager
│  ├─ news.py                  # RSS-based news briefing + optional LLM curation
│  ├─ network_tools.py         # public IP, ping, DNS tools
│  └─ ... (calendar, weather, STT, TTS, desktop automation, etc.)
├─ gui/
│  ├─ handlers.py             # ChatWorker streaming, function-result context injection
│  ├─ app.py                  # main Qt window
│  ├─ tabs/                   # Chat, Planner, Agents, etc.
│  └─ components/
│     ├─ search_browser.py   # floating web search results panel
│     └─ ... (message bubbles, thinking expander, etc.)
├─ main.py                     # program entry point + Ollama bootstrap
├─ config.py                   # central config (model names, URLs, etc.)
└─ ... (data/, log/, merged_model/)
```

## Key Abstractions

### 1) `FunctionGemmaRouter` (`core/router.py`)
- **File**: `core/router.py`
- **Responsibility**: Locally classifies user prompts into a *function* plus extracted arguments.
- **Interface**:
  - `route(user_prompt) -> (func_name, args)`
  - `route_with_timing(user_prompt) -> ((func_name, args), elapsed_seconds)`
- **Lifecycle**:
  - Lazy loaded via `core/llm.py:route_query()` on first use.
- **Used by**:
  - `core/llm.py` (route_query)
  - ultimately `gui/handlers.py` (via `route_query()`)

### 2) `FunctionExecutor` (`core/function_executor.py`)
- **File**: `core/function_executor.py`
- **Responsibility**: Execute the routed function and return structured result:
  - `{ "success": bool, "message": str, "data": Any }`
- **Interface**:
  - `execute(func_name, params) -> dict`
- **Important behavior**:
  - `_web_search(params)` returns:
    - `{"query": ..., "results":[{"title","body","url"}, ...]}`.
- **Used by**:
  - `gui/handlers.py:ChatWorker.process()` for action functions

### 3) `ChatWorker` (`gui/handlers.py`)
- **File**: `gui/handlers.py`
- **Responsibility**: End-to-end orchestration for a single user message:
  - bypass routing for file injection
  - route prompt (unless bypass)
  - execute routed function(s)
  - synthesize final response with Qwen streaming from Ollama
  - update UI + optionally queue TTS + persist to history
- **Interface**:
  - `process()` (Qt worker thread entry)
  - `_generate_response_with_context(func_name, result, enable_thinking=False)` (builds context prompt and streams)
- **Key integration point for multi-hop research**:
  - In the current code, “web_search” is **single-step** and synthesized once.
  - Multi-hop would require extending this function to run:
    - planner loop (N queries)
    - multiple search calls
    - iterative evidence collection
    - final synthesis with citations.

### 4) `SearchBrowserWindow` (`gui/components/search_browser.py`)
- **File**: `gui/components/search_browser.py`
- **Responsibility**: UI-only floating panel for showing search results and allowing the user to navigate/open them.
- **Used by**:
  - `gui/handlers.py` uses it via signals:
    - `search_results_ready(query, results)` to populate it.
- **Observation for citations**:
  - This component does not manage citations; it only shows title/snippet/url lists.
  - Citations formatting must be handled in chat synthesis output (Markdown links or `[n]` markers).

### 5) `AgentBuilder` / `AgentRegistry` (`core/agent_builder.py`, `core/agent_registry.py`)
- **Files**: `core/agent_builder.py`, `core/agent_registry.py`
- **Responsibility**:
  - Create and register custom Python scripts that can run standalone or be executed from the UI.
- **Relevance**:
  - Not directly used for multi-hop research citations in core chat; however, multi-hop could also be built as an “internet_search” custom agent in future.

## Data Flow (current web_search flow)
1. User message → `gui/handlers.py:ChatHandlers.send_message()`
2. `ChatWorker.process()`:
   - router classification: `core/llm.py:route_query() -> func_name, params`
   - for `web_search`:
     - emit `search_start(query)`
     - execute search: `core/function_executor.py:executor.execute("web_search", params)`
     - emit `search_end()`
     - emit `search_results_ready(query, results)` to UI
3. `ChatWorker._generate_response_with_context()`:
   - If `web_search` succeeded, constructs a context block:
     - lists each result `title`, `body` snippet (truncated to 300 chars), and `URL`
     - instructs model: “Include relevant URLs in your response using markdown link format [text](url).”
   - streams Ollama `/api/chat` response tokens to the UI and TTS.

## What’s missing for “multi-hop research with citations”
Based on the current code paths:

1. **No planner loop**
   - There is no mechanism to:
     - generate N follow-up search queries
     - issue them sequentially
     - aggregate evidence across hops before final synthesis.
2. **No citation extraction/numbering layer**
   - The current instruction is “Include relevant URLs…”
   - There is no enforced policy:
     - “Every factual claim must map to a source”
     - or “use [1], [2] markers matching a provided bibliography”
3. **No evidence store**
   - Search results are placed into a prompt context as plain text, but they are not structured into a graph:
     - {query -> results -> selected evidence -> cited evidence}
4. **No multi-pass synthesis**
   - The model is called once after the single search.

## Proposed implementation plan (Act Mode guidance)
To implement the requested feature (open-jarvis / isair style) in this repo effectively, you would extend the chat synthesis path in `gui/handlers.py` (or factor out a new “research engine” module under `core/`):

### A) Introduce a “multi-hop research” mode in function routing/execution
Two approaches:
1. **New routed function**: Add a new router function name (e.g., `multi_hop_research`) and a matching executor handler that:
   - runs the planner loop and final synthesis.
2. **LLM-driven within ChatWorker**:
   - keep router `web_search`, but detect a “research intent” (or a `research_with_citations` flag) and then run a planner loop before the final answer.

Given the current router config (`config.py`) is already a tool-function schema list, adding a new function may require:
- updating `config.FUNCTIONS` and `core/router.py:VALID_FUNCTIONS` and its tool schemas
- adding execution logic in `core/function_executor.py`
- updating `gui/handlers.py` action dispatch list.

### B) Implement planner loop (N queries)
Inside the research function:
1. Call the model to generate **N sub-queries** based on the user question.
2. For i in 1..N:
   - call existing `executor.execute("web_search", {"query": sub_query})`
   - normalize results: keep `title/body/url`
   - store a structured evidence list:
     - `evidence.append({ "query": sub_query, "idx":..., "url":..., "title":..., "snippet":... })`

### C) Add source selection and citation numbering
Before final synthesis:
- either ask the model to select “the best sources” and output a mapping:
  - `claim -> [source_number]`
- or use heuristic:
  - take top-K search snippets per query
  - ask the model to rewrite the answer and cite each paragraph with `[n]` markers.

To satisfy “synthesises with [1] source citations”:
- Build a canonical bibliography like:
  - `[1] Title — URL`
  - `[2] ...`
- Then instruct synthesis:
  - “Use citations as `[n]` next to each sentence/claim.”
  - “Do not invent sources; citations must exist in the bibliography.”

### D) UI/UX integration
- The SearchBrowser panel is currently designed for a single query’s results.
- For multi-hop:
  - either:
    - only show the first hop in the panel
    - or extend UI to show a combined “hop X results”
  - still, the final answer citations must appear in the chat bubble.

### E) Performance & token budgeting
This repo already sets Ollama `num_ctx` to 4096 and `num_predict` to 2048 in chat streaming options.
For multi-hop:
- You must truncate/compact evidence (snippets are already truncated).
- You must decide a max total evidence entries (e.g., 20–40) and a max total prompt size.
- Consider sending evidence incrementally per hop to avoid prompt explosion.

## Module Reference (what to read to implement)
| File | Purpose |
|---|---|
| `gui/handlers.py` | Where to integrate the planner loop + final synthesis and to format citations in the final output. |
| `core/function_executor.py` | Where multi-hop will reuse the existing `web_search` result fetch logic. |
| `core/router.py` | If you add a dedicated router function name for multi-hop research. |
| `core/llm.py` | If you adjust routing behavior or bypass routing flags. |
| `gui/components/search_browser.py` | UI constraints for showing multi-hop results. |

## Suggested Reading Order
1. `gui/handlers.py:ChatWorker.process()` and `_generate_response_with_context()` — understand current single-step web_search synthesis.
2. `core/function_executor.py:_web_search()` — understand the shape of search results for evidence.
3. `core/router.py` + `config.py:FUNTIONS` — understand how to add/route a new function if needed.
4. `gui/components/search_browser.py` — understand UI expectations (single query / pagination).
5. `core/llm.py` — check how router bypasses and function mapping currently works.

## Non-obvious behaviors/design decisions affecting this feature
- **The “web_search” function result context is hand-built in ChatWorker**:
  - Multi-hop must either reuse or replace that context construction.
- **Prompt instruction currently asks for markdown links, not `[n]` citations**:
  - You’d need to adjust the instruction to enforce `[n]` style and include an explicit bibliography block.
- **Threading/UI updates are coupled to generation streaming**:
  - Long planner loops must still update status signals (`self.status.emit(...)`) to keep UX responsive.

## Concrete acceptance criteria for “Multi-hop research with citations”
When implemented, a developer should be able to verify:
- For a user query like “Multi-hop research with citations about X”:
  - The system generates N sub-queries (planner loop).
  - It performs N web searches (or equivalent hops).
  - Final answer includes citations in the form `[1]`, `[2]`, etc.
  - A bibliography appears at the end mapping each `[n]` to a real URL that was returned by search.
  - Citations are not fabricated.

## Notes on feasibility with current architecture
This can be added without rewriting the entire system:
- Multi-hop evidence gathering can be built by orchestrating existing `web_search` calls.
- Citation formatting can be done purely in the final synthesis prompt in `_generate_response_with_context()` (no need to change UI rendering beyond allowing Markdown).
