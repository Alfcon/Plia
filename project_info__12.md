# Plia — Codebase Overview & “Active Agent / Add Agent → Agent List” Guidance

## Summary
Plia is a PySide6 desktop assistant with a “Chat” UI that can either answer directly with an Ollama-hosted Qwen model (optionally through a Gemma “function router”), or execute “action” functions via `core/function_executor.py` (timers, calendar events, web search, desktop control, etc.).  
Separately, it has a UI-driven “agent” layer for user-created custom agents: these live in a JSON-backed `core/agent_registry.py` and are presented in two places:
- **Active Agents** tab (`gui/tabs/agents.py`) — live status + a custom agent “Agent List” card that includes an **Add Agent** button and Run/Edit/Delete.
- **Agent List** tab (`gui/tabs/agent_list.py`) — a compact registry list with Run/Delete, but the **Add Agent** button is currently a placeholder (`pass`) and no “create agent” UI wiring exists.
This document explains what each tab currently does and what a developer needs to change to “move Active Agent and Add Agent to the Agent List Page” effectively.

## Architecture

### Pattern / subsystems
The architecture is a **Qt/PySide GUI application with a thread-per-work UI concurrency model**:
- UI tabs are `QWidget` subclasses under `gui/tabs/`.
- Long-running tasks (LLM streaming, status polling, agent script running) run in background threads (`QThread` / `threading.Thread`) and communicate back to UI using Qt signals.
- Domain state is centralized in:
  - `core/agent_registry.py` for user-created agents
  - `core/multi_agent.py` for Jarvis-style multi-agent runtime snapshot used by the Active Agents tab

### Technology stack (runtime)
- **Language**: Python
- **GUI**: PySide6 + qfluentwidgets (FluentWindow, cards, buttons, navigation)
- **LLMs / models**: Ollama HTTP API from `core/llm.py` / `gui/handlers.py`
- **Concurrency**: `QThread` for UI-safe workers (`ChatWorker`, `AgentStatusThread`, `RunAgentThread`)

### Execution entry point
1. `main.py` configures logging/audio plumbing, starts Ollama if needed, then creates `gui/app.py:MainWindow`.
2. `MainWindow` lazily initializes tab widgets via `LazyTab` when selected.
3. Chat input sends text to `gui/handlers.py:ChatHandlers.send_message()`, which creates a `ChatWorker` (`QThread`) to stream LLM output and/or execute action functions.

## Directory Structure (relevant parts)
```text
project-root/
├── gui/
│   ├── app.py                      — Main window + navigation + lazy tab loader
│   ├── handlers.py                — ChatWorker + UI signal handlers
│   ├── tabs/
│   │   ├── agents.py              — “Active Agents” tab: live system status + multi-agent snapshot + custom agent card (incl. Add Agent)
│   │   └── agent_list.py          — “Agent List” tab: registry list (Run/Delete) + Add button placeholder
│   └── components/               — (UI widgets like toast, thinking expander, etc.)
└── core/
    ├── agent_registry.py         — JSON-backed custom agent CRUD + execution helpers
    ├── multi_agent.py            — Jarvis-style multi-agent runtime snapshot
    └── function_executor.py     — tool/action function dispatch (timers, email, web_search, etc.)
```

## Key Abstractions

### ChatWorker (streaming + intent dispatch)
- **File**: `gui/handlers.py` (class `ChatWorker`)
- **Responsibility**: Orchestrates one user message:
  - Detect “build program/tool/script” intents early (`detect_build_intent` / `build_agent`)
  - Detect “create an agent” intents via `agent_registry.parse_create_intent()` and emits a `create_agent_signal`
  - Detect “run agent X” patterns and executes the agent via `agent_registry`
  - Otherwise routes to the Gemma router and executes action functions or streams Qwen
- **Interface**: `process()`; emits UI signals (`response_chunk`, `toast`, `create_agent_signal`, `agent_result_signal`, etc.)

### AgentsTab (Active Agents page + custom agent management card)
- **File**: `gui/tabs/agents.py` (class `AgentsTab`)
- **Responsibility**:
  - Polls and displays live status for models/services using `AgentStatusThread`
  - Displays multi-agent snapshot (`core/multi_agent.py`)
  - Builds a “Custom Agents / Agent List” card powered by `agent_registry.all_agents()`
  - Owns the **Add Agent** dialog and custom agent row actions (Run / Edit / Delete)
- **Notable methods**:
  - `_build_custom_section()` renders header + “Add Agent” button and list rows
  - `_on_create_agent()` shows `CreateAgentDialog` then calls `agent_registry.create_agent(...)`
  - `_on_run_agent()` runs the selected custom agent using `RunAgentThread` and emits UI output to chat
  - `_on_edit_agent()` opens `AgentEditorWindow`
  - `refresh()` polls status and disables/enables the refresh button

