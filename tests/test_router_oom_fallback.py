"""FunctionGemmaRouter must retry on CPU when the CUDA load OOMs.

Defense-in-depth on top of the serialize-preload fix in core/llm.py:
even with the router loading first, an external process (or a
second-instance restart) can hold VRAM and starve the load. Rather than
crashing into router=None — which silently disables function calling
for the whole session — fall back to CPU + float32 and keep routing
working, just slower.

Mirrors the pattern in core/wake_trainer.py:367-374.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def stub_model_classes(monkeypatch):
    """Stub HF tokenizer + causal-LM loaders so the test never touches disk.

    Returns a dict the test mutates to control the model loader's behaviour
    (e.g. raise OOM on the first call).
    """
    import torch
    from core import router as router_mod

    state = {
        "model_calls": [],
        "raise_oom_first": True,
    }

    class _StubTokenizer:
        def __init__(self):
            self.pad_token_id = 0

        @classmethod
        def from_pretrained(cls, path):
            return cls()

    class _StubModel:
        def __init__(self, device, dtype):
            import torch as _t
            self.device = _t.device(device)
            self.dtype = dtype

        def eval(self):
            return self

        @classmethod
        def from_pretrained(cls, path, torch_dtype, device_map):
            state["model_calls"].append({"device_map": device_map, "dtype": torch_dtype})
            if state["raise_oom_first"] and device_map == "cuda" and len(state["model_calls"]) == 1:
                # PyTorch ≥ 2.0 exposes this concrete subclass; otherwise the
                # router also accepts a RuntimeError with "out of memory" in
                # the message.
                raise torch.cuda.OutOfMemoryError("CUDA out of memory. Tried to allocate 200 MiB.")
            return cls(device_map, torch_dtype)

    # Patch the transformers symbols the router lazy-imports inside __init__.
    import transformers
    monkeypatch.setattr(transformers, "AutoTokenizer", _StubTokenizer)
    monkeypatch.setattr(transformers, "AutoModelForCausalLM", _StubModel)
    monkeypatch.setattr(router_mod, "ensure_model_available", lambda p: p)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: None)

    return state


def test_router_retries_on_cpu_after_cuda_oom(stub_model_classes):
    from core.router import FunctionGemmaRouter

    r = FunctionGemmaRouter(model_path="/tmp/fake_router", compile_model=False)

    calls = stub_model_classes["model_calls"]
    assert len(calls) == 2, f"expected 2 load attempts (cuda then cpu), got {calls}"
    assert calls[0]["device_map"] == "cuda"
    assert calls[1]["device_map"] == "cpu"

    import torch
    assert calls[1]["dtype"] == torch.float32
    assert r.model.device.type == "cpu"


def test_router_does_not_retry_on_non_oom_failures(monkeypatch):
    """If the first load fails for some reason other than OOM, the router
    must surface the error — silently retrying on CPU would hide bugs."""
    import torch
    from core import router as router_mod

    class _StubTokenizer:
        pad_token_id = 0

        @classmethod
        def from_pretrained(cls, path):
            return cls()

    class _StubModel:
        @classmethod
        def from_pretrained(cls, path, torch_dtype, device_map):
            raise RuntimeError("model weights corrupted")

    import transformers
    monkeypatch.setattr(transformers, "AutoTokenizer", _StubTokenizer)
    monkeypatch.setattr(transformers, "AutoModelForCausalLM", _StubModel)
    monkeypatch.setattr(router_mod, "ensure_model_available", lambda p: p)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    with pytest.raises(RuntimeError, match="corrupted"):
        router_mod.FunctionGemmaRouter(model_path="/tmp/fake_router", compile_model=False)
