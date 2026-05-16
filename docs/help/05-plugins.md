# Plugins

You can extend Plia by writing a small Python file. Drop it in `~/.plia_ai/plugins/` and any function whose name starts with `tool_` becomes an agent-callable tool.

## The contract

```python
def tool_<name>(params: dict) -> dict:
    return {
        "success": bool,        # True if the call succeeded
        "message": str,         # one-line human summary
        "data":    Any | None,  # whatever you want — agents see this
    }
```

The plugin's filename (without `.py`) is the namespace. A function `tool_say_hello` in `~/.plia_ai/plugins/example.py` becomes the tool `example:say_hello`.

## A minimal example

```python
# ~/.plia_ai/plugins/example.py

def tool_say_hello(params):
    """Greet someone by name. Params: {"name": str}."""
    name = (params or {}).get("name") or "world"
    return {
        "success": True,
        "message": f"Hello, {name}!",
        "data": {"greeting": f"Hello, {name}!"},
    }
```

Restart Plia. In any live agent's editor you'll see **example:say_hello** in the Tools list (cyan-tinted — built-ins are plain text, destructive built-ins are red, plugins are cyan). Tick it, save, and the agent's LLM can call it.

## Plia is forgiving

- Plugin functions don't have to return the full dict shape. Plia wraps non-dict returns with sensible defaults.
- If a function raises, Plia catches the exception and returns `success: False` with the message — the agent gets a useful error, the rest of the run continues.
- A syntax error in one plugin won't block other plugins from loading.

## Discovery

The `list_plia_features` tool returns every tool an agent can call, **including plugin tools**. Manager-style agents can use this to discover and route to plugins dynamically.

## Reference plugin

`docs/example_plugin.py` (in the Plia repo) is the canonical reference. Copy it to `~/.plia_ai/plugins/example.py` and you'll have three working tools right away: `example:say_hello`, `example:random_fact`, `example:word_count`.

## When to use plugins vs MCP

| Plugin (Python file) | MCP server |
|---|---|
| Lives in your Plia install, calls Python directly | Subprocess speaking a protocol, language-agnostic |
| Fast (no IPC) | Higher overhead but completely isolated |
| Trivial for small custom tools | Better for sharing or for using community servers |
| Reload requires Plia restart | Hot reload via the MCP Servers tab |

Use plugins for quick one-off helpers; use MCP for community/installed integrations like GitHub, Slack, Notion, etc.
