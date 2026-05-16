# Live Agents

Live agents are the worker units of Plia. Each agent has a task, a trigger, a set of tools it can use, and one or more notify channels for its results.

## Anatomy of an agent

| Field | Meaning |
|---|---|
| **Display name** | Human label shown everywhere |
| **Task description** | The prompt baked into the agent's system prompt — what it's supposed to do each run |
| **Engine (executor)** | `tool_loop` (LLM with tools, the default) or `script` (runs a generated .py) |
| **Trigger** | `on_demand` (you click Run), `scheduled` (every N), or `quota` (until N items found) |
| **Cadence / Quota** | Set only for scheduled or quota triggers |
| **Persistence** | `persistent` (survives Plia restart) or `session` (gone on restart) |
| **Notify channels** | Where results go: `tts`, `chat`, `comm_log`, `file`, `toast_card`, `web_searches`. **Combinable** — e.g. `tts,chat,file` fires all three. |
| **Allowed tools** | Whitelist of tools the agent's LLM may call |
| **Status** | `active`, `paused`, `terminated` |

## Creating an agent

### Voice
Say *"jarvis create an agent that &lt;task description&gt;"*. The wizard asks:
1. **Trigger** — say "on demand", "scheduled", or "quota". (Between answers Plia primes STT so you don't need to say "jarvis" each time.)
2. **Cadence / Quota** — only if you picked scheduled / quota.
3. **Persistence** — "persistent" or "session only".
4. **Notify** — say one or many: "speak", "chat", "save to file", "communication log", "web searches", "toast" — or combine: "speak and save to file".
5. **Confirm** — "yes" or "no".

### Chat
Type the same in the Chat tab. The wizard opens as a dialog instead of voice.

## Running an agent (Agent List page)

Each Live Agent row has these buttons:

| Button | Behaviour |
|---|---|
| **▶ Run now** | Fire the agent with its stored task description. If the agent was terminated, it's reactivated first. |
| **💬 Run with prompt…** | Open a small dialog, type a one-off prompt, the agent runs with that as its task instead of the stored one. Useful for Manager / orchestrator agents driven by different questions each time. |
| **⏸ Pause / ▶ Resume** | Only for scheduled/quota agents — pauses the next-tick timer. |
| **⏹ Stop** | Mark the agent terminated. (Run now reactivates it.) |
| **⚙ Edit** | Open the editor: change display name, task, schedule, tools, notify channels. Read-only "Available sub-agents" panel lists every other agent you can call via `run_agent`. |
| **🗑 Delete** | Remove the agent + its role YAML. |

A **green ● running** dot appears in front of the status while a run is in flight; it reverts when the run completes.

## Sub-agent orchestration

Two built-in tools let agents call other agents:

- **`list_agents`** — returns every live agent in the runtime (name, role_id, executor, trigger, status, description).
- **`run_agent`** — invoke a specific agent. Params: `agent` (role_id) or `name` (display name, case-insensitive), `task` (optional one-off task).

Build a Manager agent by giving it `list_agents` + `run_agent` and writing its task as orchestration steps. The recursion guard caps depth at 3 so A → B → A loops are bounded.

## Notify channels

| Channel | Where the result lands |
|---|---|
| `tts` | Plia speaks a one-line summary |
| `chat` | A new bubble in the agent's dedicated chat session (sidebar entry) |
| `comm_log` | The dashboard's Communication Log |
| `file` | Appended to `~/.plia_ai/agent_results/<role_id>.log` |
| `toast_card` | Top-right toast + a result card on the Dashboard right panel |
| `web_searches` | A clickable card on the Web Searches tab |

Combine freely: `tts,chat,web_searches` is valid and fires all three.

## Hallucination guard

The tool-loop executor refuses empty answers from models that skip their tools. If the LLM returns 0 items without calling any tool, Plia nudges it to retry with the tool first. If it answers with items but never called a tool, the result is flagged in the chat output with *"⚠️ The agent did not call any tools…"*.
