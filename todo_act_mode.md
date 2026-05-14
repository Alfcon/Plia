# Plia — Act-mode Implementation TODO (priority: 2,1,3,4)

- [ ] MCP tool-catalog relevance pruning (routing scalability):
  - [ ] Add relevance/intent matching to keep only top-K relevant MCP tools before injecting catalog text into router prompt
  - [ ] Cache pruned catalog per (session + prompt hash) to avoid recomputation
  - [ ] Add diagnostics logging: total MCP tools, kept MCP tools, pruning reason/keywords
  - [ ] Confirm behavior when MCP catalog is empty (no regressions)

- [ ] MCP end-to-end sanity:
  - [ ] Create an example `~/.plia/mcp.json` schema for a minimal stdio MCP server (document it in a new markdown file)
  - [ ] Verify startup discovery completes and router prompt includes MCP tool catalog
  - [ ] Verify `mcp_tool_call(tool_id, arguments)` routes through `core/function_executor.py` → `core/mcp_client.py` → MCP server and returns `{success, message, data}`
  - [ ] Smoke test with at least one real MCP tool (manual test + log evidence)

- [ ] Sensitive-data auto-redaction before *every* Ollama call (chat + voice + file injection):
  - [ ] Implement deterministic redaction utility (PII/secrets patterns + optional user blocklist)
  - [ ] Hook redaction into:
    - [ ] Chat pipeline in `gui/handlers.py` before constructing messages/context sent to Ollama
    - [ ] Voice pipeline in `core/voice_assistant.py` before building prompts/context sent to Ollama
    - [ ] File-injection prompt body used for “read option N” / file-read response
  - [ ] Ensure redaction is applied consistently to both:
    - [ ] LLM input prompts
    - [ ] LLM-derived context text shown in UI
  - [ ] Avoid logging raw secrets anywhere (update logs if necessary)

- [ ] Redaction controls in settings:
  - [ ] Add settings toggle: enabled/disabled
  - [ ] Add strictness levels: light/normal/strict
  - [ ] Add optional user blocklist patterns (persisted)
  - [ ] Wire settings into redaction utility (single source of truth)

- [ ] Morning digest scheduled agent:
  - [ ] Implement daily scheduler mechanism (prefer minimal change; Qt timer/background thread acceptable)
  - [ ] Implement digest routine:
    - [ ] Fetch briefing via `core/news.py` / existing briefing flow
    - [ ] Optional: generate LLM summary (Ollama) using existing streaming pipeline
    - [ ] Push to UI: dashboard card + toast; optionally TTS
  - [ ] Add GUI settings: enable/disable, time of day, categories/filters, speak vs silent
  - [ ] Ensure “exactly once per day” behavior (with timezone awareness)

- [ ] Integration mapping for remaining capabilities (post backbone work):
  - [ ] For each missing capability from your list, decide:
    - [ ] Path A: MCP server
    - [ ] Path B: direct Plia tool implementation
    - [ ] Path C: heavy ML/OS integration
  - [ ] Write a short capability→approach→needed deps/tools doc

- [ ] Testing/validation (must pass):
  - [ ] Smoke test basic chat/function routing still works
  - [ ] Smoke test multi-hop citations workflow still works (no citation/prompt regressions)
  - [ ] Smoke test MCP tool call works end-to-end (discovery + execution + response)
  - [ ] Redaction test:
    - [ ] Provide synthetic prompts with email/phone/api-key-like strings
    - [ ] Verify raw secrets do not appear in Ollama request payloads (add temporary debug gate if needed)
  - [ ] Scheduler test:
    - [ ] Verify digest triggers once and UI updates as expected

- [ ] Documentation updates:
  - [ ] Document `~/.plia/mcp.json` schema + example
  - [ ] Document MCP pruning behavior + diagnostics
  - [ ] Document redaction settings + examples of what gets redacted
  - [ ] Document scheduler settings + how to test it

- [ ] Final verification:
  - [ ] Run app startup without runtime/import crashes
  - [ ] Manually verify UI toggles apply as intended
  - [ ] Provide a short checklist of verified capabilities
