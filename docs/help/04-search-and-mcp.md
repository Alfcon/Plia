# Web Search & MCP Servers

## Web search backends

Plia ships with two: **Brave Search API** (preferred) and **DuckDuckGo** (via the `ddgs` package). Both produce the same normalised `{title, body, url}` shape so callers don't care.

### Brave (recommended)
1. Get a free API key at <https://api.search.brave.com> (2 000 queries / month free tier).
2. Open **Settings → Web Search**.
3. Paste the key into **Brave Search API Key**.
4. The **Search Backend** dropdown:
   - `auto` (default): Brave if a key is set, else DuckDuckGo.
   - `brave`: hard-pin to Brave (still falls back to DDG if Brave errors).
   - `duckduckgo`: hard-pin to DDG.

When Brave returns an HTTP error (401, 429, etc.), Plia automatically retries via DuckDuckGo.

### DuckDuckGo (no key)
Works out of the box; no setup required. Rate-limit behaviour is at the mercy of DDG's infra.

## MCP Servers

The [Model Context Protocol](https://modelcontextprotocol.io) is an open spec for running tool servers as stdio subprocesses. Plia spawns and manages them via the **MCP Servers** tab.

### What you can plug in
Anything in the official MCP server registry. Example commands:

| Server | Command | Args | Notes |
|---|---|---|---|
| GitHub | `npx` | `-y @modelcontextprotocol/server-github` | Set `GITHUB_PERSONAL_ACCESS_TOKEN=…` in Env |
| Filesystem | `uvx` | `mcp-server-filesystem /home/you/Documents` | Limit to a directory you trust the LLM with |
| Brave Search | `npx` | `-y @modelcontextprotocol/server-brave-search` | Set `BRAVE_API_KEY=…` |
| Slack | `npx` | `-y @modelcontextprotocol/server-slack` | Set Slack tokens in Env |
| Fetch (HTTP) | `uvx` | `mcp-server-fetch` | No setup |

### Adding a server
1. Open **MCP Servers** tab.
2. Click **Add Server**.
3. Fill the dialog:
   - **Server ID** — short unique key, e.g. `github` (becomes the prefix for every tool: `github:create_issue`).
   - **Command** — executable, e.g. `npx` or `uvx`.
   - **Arguments** — one per line, or a JSON list.
   - **Environment** — `KEY=value` lines (e.g. `GITHUB_PERSONAL_ACCESS_TOKEN=ghp_…`).
4. Click **Save**.

The InfoBar says *"MCP config saved — Reloading servers…"*, then *"MCP reload complete — N tool(s) discovered"*. No Plia restart needed.

### How agents use MCP tools
Every discovered MCP tool surfaces with the ID `<server_id>:<tool_name>`. Agents call them via the built-in `mcp_tool_call` tool:

```
mcp_tool_call({
    "tool_id": "github:create_issue",
    "arguments": {"owner": "...", "repo": "...", "title": "..."}
})
```

The Function Gemma router also includes the MCP catalog when routing free-text queries, so spoken commands can hit MCP tools without you having to know the tool_id.

### Reload Now
The **Reload Now** button on the MCP Servers tab kills current sessions and re-spawns from the current `mcp.json`. Useful if a server crashed or if you edited the file directly.

### Config file
Everything is stored in `~/.plia/mcp.json`:
```json
{
  "servers": [
    {
      "id": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."},
      "connect_timeout_seconds": 10.0,
      "call_timeout_seconds":    60.0
    }
  ]
}
```