### AgentListTab (registry list sidebar page)
- **File**: `gui/tabs/agent_list.py` (class `AgentListTab`)
- **Responsibility**: Render a compact scrollable list of registry agents (`agent_registry.all_agents()`), with Run and Delete actions.
- **Notable gap**:
  - The tab includes an **Add Agent** button (`self._add_btn`) but `_open_create()` is `pass`, so it does nothing.
  - Rows are `AgentListRow` and only expose Run/Delete (no Edit button), and do not show “live status”.

### AgentRegistry (single source of truth for custom agents)
- **File**: `core/agent_registry.py` (class `AgentRegistry`)
- **Responsibility**:
  - Persists custom agent metadata to `~/.plia_ai/custom_agents.json`
  - Provides CRUD and execution helpers:
    - `create_agent(...)` persists and emits `agents_changed`
    - `delete_agent(name)` persists and emits `agents_changed`
    - `run_agent(...)` calls Ollama `/api/chat` using the stored `prompt`
    - `run_agent_file(...)` launches an agent’s written `.py` script
  - Provides intent parsing: `parse_create_intent(user_text)`
- **Lifecycle**: Singleton at module import (`agent_registry = AgentRegistry()`)

### MultiAgentSystem snapshot
- **File**: `core/multi_agent.py`
- **Responsibility**: Loads role YAMLs from `~/.plia_ai/roles` (Jarvis-style), maintains an in-memory hierarchy, and provides a `snapshot()` used by AgentsTab UI.

## Data Flow (agent-related)
1. User asks to create or run an agent in chat:
   - `ChatWorker.process()` detects intent using `agent_registry.parse_create_intent()` or `_detect_run_agent_intent()`.
2. For create-intent:
   - `ChatWorker` emits `create_agent_signal(intent_dict)`
   - `ChatHandlers` receives `_on_create_agent_from_chat(prefill)` and *tries* to navigate to an Agents UI dialog.
3. For run-intent:
   - `ChatWorker` calls `agent_registry.run_agent(...)` (LLM-only agents) or `agent_registry.run_agent_file(...)` (file-backed agents).
4. UI execution for custom agents (from AgentsTab):
   - `AgentsTab` uses `RunAgentThread` and then updates its own UI card via `_build_custom_section()` after completion.
5. Registry change:
   - `AgentRegistry.agents_changed` triggers `AgentsTab._rebuild_custom_section()` and `AgentListTab.refresh()`.

## Non-Obvious Behaviors & Design Decisions (important for this task)

### 1) “Agent creation from chat” is currently wired to AgentsTab by name, but MainWindow doesn’t expose those attributes
`ChatHandlers._on_create_agent_from_chat()` attempts:
- `mw.navigate_to_agents()`
- `mw.agents_tab.create_agent_from_chat(prefill)`

But `gui/app.py` does **not** define `navigate_to_agents()` or `agents_tab` (it only holds `self.agents_lazy` and never assigns `self.agents_tab` in `_on_tab_changed`).

**Meaning for your requested change:** if you “move Add Agent to Agent List page”, you’ll likely also need to fix the UI navigation/dialog plumbing so chat-driven agent creation actually works on the new target tab.

### 2) Active Agents tab is doing two jobs: live system monitoring + agent CRUD UI
`AgentsTab` mixes:
- runtime status polling (`AgentStatusThread`)
- agent registry CRUD and dialogs
- multi-agent snapshot visualization

**Meaning:** if “Active Agent” (live status) should move to Agent List page, you are effectively merging two tabs’ responsibilities, and AgentListTab will need to grow beyond just a registry list.

### 3) Agent List tab currently has an Add button but it’s deliberately a stub
In `gui/tabs/agent_list.py`, `_open_create()` is `pass`. This looks intentional as part of incremental UI rollout, but it makes “move Add Agent to Agent List page” a concrete implementation task.

## What “move Active Agent and Add Agent to the Agent List Page” likely means in this codebase

Because there are two distinct tabs and only one of them has both **live status** and **Add Agent** UI, there are two plausible interpretations:

### Interpretation A (most likely): move *custom agent management* (Add Agent + list + controls) into Agent List tab
- **Move** the **Add Agent** button and custom agent rows (Run/Edit/Delete) from `AgentsTab._build_custom_section()` into `AgentListTab`.
- Keep `AgentsTab` only for “live system status” (router/llm/voice/stt/tts/etc.) and possibly multi-agent snapshot.
- **Implementation consequence**:
  - `AgentListTab` needs to import/use `CreateAgentDialog` and `RunAgentDialog` (currently inside `agents.py`) or refactor those dialogs into a shared module.
  - `AgentListTab` needs an Edit path using `AgentEditorWindow` if you truly want parity with Active Agents’ Edit button.

