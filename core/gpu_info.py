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
