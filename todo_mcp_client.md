# MCP Client — Implementation Todo (Plia)

- [ ] Confirm/define `~/.plia/mcp.json` schema (servers list, env/args, transport: stdio/TCP)
- [ ] Add dependency on the official MCP Python SDK to `requirements.txt` (exact pip package + version pin)

- [ ] Implement `core/mcp_client.py`
  - [ ] Load MCP config from `~/.plia/mcp.json`
  - [ ] Spawn MCP servers per config (lifecycle management: start/restart/stop)
  - [ ] Connect to servers + perform tool discovery
  - [ ] Cache a tool catalog (tool_name → schema/description, server origin)
  - [ ] Provide an execution API: `execute(tool_name, arguments) -> {success, message, data}`
  - [ ] Ensure thread-safety for calls coming from Qt `QThread` workers

- [ ] Integrate MCP into routing model logic
  - [ ] Modify `core/router.py` to add a *single stable* tool entry (recommended): `mcp_tool_call(tool_name, arguments) -> str`
  - [ ] Add `mcp_tool_call` to the router’s `VALID_FUNCTIONS` / tool schema list
  - [ ] Adjust router guidance (short “available MCP tools” catalog) without retraining
  - [ ] Decide how router will select a tool (tool catalog text + stable function call pattern)

- [ ] Integrate MCP into backend execution
  - [ ] Modify `core/function_executor.py` to dispatch `func_name == "mcp_tool_call"`
  - [ ] Normalize MCP output to executor contract `{success, message, data}`
  - [ ] Handle error paths cleanly: tool not found, server unreachable, timeout, invalid args

- [ ] Ensure the assistant uses tool results effectively
  - [ ] Modify `gui/handlers.py` context injection:
    - [ ] When `mcp_tool_call` succeeds, include truncated but faithful tool output in `context_msg`
    - [ ] Add truncation + JSON-to-text conversion rules (avoid huge payloads)
  - [ ] Ensure non-tool functions keep current behavior

- [ ] Add diagnostics & observability
  - [ ] Add clear logging for: config load, server spawn, tool discovery count, each tool execution + duration
  - [ ] Ensure failures don’t crash app; return helpful error messages to the LLM

- [ ] Smoke test & validation
  - [ ] Create a minimal local MCP test server (1 tool) for automated/manual smoke testing
  - [ ] Smoke: tool discovery works (tool catalog appears)
  - [ ] Smoke: `mcp_tool_call` executes the tool and returns output
  - [ ] Integration: send a chat prompt that causes router → executor → MCP tool → LLM response using the output
  - [ ] Regression: verify existing timer/web_search/desktop flows still work

- [ ] Documentation updates
  - [ ] Document `~/.plia/mcp.json` example schema
  - [ ] Document supported transport(s) and how to add servers
  - [ ] Document how to run a quick smoke test
