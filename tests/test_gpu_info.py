"""Tests for core.gpu_info — cross-vendor GPU detection."""

import sys
import types
from dataclasses import FrozenInstanceError

import pytest


def test_gpuinfo_dataclass_fields_and_frozen():
    from core.gpu_info import GpuInfo

    info = GpuInfo(
        backend="cpu",
        name="No GPU",
        vram_total_gb=0.0,
        vram_used_gb=1.5,
        vram_free_gb=2.5,
        util_pct=42.0,
    )
    assert info.backend == "cpu"
    assert info.name == "No GPU"
    assert info.vram_total_gb == 0.0
    assert info.vram_used_gb == 1.5
    assert info.vram_free_gb == 2.5
    assert info.util_pct == 42.0

    with pytest.raises(FrozenInstanceError):
        info.backend = "cuda"  # type: ignore[misc]


@pytest.fixture
def reset_gpu_info(monkeypatch):
    """Reset the module-level backend cache between tests."""
    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_BACKEND_CACHE", None, raising=False)
    yield
    monkeypatch.setattr(gpu_info, "_BACKEND_CACHE", None, raising=False)


def _make_fake_pynvml(*, init_ok=True, handle_ok=True):
    """Return a fake pynvml module suitable for sys.modules patching."""
    mod = types.ModuleType("pynvml")

    class NVMLError(Exception):
        pass

    mod.NVMLError = NVMLError

    def nvmlInit():
        if not init_ok:
            raise NVMLError("no driver")

    def nvmlDeviceGetHandleByIndex(idx):
        if not handle_ok:
            raise NVMLError("no device")
        return object()

    def nvmlShutdown():
        pass

    def nvmlDeviceGetMemoryInfo(_h):
        m = types.SimpleNamespace(
            total=24 * 1024**3,
            used=4 * 1024**3,
            free=20 * 1024**3,
        )
        return m

    def nvmlDeviceGetUtilizationRates(_h):
        return types.SimpleNamespace(gpu=42)

    def nvmlDeviceGetName(_h):
        return "NVIDIA GeForce RTX 4090"

    mod.nvmlInit = nvmlInit
    mod.nvmlDeviceGetHandleByIndex = nvmlDeviceGetHandleByIndex
    mod.nvmlShutdown = nvmlShutdown
    mod.nvmlDeviceGetMemoryInfo = nvmlDeviceGetMemoryInfo
    mod.nvmlDeviceGetUtilizationRates = nvmlDeviceGetUtilizationRates
    mod.nvmlDeviceGetName = nvmlDeviceGetName
    return mod


def test_detect_backend_returns_cuda_when_pynvml_ok(monkeypatch, reset_gpu_info):
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml())

    from core.gpu_info import detect_backend
    assert detect_backend() == "cuda"


def test_detect_backend_caches_result(monkeypatch, reset_gpu_info):
    """Second call must hit the cache, not re-probe pynvml."""
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml())

    from core.gpu_info import detect_backend
    first = detect_backend()

    # Make pynvml init fail on a fresh probe — cache must still return "cuda".
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    second = detect_backend()

    assert first == second == "cuda"
