"""preload_models() ordering tests.

Regression guard for the CUDA OOM race where the router and the Ollama
responder (qwen3:8b) were spawned in parallel threads, both grabbing VRAM
on a 7.62 GB card. Router load lost the race more often than not and
threw a CUDA OOM that left the global ``router`` at ``None`` — silently
disabling function calling for the rest of the session.

The fix loads the router synchronously first; only after it's resident
do the responder + TTS preload threads start.
"""

from __future__ import annotations

import time

import pytest


def test_router_finishes_before_responder_starts(monkeypatch):
    """Router load must complete strictly before the responder load runs.

    We stub the three heavy loaders, give the router a small sleep so a
    racy implementation would let the responder start during it, and
    assert the recorded timestamps respect the ordering.
    """
    from core import llm
    from core import tts as tts_mod

    events: list[tuple[str, float]] = []

    class _StubRouter:
        def __init__(self, *args, **kwargs):
            events.append(("router_start", time.monotonic()))
            time.sleep(0.05)
            events.append(("router_done", time.monotonic()))

    monkeypatch.setattr("core.router.FunctionGemmaRouter", _StubRouter)

    class _StubResponse:
        status_code = 200

    def _post(*a, **kw):
        events.append(("responder", time.monotonic()))
        return _StubResponse()

    monkeypatch.setattr(llm.http_session, "post", _post)
    monkeypatch.setattr(tts_mod.tts, "initialize",
                        lambda: events.append(("voice", time.monotonic())))

    # Make sure the global router is reset so load_router actually runs.
    monkeypatch.setattr(llm, "router", None)

    llm.preload_models()

    names = [n for n, _ in events]
    assert names[0] == "router_start", names
    assert "router_done" in names, names

    t_router_done = next(t for n, t in events if n == "router_done")
    t_responder = next((t for n, t in events if n == "responder"), None)
    t_voice = next((t for n, t in events if n == "voice"), None)

    assert t_responder is not None, "responder thread never ran"
    assert t_voice is not None, "voice thread never ran"

    # The whole point of the fix: responder/voice may not start until the
    # router is fully resident. A parallel implementation would have one
    # of these timestamps land *during* the router's 50 ms sleep.
    assert t_responder >= t_router_done, (
        f"responder ran before router finished: "
        f"router_done={t_router_done:.4f}, responder={t_responder:.4f}"
    )
    assert t_voice >= t_router_done, (
        f"voice ran before router finished: "
        f"router_done={t_router_done:.4f}, voice={t_voice:.4f}"
    )