### Interpretation B: move the *entire Active Agents UI* (“Active Agent”) into Agent List tab
- Replace AgentListTab with (or embed) what AgentsTab currently renders: status sections + multi-agent snapshot + custom agent card.
- **Implementation consequence**:
  - `AgentListTab` becomes a clone/adapter of `AgentsTab`.
  - There must still be a clear “Add Agent” entry point and correct signal wiring from chat.

Either way, you must decide how much of `AgentsTab` moves, because right now:
- “Add Agent” exists in `AgentsTab`
- “Agent List tab” is missing both the creation dialog and the live-status presentation

## Suggested Implementation Targets (files a developer must edit)

### If choosing Interpretation A (custom agent management into Agent List)
1. **`gui/tabs/agent_list.py`**
   - Implement `_open_create()` to open the same `CreateAgentDialog` used in `agents.py` (or refactor dialog code to shared location).
   - Add Edit support:
     - Either add an Edit button to `AgentListRow`, or implement Edit elsewhere in the tab UI.
     - Route Edit to `AgentEditorWindow` in `gui/tabs/agent_editor.py`.
   - Update row rendering to match actions currently in `CustomAgentRow` (Run/Delete/Edit).
2. **`gui/tabs/agents.py`**
   - Remove (or hide) the “Custom Agents” card inside `_build_custom_section()` if it should no longer live on Active Agents tab.
   - Potentially keep only status + multi-agent snapshot.
3. **`gui/handlers.py` + `gui/app.py`**
   - Fix chat-driven agent creation routing:
     - Ensure `ChatHandlers._on_create_agent_from_chat` can navigate to the correct tab and invoke the correct dialog opener.
     - The current method expects `main_window.navigate_to_agents` and `main_window.agents_tab`, but neither exists.

### If choosing Interpretation B (merge whole Active Agents into Agent List)
1. **`gui/tabs/agent_list.py`**
   - Replace its UI with the `AgentsTab` layout/logic, or instantiate `AgentsTab` content inside `AgentListTab`.
   - Ensure `agents_changed` refresh calls still work for registry-driven updates.
2. **`gui/app.py`**
   - Decide whether to keep “Active Agents” navigation item. If you remove it, you must ensure nothing else depends on it (voice refresh currently calls `agents_lazy.get_widget().refresh()`).
3. **`gui/tabs/agents.py`**
   - Consider removing redundant code or keeping it as thin wrapper.

## Non-Obvious Risks (watch-outs)
- **Dialog code reuse**: `CreateAgentDialog`, `RunAgentDialog` live inside `gui/tabs/agents.py`. If you implement creation in `agent_list.py`, you’ll either duplicate code or refactor them to avoid divergence.
- **Signal wiring**: Chat-to-UI agent creation is currently fragile because MainWindow doesn’t expose expected attributes (`agents_tab`, `navigate_to_agents`).
- **Action parity**: Active Agents uses `CustomAgentRow` with Edit; AgentListTab’s `AgentListRow` has no Edit. “Move Add Agent” alone won’t fully satisfy users if they also expect Edit parity.

## Suggested Reading Order (for implementing the move)
1. `gui/tabs/agents.py` — understand current Add Agent + custom agent actions (Run/Edit/Delete) and dialogs
2. `gui/tabs/agent_list.py` — understand current list presentation and the stubbed Add button
3. `gui/handlers.py` — understand how chat intents trigger agent creation and where it currently fails
4. `gui/app.py` — understand lazy tab initialization and which attributes are (or aren’t) exposed to handlers
5. `core/agent_registry.py` — confirm registry fields expected by UI rows and execution logic

## Task-specific TODO checklist (for your requested change)

- [ ] Decide whether “Active Agent” means:
  - [ ] only “Custom agent management” (Add/Run/Edit/Delete), or
  - [ ] also the live status + multi-agent snapshot sections
- [ ] Move **Add Agent** UI into `gui/tabs/agent_list.py` (implement `_open_create()`)
- [ ] Ensure “Run” works the same way as Active Agents (including internet-search runtime args)
- [ ] Decide whether “Edit” should also move:
  - [ ] If yes: add Edit controls to `AgentListRow` and route to `AgentEditorWindow`
- [ ] Fix chat-driven agent creation plumbing:
  - [ ] Expose a callable on MainWindow that navigates to the target tab
  - [ ] Expose a reference (e.g., `self.agent_list_tab` / `self.agents_tab`) or adapt `ChatHandlers._on_create_agent_from_chat`
- [ ] Validate voice command refresh logic if you repurpose/move the Active Agents tab
- [ ] Remove/disable now-redundant “Add Agent” and/or custom agent card from the old tab to avoid duplicate controls
