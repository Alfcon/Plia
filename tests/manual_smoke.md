# Multi-Agent System — Manual Smoke Checklist

Run after Phase 5. Requires Ollama running and the Plia app launched
(`python main.py`). The automated suite (`pytest tests/ -v`) must be green first.

## Creation — voice
- [ ] Say the wake word, then "create an agent that watches GitHub for related projects".
- [ ] Plia speaks the trigger question. Answer "scheduled".
- [ ] Plia asks cadence. Answer "every 6 hours".
- [ ] Plia asks persistence. Answer "persistent".
- [ ] Plia asks notify. Answer "communication log".
- [ ] Plia reads back the summary. Answer "yes".
- [ ] Plia confirms creation; the agent appears in the Active Agents tab → Live Agents section.

## Creation — chat
- [ ] In the chat tab, type "create an agent that summarises my emails".
- [ ] The CreationWizardDialog opens, pre-filled with the task.
- [ ] Walk through trigger / cadence-or-quota / persistence / notify / confirm.
- [ ] On confirm, the dialog closes and the agent appears in Live Agents.

## Controls (Active Agents tab → Live Agents)
- [ ] "▶ Run now" on a scheduled agent → a run starts; history row appears after it completes.
- [ ] "⏸ Pause" → status flips to paused; "▶ Resume" → status flips back to active.
- [ ] "⏹ Stop" → status flips to terminated; the row greys out but stays visible.
- [ ] "⚙ Edit" → LiveAgentEditorDialog opens; change cadence, save; subtitle updates.
- [ ] "🗑 Delete" → row disappears; the role YAML under ~/.plia_ai/roles/ is gone.
- [ ] Quota agent: subtitle shows "quota X/Y"; auto-terminates when the limit is reached.

## Reporting channels
- [ ] An agent with notify=tts → on run completion, Plia speaks a one-line summary.
- [ ] An agent with notify=toast_card → a toast appears top-right AND a card appears on the dashboard.
- [ ] An agent with notify=comm_log → an entry appears in the dashboard Communication Log.

## Persistence across restart
- [ ] Create one persistent agent and one session agent.
- [ ] Close Plia, reopen it.
- [ ] The persistent agent is still in Live Agents and re-armed (next-fire shown).
- [ ] The session agent is gone.
- [ ] If a persistent scheduled agent was overdue, it fires once shortly after launch (catch-up).

## Regression
- [ ] Normal chat still works (ask a plain question).
- [ ] Legacy "Custom Agents" section still shows prompt-only agents and Run/Delete still work.
- [ ] Voice weather / web search / desktop commands still work (not swallowed by the wizard intercept).
