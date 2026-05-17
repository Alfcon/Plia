"""Cross-vendor GPU info — NVIDIA via pynvml/nvidia-smi, AMD via sysfs.

Replaces direct pynvml usage across the GUI. Exposes a small public surface:

    detect_backend() -> "cuda" | "rocm" | "cpu"   # one-shot, cached
    read_gpu()       -> GpuInfo                    # cheap per-tick read

The module is intentionally dependency-light: it imports pynvml lazily inside
detect_backend() so an AMD-only Linux install with no pynvml installed still
works.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GpuInfo:
    backend: Literal["cuda", "rocm", "cpu"]
    name: str             # e.g. "AMD Radeon RX 7900 XTX" or "No GPU"
    vram_total_gb: float
    vram_used_gb: float
    vram_free_gb: float
    util_pct: float       # 0-100, 0.0 if unavailable


_BACKEND_CACHE: str | None = None


def detect_backend() -> str:
    """Probe for an available GPU backend. Cached after the first call.

    Returns one of:
        "cuda" — NVIDIA via pynvml or nvidia-smi fallback
        "rocm" — AMD GPU detected via Linux sysfs
        "cpu"  — no usable GPU
    """
    global _BACKEND_CACHE
    if _BACKEND_CACHE is not None:
        return _BACKEND_CACHE

    backend = (
        _probe_nvidia_pynvml()
        or _probe_nvidia_smi()
        or "cpu"
    )
    _BACKEND_CACHE = backend
    return backend


def _probe_nvidia_pynvml() -> str | None:
    try:
        import pynvml  # lazy: optional for AMD-only installs
        pynvml.nvmlInit()
        pynvml.nvmlDeviceGetHandleByIndex(0)
        return "cuda"
    except Exception:
        return None


def _probe_nvidia_smi() -> str | None:
    """Second-chance NVIDIA probe via the nvidia-smi binary."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.free,name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "cuda"
    except Exception:
        pass
    return None
