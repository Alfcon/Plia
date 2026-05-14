# Plia Multi-Agent System — Design Spec

**Date:** 2026-05-14
**Status:** Design approved, awaiting implementation plan
**Approach:** Build on `core/multi_agent.py` (Jarvis-style `MultiAgentSystem`)

## Goal

Let a user say or type "create an agent that does X" and have Plia create a live, scheduled or on-demand worker that performs that task on its own and reports results back via the user's chosen channel. The system reuses Plia's existing dormant `MultiAgentSystem` as the foundation.

## Scope (whole system)

Implementation will be sliced into phases (handled by the implementation plan), but the spec covers the full target architecture.

In scope:
- Voice + chat intent detection for agent creation
- A creation wizard that asks: trigger, cadence/quota, persistence, notification channel
- Two execution backends — generated Python script, LLM tool-loop — chosen automatically per agent
- Cron-like scheduler with quota and on-demand modes
- Per-agent persistence across Plia restarts (user choice at creation)
- Active Agents tab controls (Run now, Pause, Resume, Stop, Edit, Delete, History)
- Reporting to (always) Active Agents history plus one of: TTS / toast + dashboard card / communication log

Out of scope (explicit non-goals):
- Real Ollama / LLM response testing — stubbed in tests
- Parent/child agent delegation UI (the underlying hierarchy supports it, but the wizard doesn't expose it in v1)
- Long-term agent memory beyond last-run summary (script agents may self-manage; tool-loop agents get last summary only)

## Architecture

```
User (voice OR chat)
    │  "Create an agent that watches GitHub for related projects"
    ▼
Intent detector (voice intercept in voice_assistant.py + existing
                 detect_build_intent / parse_create_intent in handlers.py)
    │
    ▼
CreationPipeline  (core/agent_creator.py — new)
  Wizard Q&A:   trigger → cadence/quota → persistence → notify
  Silent steps: classify_executor, pick_tools
    │
    ├── writes RoleDefinition YAML to ~/.plia_ai/roles/<slug>.yml
    └── writes AgentState entry to ~/.plia_ai/agent_state.json
    │
    ▼
PersistentStore  (core/agent_state.py — new)
  Loaded on Plia startup → re-arms scheduler for persistent agents
    │
    ▼
Scheduler  (core/agent_scheduler.py — new)
  QTimer-based; arms scheduled & quota agents; on_demand never fires
  on each tick → AgentTaskManager.launch(... runner=...)
    │
    ▼
AgentTaskManager (already exists in multi_agent.py)
  Spawns one thread per agent run; tracks running/completed/failed
    │
    ├── runner = script_executor       (core/executors/script_executor.py — new)
    └── runner = tool_loop_executor    (core/executors/tool_loop_executor.py — new)
    │
    ▼
ResultDispatcher  (core/agent_reporting.py — new)
  ALWAYS: append to AgentState.history (Active Agents tab refresh)
  PLUS one of: TTS / toast + dashboard card / communication log
```

Key principles:
- `MultiAgentSystem` is the foundation. New agents are `AgentInstance`s in its `AgentHierarchy`. Their `RoleDefinition`s persist as YAML so `discover_roles()` loads them on startup.
- Roles describe **what the agent is**; state describes **how it's currently running**. They live in separate files.
- The existing `AgentTaskManager` stays in charge of execution; the new scheduler just calls `launch()`.
- The legacy `AgentRegistry` stays for prompt-only agents — unchanged. Live agents go through `MultiAgentSystem`.

## Data model

### Role file — `~/.plia_ai/roles/<slug>.yml`

Already supported by `discover_roles()`. Wizard fills this in. Example:

```yaml
id: github_project_watcher
name: GitHub Project Watcher
description: Watches GitHub for new repositories related to <topic>.
responsibilities:
  - Search GitHub for repos matching the user's topic
  - Filter out already-seen repos
  - Return a ranked list with title, stars, description, link
tools:
  - web_search
  - http_get          # NEW small tool — see "New tools" below
authority_level: 1
autonomous_actions: [web_search, http_get]
approval_required: []
sub_roles: []
heartbeat_instructions: |
  Find new GitHub repositories matching the user's topic.
  Report the top results with stars and short descriptions.
communication_style:
  tone: concise
  verbosity: brief
  formality: neutral
kpis: []
```

### Runtime state — `~/.plia_ai/agent_state.json`

One entry per `AgentInstance`. Dataclass:

```python
@dataclass
class AgentState:
    role_id: str               # links to a RoleDefinition
    instance_id: str           # AgentInstance.id (UUID)
    display_name: str
    icon: str
    executor: str              # "script" | "tool_loop"
    script_path: str | None    # set if executor == "script"
    trigger: str               # "scheduled" | "on_demand" | "quota"
    cadence: dict | None       # scheduled: {"interval_sec": int, "anchor_iso": str}
    quota: dict | None         # quota: {"limit": int, "criterion": str, "progress": int}
    persistence: str           # "persistent" | "session"
    notify: str                # "tts" | "toast_card" | "comm_log"
    status: str                # "active" | "paused" | "terminated"
    next_fire_at: str | None
    last_fire_at: str | None
    runs: int
    history: list[dict]        # FIFO cap 50: {ran_at, success, summary, details, items_found, items, error}
    created_at: str
```

Lifecycle rules:
- `persistence == "persistent"` → loaded and re-armed on startup; quota progress resumes.
- `persistence == "session"` → dropped on shutdown (re-cleared at next startup load).
- `status == "terminated"` → entry stays in file (history) but never re-arms.

### Tool whitelist (security)

`AuthorityBounds.allowed_tools` already exists in `multi_agent.py`. The creation pipeline picks a safe default per task via keyword map; user can edit via the Active Agents editor.

Confirmed tools exposed by `core/function_executor.py`: `set_timer`, `set_alarm`, `create_calendar_event`, `add_task`, `web_search`, `get_system_info`, `control_desktop`, `system_command`, `manage_notes`, `send_email`, `read_emails`, `clipboard_action`, `file_operations`, `get_stock_price`, `convert_currency`, `translate_text`, `control_media`, `network_tools`, `mcp_tool_call`.

Destructive tools (`control_desktop`, `system_command`, `file_operations`, `send_email`) are **never** auto-granted. They require explicit user opt-in in the Edit dialog, and only `authority_level >= 5` agents can use them. Default authority for wizard-created agents is `1`.

### New tools

`http_get` — a small read-only HTTP GET tool added to `function_executor` (returns status + body, text only, size-capped). API-driven agents (GitHub, generic REST) need it; `web_search` only does search-result scraping and `network_tools` is for diagnostics, not content fetch. This is the only genuinely new tool the design requires.

### Wizard answers mapping

| Wizard answer | Lands in |
|---|---|
| Task description | `role.responsibilities`, `role.heartbeat_instructions`, `role.description` |
| Trigger / cadence / quota | `state.trigger`, `state.cadence`, `state.quota` |
| Persistence | `state.persistence` |
| Notify channel | `state.notify` |
| Auto-classified executor | `state.executor`, `state.script_path` |
| Auto-picked tools | `role.tools`, `role.autonomous_actions` |

## Creation pipeline

### Intent detection

- **Chat path**: existing `agent_registry.parse_create_intent` and `agent_builder.detect_build_intent` continue to fire from `gui/handlers.py`. Both now route into the unified `agent_creator.start_wizard(...)` instead of immediately opening the legacy dialog.
- **Voice path**: new early intercept in `core/voice_assistant.py::_process_query`, before the router, using the same regex set. On match → `agent_creator.start_wizard(task, channel="voice")`.

### Wizard state machine — `core/agent_creator.py`

```
PARSE_INTENT      (task captured)
    ↓
ASK_TRIGGER       → "Scheduled, on-demand, or quota?"
    ↓
ASK_CADENCE       (only if trigger == scheduled)
                  "How often? e.g. every hour / twice a day / every Monday"
    ↓
ASK_QUOTA         (only if trigger == quota)
                  "How many results? Top-rated or any?"
    ↓
ASK_PERSISTENCE   → "Survive restarts, or session-only?"
    ↓
ASK_NOTIFY        → "Speak, toast + dashboard card, or communication log?"
    ↓
CLASSIFY_EXECUTOR (silent — small Ollama call)
PICK_TOOLS        (silent — keyword map → AuthorityBounds.allowed_tools)
    ↓
BUILD_ARTIFACTS
  • script:    invoke AgentBuilder → ~/.plia_ai/agents/<slug>.py
  • tool_loop: skip — runtime uses role + tools directly
    ↓
CONFIRM           → read back summary, user says yes/no/edit
    ↓
COMMIT
  • write ~/.plia_ai/roles/<slug>.yml
  • append AgentState to ~/.plia_ai/agent_state.json
  • multi_agent_system.reload_roles()
  • create AgentInstance, add to hierarchy
  • scheduler.arm(state)
```

One `WizardController` class. Both UI channels drive it through `answer(text)`.

### Channel adapters

- **VoiceAdapter** — emits each question via TTS, listens for the next utterance via STT, parses with per-question regex/keyword matchers. "Cancel" / "never mind" / "stop" aborts. After two parse failures, falls back to the GUI dialog.
- **ChatAdapter** — opens a multi-page `CreationWizardDialog` (PySide6) pre-filled with the parsed task. Each page = one wizard state.

Both adapters share the same per-question parser so voice and chat give identical interpretation.

### Executor classifier (silent step)

Single Ollama call to `RESPONDER_MODEL`:

```
You are picking the execution model for a Plia agent.
TASK: <task>

Reply with exactly one word:
- script    → task is deterministic and repeatable (search+download, RSS fetch, fixed-API check)
- tool_loop → task is exploratory or multi-step (research, compare, decide based on findings)
```

On parse failure, default to `tool_loop` (safer — runs under iteration cap).

### Tool whitelist picker (silent step)

Keyword map → default tool set:

| Task contains | Default tools |
|---|---|
| `github`, `repo`, `pull request` | `web_search`, `http_get` |
| `email`, `inbox` | `read_emails` (read-only; `send_email` requires opt-in) |
| `calendar`, `event`, `meeting`, `schedule` | `get_system_info` (exposes `calendar_today`); `create_calendar_event` requires opt-in |
| `news`, `rss`, `article`, `headline` | `web_search`, `http_get` |
| `stock`, `price`, `currency` | `get_stock_price`, `convert_currency` |
| (no match) | `web_search` only |

Destructive tools are blocklisted from auto-grant. Task strings that mention dangerous verbs (`delete`, `rm`, `format`, `shell`) trigger a wizard warning and require explicit confirmation before tools are granted.

### Confirmation summary (voice example)

> "Here's what I'll create. GitHub Project Watcher. Watches GitHub for new repos related to your topic. Runs every six hours. Stays active across restarts. Notifies you via dashboard toast. Tool-loop with web search and HTTP. Say yes to create."

"Yes" → COMMIT. "No" → "Which part should we change?" → re-asks that step. "Cancel" → discard.

### Edge cases

- Task under 6 words or no verb-object → re-prompt for clarification before ASK_TRIGGER.
- Duplicate slug → suffix `_2`, `_3`.
- Forbidden tool keywords in task → warn and require explicit grant.
- STT mis-hear: two consecutive parse failures → fall back to GUI dialog.

## Scheduler

Module: `core/agent_scheduler.py`. QTimer-based — no new dependencies.

### Trigger modes

| Mode | Behaviour |
|---|---|
| `scheduled` | Fires every `cadence.interval_sec`, anchored to `cadence.anchor_iso`. Catch-up: one immediate fire if the most recent scheduled tick was missed while Plia was off. |
| `on_demand` | Never auto-fires. "Run now" button is the only trigger. |
| `quota` | Fires on a short interval (default 10 min) until `quota.progress >= quota.limit`, then auto-terminates. Run-now still works. |

### Cadence parser

| Phrase | Result |
|---|---|
| `every hour` / `hourly` | `interval_sec=3600`, anchor = top of next hour |
| `every 30 minutes` | `interval_sec=1800` |
| `twice a day` | `interval_sec=43200`, anchor = 09:00 and 21:00 local |
| `daily` / `every day at 8am` | `interval_sec=86400`, anchor = 08:00 local |
| `every Monday morning` | weekly anchor, Mon 08:00 |
| anything else | re-prompt with examples |

### Scheduler API

```python
class AgentScheduler(QObject):
    def __init__(self, multi_agent_system, task_manager, state_store, now_provider=None): ...

    def load_and_arm(self) -> None:
        """Called on Plia startup. Reads agent_state.json,
        arms persistent agents, drops session agents."""

    def arm(self, state: AgentState) -> None: ...
    def disarm(self, role_id: str) -> None: ...
    def pause(self, role_id: str) -> None: ...
    def resume(self, role_id: str) -> None: ...
    def fire_now(self, role_id: str) -> str:
        """Run the agent immediately. Returns task_id."""

    def _on_tick(self, role_id: str) -> None:
        """Internal callback. Delegates to AgentTaskManager.launch(...)."""
```

### Fire flow

```
Timer fires for role_id
    ↓
state_store.lock(role_id)              # avoid double-fire
    ↓
if previous run still running → skip this tick, schedule next
    ↓
runner = script_executor OR tool_loop_executor   # from state.executor
    ↓
task_id = AgentTaskManager.launch(
    agent=instance, task=role.heartbeat_instructions,
    context=last_history_summary, runner=runner)
    ↓
state.last_fire_at = now; state.runs += 1
state.next_fire_at = compute_next(cadence, mode)
state_store.save_debounced()
    ↓
on AgentTaskManager completion (callback):
    dispatcher.report(state, result)
    if mode == quota:
        state.quota.progress += result.items_found
        if state.quota.progress >= state.quota.limit:
            scheduler.disarm(); state.status = "terminated"
    state_store.save_debounced()
```

### Concurrency rules

- Each agent runs in its own thread (existing `AgentTaskManager`).
- One agent only ever has one run in flight; overlapping ticks are skipped, not queued.
- Scheduler arming/disarming runs on the Qt event loop — no locks needed.
- State store uses a single file lock for writes; reads are unlocked snapshots.

### Catch-up policy

On startup, for each persistent + scheduled agent:
- If `last_fire_at + cadence.interval_sec < now`: fire once immediately, then resume normal cadence. Default: **enabled**, not asked in the wizard.

### Pause / Resume / Stop semantics

- **Pause**: QTimer cancelled. `status="paused"`. Resume only via user click.
- **Stop / Terminate**: `disarm()` + `MultiAgentSystem.terminate_agent(instance_id)`. State entry stays in file (`status="terminated"`) for history. Cannot be resumed — user re-creates.
- **Delete**: state entry removed + role YAML deleted + generated script deleted (if any). Hard remove.

## Execution model

### Shared run-result shape

Both executors return the same dict so scheduler and dispatcher don't care which one ran:

```python
@dataclass
class RunResult:
    success: bool
    summary: str            # one-line human-readable (TTS, toast, log title)
    details: str            # multi-line full output (Active Agents history)
    items_found: int        # count contributing to quota.progress
    items: list[dict]       # optional structured findings (title, url, score, ...)
    error: str | None
```

Both executors match `AgentTaskManager.launch()`'s expected signature:

```python
def runner(*, agent: AgentInstance, task: str, context: str) -> dict: ...
```

### Script executor — `core/executors/script_executor.py`

**At creation (once, in COMMIT)**:
- `AgentBuilder.build_agent()` writes `~/.plia_ai/agents/<slug>.py`.
- Its `_SYSTEM_PROMPT` is extended to require this exact `run()` signature:
  ```python
  def run(**kwargs) -> dict:
      """Returns {success, summary, details, items_found, items}."""
  ```
- `state.script_path` is set to the produced file.

**On each tick**:
1. Spawn subprocess: `python <script_path> --task "<task>" --context "<ctx>" --json`
2. Read final JSON line on stdout (the script's `run()` result).
3. Default timeout: 5 min (configurable per role).
4. Non-zero exit OR no JSON parsed → `RunResult(success=False, error=...)`.

Subprocess isolation — agent scripts may have their own deps, may misbehave, may need to be killed. Subprocess keeps Plia safe.

### Tool-loop executor — `core/executors/tool_loop_executor.py`

Tool catalog: built per-run from `agent.authority.allowed_tools`. Each entry is `{name, signature, description}` from existing `function_executor` schemas and MCP tool registry.

Loop:

```
messages = [
    {role: system, content: build_system_prompt(role) + tool_catalog_text},
    {role: user,   content: task},
    {role: user,   content: "Previous run summary: " + context},   # if any
]
for step in range(MAX_STEPS = 8):
    response = ollama.chat(messages, tools=catalog, stream=False)
    if response.tool_calls:
        for call in response.tool_calls:
            if call.name not in allowed_tools:
                messages.append({role: tool, content: "DENIED: not in allowed_tools"})
                continue
            result = function_executor.execute(call.name, call.params)
            messages.append({role: tool, name: call.name, content: json.dumps(result)})
    else:
        return parse_final(response.content)

# Iteration cap hit
return RunResult(success=True, summary="Iteration cap reached. Partial results.", ...)
```

Hard limits (from `agent.authority`):
- `max_token_budget` — sum of all `prompt_eval_count + eval_count`; abort if exceeded.
- `MAX_STEPS = 8` (configurable, 1–16).
- Per-tool denylist enforced even if `allowed_tools` says yes.

Final response parsing — LLM ends with:

```
SUMMARY: <one line>
ITEMS_FOUND: <number>
ITEMS_JSON: <json array>
```

Robust regex extracts each. Missing fields default to 0 / empty.

### Memory across runs

Both executors get `context = state.history[-1].summary` (last successful run). For tool-loop, the LLM sees "Previous run summary: ...". For scripts, kwargs include `--context`.

Long-term per-agent state (e.g., "repos I've already seen") is the agent's responsibility. Out of scope for v1.

### Failure isolation

- Script crash → kills only the subprocess.
- Tool-loop budget/step cap → returns partial result, dispatcher reports the partial.
- Either failure increments `runs`, records `success=False`, and **does not** terminate. Scheduler arms next tick normally.
- Executor-internal exception → logged, reported as `error="executor_internal"`.

## Reporting

Module: `core/agent_reporting.py`.

`ResultDispatcher` (QObject, main thread) receives `RunResult` from background executor threads via signal, fans out to channels.

### Always — history

- Each `RunResult` becomes a history entry on `AgentState`.
- History capped at 50 entries per agent (FIFO).
- After append: `agent_history_appended` signal → `AgentsTab` refreshes the row.
- Active Agents tab gains a per-agent collapsible "Run History" panel showing the last 10 runs: timestamp, success/fail dot, summary. Expand a row → see full `details`.

### Channel A — TTS

| Condition | Spoken |
|---|---|
| success, items_found > 0 | "<display_name>: <summary>." |
| success, items_found == 0 | "<display_name> ran. Nothing new." |
| failure | "<display_name> failed. <error or 'unknown error'>." |

Goes through existing `tts.queue_sentence()`.

### Channel B — Toast + dashboard card

- **Toast**: existing `InfoBar` pattern. 4-second auto-dismiss. Green/red.
- **Dashboard card**: new `CardWidget` on dashboard tab. Shows icon + display name, summary, top 3-5 item titles, timestamp, "View all" → Active Agents tab. Stacks newest-first, capped at 5 visible; older collapse into "More..." count.

### Channel C — Communication log

Appends a colour-tagged block to the existing dashboard `comm_log` `QTextEdit`:

```
[14:32:07] GitHub Project Watcher
  Found 3 new repos related to your topic.
    • acme/local-llm-router  (412 stars)
    • orgX/voice-agent-fw    (89 stars)
    • personY/plia-fork      (12 stars)
```

### Thread safety

Executors call `result_dispatcher.report(...)`, which writes state under file lock then emits signals. Qt queued connections move signals onto the main thread before widget updates.

### Touched files

| File | Change |
|---|---|
| `gui/app.py` | Construct `result_dispatcher`; connect signals to existing toast/card/comm-log slots. |
| `gui/tabs/agents.py` | Live Agents section + history panel; subscribe to `agent_history_appended`. |
| `gui/tabs/dashboard.py` | Add `add_agent_card(payload)`. Existing `_log()` handles comm-log. |
| `core/agent_reporting.py` | New. Owns the dispatcher. |

## Active Agents tab controls

### Layout

New top section: **"Live Agents"** above the legacy "Custom Agents" block (unchanged for prompt-only agents).

Each live agent is one card:

```
┌────────────────────────────────────────────────────────────────────┐
│ 🔍 GitHub Project Watcher        ● active                          │
│ Runs every 6 hours · next in 2h 14m · last 14:32 ✓ · 12 runs       │
│ [▶ Run now] [⏸ Pause] [⏹ Stop] [⚙ Edit] [🗑 Delete]    ▼ History  │
├── History (expanded) ──────────────────────────────────────────────┤
│ 14:32 ✓  Found 3 new repos related to your topic.                  │
│ 08:32 ✓  Found 1 new repo: acme/local-llm-router.                  │
│ 02:32 ✓  Ran. Nothing new.                                          │
└────────────────────────────────────────────────────────────────────┘
```

Variants per trigger:
- **Quota**: subtitle `Quota: 8/20 found · runs every 10 min`. "Pause" → "Cancel" once `progress > 0`.
- **On-demand**: subtitle `On-demand only · last run 12:04 ✓ · 3 runs`. "Pause" hidden.

### Button semantics

| Button | Action | Side effects |
|---|---|---|
| ▶ Run now | `scheduler.fire_now(role_id)` | Disabled while run in-flight; spinner in status. |
| ⏸ Pause | `scheduler.pause(role_id)` | Cancels QTimer, `status="paused"`. In-flight run completes. |
| ▶ Resume | `scheduler.resume(role_id)` | Recomputes `next_fire_at`; arms QTimer. |
| ⏹ Stop | `scheduler.disarm()` + `terminate_agent()` | `status="terminated"`; instance removed from hierarchy. Card stays visible (greyed) until deleted. |
| ⚙ Edit | Opens `AgentEditorWindow` (extended) | On save, disarm+rearm if cadence changed. |
| 🗑 Delete | Confirm dialog | Removes state entry, role YAML, generated script (if any). Hard delete. |
| ▼ History | Expand the run history panel | Per-session UI state, not persisted. |

### Bulk controls

- "Pause all" / "Resume all".
- Status filter: All / Active / Paused / Terminated.
- Sort: Name / Next fire / Last run / Status.
- Count strip: `3 active · 1 paused · 2 terminated`.

### Edit dialog — extended `AgentEditorWindow`

Tabs:
1. **Basics** — display name, icon, task description.
2. **Schedule** — trigger mode, cadence (free-text + parser), quota limit + criterion.
3. **Tools** — checkbox list of `function_executor` + MCP tools. Destructive ones in red, require explicit toggle.
4. **Notify** — radio: TTS / Toast+Card / Comm log.
5. **Advanced** — persistence, max steps (1–16), token budget, catch-up policy. Read-only `executor` field — changing executor requires recreation.

Save flow: validate → disarm scheduler → update role YAML + state entry → `reload_roles()` → re-arm with new cadence.

### Empty state

> "No live agents yet. Say *'Create an agent that…'* or click **+ Create Live Agent**."

`+ Create Live Agent` button opens the same wizard via `agent_creator.start_wizard(channel="chat")`.

### Touched files

| File | Change |
|---|---|
| `gui/tabs/agents.py` | New `LiveAgentsSection` widget. |
| `gui/tabs/agent_editor.py` | Add Schedule / Tools / Notify / Advanced tabs. |
| `gui/handlers.py` | Route `+ Create Live Agent` button into `agent_creator.start_wizard(...)`. |
| `core/agent_state.py` | New `changed` signal. |

## Testing

`pytest>=7.0.0` already in `requirements.txt`. New `tests/` directory mirrors `core/`.

### Pure-logic unit tests

| Module | Examples |
|---|---|
| `agent_creator.parse_cadence` | "every hour" → 3600, "every Monday morning" → weekly+Mon 08:00, "blarg" → None |
| `agent_creator.parse_intent` | "create an agent that watches GitHub" → captures task; weather queries → None |
| `agent_creator.pick_tools` | "github" → [web_search, http_get]; "delete files" → refuses |
| `agent_creator.classify_executor` | mock Ollama; assert `script` for "download X to ~/Downloads", `tool_loop` for "compare top 5 LLM repos" |
| `agent_state` serialization | round-trip dataclass ↔ JSON; missing-fields tolerance |
| `agent_reporting._tts_phrase` etc. | success+items, success+empty, failure phrasings |

### Scheduler tests (injected clock)

`AgentScheduler` takes a `now_provider` (defaults to `datetime.now`). Tests inject a stub clock + fake QTimer:

- Arm scheduled agent, verify `next_fire_at` arithmetic.
- Catch-up: missed tick on `load_and_arm()` fires once immediately, then arms next.
- Pause cancels timer; Resume recomputes from current clock.
- Quota at 19/20 + 1 new item triggers `disarm` + `terminated`.
- Overlapping ticks: in-flight run → skip, log, schedule next.

### Executor tests (with mocks)

**Script executor**: fake `Popen`. Verify valid JSON → `RunResult`; no JSON / non-zero exit / timeout each map to correct failure.

**Tool-loop executor**: stub Ollama HTTP + stub `function_executor.execute`. Verify tool-call → execution → result fed back; denied tool → "DENIED" message; 8 iterations → partial; token budget exceeded → partial.

### Integration tests (no GUI)

1. **Happy path**: `commit(answers)` → YAML + state written → `reload_roles()` → `fire_now()` → mocked tool-loop → dispatcher → history appended.
2. **Persistence**: create persistent agent → tear down → reconstruct → `load_and_arm()` re-arms; history survives.
3. **Session agent dropped**: create session → tear down → reconstruct → state entry gone.
4. **Quota lifecycle**: quota-3 agent → fire 3 times → auto-terminates.

### GUI smoke tests (manual checklist in `tests/manual_smoke.md`)

- Voice: "Create an agent that watches GitHub" → wizard speaks each question → COMMIT → tab updates.
- Chat: same intent → dialog opens pre-filled → user picks options → COMMIT → tab updates.
- Run-now per trigger mode → toast/card appears, history updates.
- Pause + Resume + Stop + Edit + Delete each behave per spec.
- TTS / toast+card / comm-log channels each tested with a stub agent.
- Restart with one persistent + one session agent → persistent re-armed, session gone.

### Out of scope for tests

- Real Ollama responses — stubbed everywhere.
- Real GitHub API — canned fixtures.
- TTS audio output — verified at the call-site level only.

### Verification before completion

`pytest` green, manual checklist signed off, app launches and creates one agent end-to-end without console errors.

## File inventory

### New files

| Path | Purpose |
|---|---|
| `core/agent_creator.py` | Wizard state machine + parsers + voice/chat adapters |
| `core/agent_state.py` | `AgentState` dataclass + persistent store (`agent_state.json`) |
| `core/agent_scheduler.py` | QTimer-based scheduler |
| `core/agent_reporting.py` | `ResultDispatcher` + channel routing |
| `core/executors/__init__.py` | Package init |
| `core/executors/script_executor.py` | Subprocess runner for generated `.py` agents |
| `core/executors/tool_loop_executor.py` | LLM + tool-call loop runner |
| `tests/test_agent_creator.py` | Wizard / parser unit tests |
| `tests/test_agent_scheduler.py` | Scheduler tests with injected clock |
| `tests/test_executors.py` | Script + tool-loop executor tests |
| `tests/test_agent_state.py` | Serialization + persistence tests |
| `tests/test_integration.py` | End-to-end without GUI |
| `tests/manual_smoke.md` | Manual GUI/voice checklist |

### Modified files

| Path | Change |
|---|---|
| `core/multi_agent.py` | Point the `multi_agent_system` singleton's `roles_dir` at `~/.plia_ai/roles/` (currently the relative `"roles"`); possibly expose `terminate_agent`/`reload_roles` signals |
| `core/agent_builder.py` | Extend `_SYSTEM_PROMPT` to enforce `run()` return shape |
| `core/function_executor.py` | Add `http_get` tool (read-only HTTP GET, size-capped) |
| `core/voice_assistant.py` | Add agent-creation intent intercept before router |
| `gui/handlers.py` | Route create-agent intents to `agent_creator.start_wizard` |
| `gui/app.py` | Construct `result_dispatcher`, scheduler, state store; wire signals; call `scheduler.load_and_arm()` on startup |
| `gui/tabs/agents.py` | New `LiveAgentsSection` widget + history panel |
| `gui/tabs/agent_editor.py` | New tabs: Schedule / Tools / Notify / Advanced |
| `gui/tabs/dashboard.py` | New `add_agent_card()` method + card list region |

## Open considerations (deferred, not blocking v1)

- Parent/child delegation UI: `MultiAgentSystem` already supports it. Wizard doesn't expose it in v1.
- Long-term per-agent memory beyond last-summary: agents self-manage today. A future `agent_memory_write` tool can be added.
- Per-agent log retention beyond 50 entries: capped now; rotation strategy can come later.
- Real Ollama tool-call API support: if `RESPONDER_MODEL` doesn't support native tool-calling, the tool-loop executor falls back to a regex-parsed JSON-tool protocol (well-trodden pattern).
