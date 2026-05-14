Plia doesn’t have a built-in **“marketplace browser”** UI (skills marketplace / OpenClaw / Hermes / Composio-style listing + one-click add). The only “marketplace-like” capability in this codebase is:

1) **Use Internet Search Agent (web) → generate results/behavior**, and  
2) **Create/register a local agent** so it appears in **Agent List**.

## What you *can* do to “search the marketplace”
### Option 1: Web-search for agents, then build/use one locally
1. Open **Active Agents** tab.
2. Click **Create Agent**.
3. Choose **Internet Search Agent** by providing an **OpenAI API key** (the dialog supports it).
4. Click **Run Agent**: you’ll be prompted for:
   - **Search Query**
   - **Task**
5. The output is produced by that internet-search agent.
6. If you want it to become a reusable item in the **Agent List**, you must then **build/create** an agent from that idea (Agent Builder flow), so it gets saved into `~/.plia_ai/custom_agents.json`.

### Option 2: Use Agent List as the “marketplace shelf” (local registry)
- The **Agent List** tab only shows agents that already exist in the **local registry** (`core/agent_registry.py`).
- Now that your **Agent List Run** supports `internet_search` agents, you can:
  - click **Run** on an internet-search agent entry,
  - enter the runtime **search query + task**,
  - and it will launch with the correct CLI args (`--search` / `--task`).

## Why “marketplace add” isn’t available here
- Searches for keywords like *marketplace/skills/OpenClaw/Hermes/Composio/Home Assistant* only hit the **agent creation/run flows**, not any UI/data source that downloads third-party agents into the registry automatically.

## Quick check
Do you want the marketplace experience to be:
1) **A) “Find agents on the internet and immediately use them”** (web-first, no install), or  
2) **B) “Find agents on the internet and install/save them into Agent List”** (requires adding code to fetch/prebuild + register)?

Reply A or B and I’ll give you the exact best workflow Plia can do today (and what would be missing for the other).