"""
example_plugin.py — Reference Plia plugin.

Copy this file to ~/.plia_ai/plugins/example.py and restart Plia (or open
Settings → Plugins → Reload). Any top-level function named ``tool_*`` is
auto-registered as the agent-callable tool ``example:<short_name>``.

The contract for every tool function:
    def tool_<name>(params: dict) -> dict:
        return {"success": bool, "message": str, "data": Any | None}

Plia is forgiving — return anything dict-like and missing keys get sensible
defaults; return a non-dict and it'll be wrapped automatically.
"""

import random
from datetime import datetime


def tool_say_hello(params: dict) -> dict:
    """Greet someone by name. Params: {"name": str}."""
    name = (params or {}).get("name") or "world"
    greeting = f"Hello, {name}!"
    return {
        "success": True,
        "message": greeting,
        "data": {"greeting": greeting},
    }


def tool_random_fact(_params: dict) -> dict:
    """Return a random hardcoded fact (no network)."""
    facts = [
        "Octopuses have three hearts and blue blood.",
        "Honey never spoils — edible honey has been found in Egyptian tombs.",
        "Bananas are botanically berries; strawberries aren't.",
        "The Eiffel Tower can be 15 cm taller in summer due to thermal expansion.",
        "Wombat poop is cube-shaped.",
    ]
    fact = random.choice(facts)
    return {
        "success": True,
        "message": "Random fact",
        "data": {"fact": fact, "as_of": datetime.now().isoformat(timespec="seconds")},
    }


def tool_word_count(params: dict) -> dict:
    """Count words / chars in a string. Params: {"text": str}."""
    text = (params or {}).get("text") or ""
    if not isinstance(text, str):
        text = str(text)
    return {
        "success": True,
        "message": f"{len(text.split())} word(s), {len(text)} char(s)",
        "data": {
            "words": len(text.split()),
            "chars": len(text),
            "lines": len(text.splitlines()),
        },
    }
