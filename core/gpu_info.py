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
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class GpuInfo:
    backend: Literal["cuda", "rocm", "cpu"]
    name: str             # e.g. "AMD Radeon RX 7900 XTX" or "No GPU"
    vram_total_gb: float
    vram_used_gb: float
    vram_free_gb: float
    util_pct: float       # 0-100, 0.0 if unavailable


_SYSFS_DRM_ROOT = Path("/sys/class/drm")
_AMD_PCI_VENDOR = "0x1002"

# Cached after detect_backend so read_gpu() doesn't re-scan.
# This is the `cardN` directory itself, NOT `cardN/device` — readers must
# descend into "device" to access mem_info_vram_*, gpu_busy_percent, etc.
_AMD_CARD_PATH: Path | None = None

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
        or _probe_amd_sysfs()
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


def _probe_amd_sysfs() -> str | None:
    """Scan /sys/class/drm for AMD cards. Picks the largest-VRAM card.

    Side effect: caches the chosen card path in _AMD_CARD_PATH so read_gpu()
    can hit it directly.
    """
    global _AMD_CARD_PATH

    if not _SYSFS_DRM_ROOT.exists():
        return None

    candidates: list[tuple[int, Path]] = []
    for card in sorted(_SYSFS_DRM_ROOT.glob("card*")):
        device = card / "device"
        vendor_file = device / "vendor"
        vram_file = device / "mem_info_vram_total"
        try:
            if vendor_file.read_text().strip() != _AMD_PCI_VENDOR:
                continue
            vram_total = int(vram_file.read_text().strip())
        except (OSError, ValueError):
            continue
        if vram_total <= 0:
            continue
        candidates.append((vram_total, device))

    if not candidates:
        return None

    candidates.sort(key=lambda t: t[0], reverse=True)
    _AMD_CARD_PATH = candidates[0][1].parent
    return "rocm"


_EMPTY_INFO = GpuInfo(
    backend="cpu", name="No GPU",
    vram_total_gb=0.0, vram_used_gb=0.0, vram_free_gb=0.0, util_pct=0.0,
)


def read_gpu() -> GpuInfo:
    """Cheap per-tick read. Returns empty info on any error."""
    backend = detect_backend()
    if backend == "cuda":
        return _read_cuda()
    if backend == "rocm":
        return _read_rocm()
    return _EMPTY_INFO


def _read_cuda() -> GpuInfo:
    try:
        import pynvml
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mi = pynvml.nvmlDeviceGetMemoryInfo(h)
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        raw_name = pynvml.nvmlDeviceGetName(h)
        name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else raw_name
        gb = 1024 ** 3
        return GpuInfo(
            backend="cuda",
            name=name,
            vram_total_gb=round(mi.total / gb, 2),
            vram_used_gb=round(mi.used / gb, 2),
            vram_free_gb=round(mi.free / gb, 2),
            util_pct=float(util.gpu),
        )
    except Exception:
        return GpuInfo(
            backend="cuda", name="NVIDIA GPU",
            vram_total_gb=0.0, vram_used_gb=0.0, vram_free_gb=0.0, util_pct=0.0,
        )


def _read_rocm() -> GpuInfo:
    """Read VRAM/util from the cached AMD card sysfs path.

    _AMD_CARD_PATH points at the `cardN` directory; per-tick sysfs files
    live one level down in `cardN/device/`.
    """
    if _AMD_CARD_PATH is None:
        return GpuInfo(
            backend="rocm", name="AMD GPU",
            vram_total_gb=0.0, vram_used_gb=0.0, vram_free_gb=0.0, util_pct=0.0,
        )

    device = _AMD_CARD_PATH / "device"

    def _read_int(name: str) -> int:
        try:
            return int((device / name).read_text().strip())
        except (OSError, ValueError):
            return 0

    def _read_text(name: str) -> str:
        try:
            return (device / name).read_text().strip()
        except OSError:
            return ""

    gb = 1024 ** 3
    total_b = _read_int("mem_info_vram_total")
    used_b = _read_int("mem_info_vram_used")
    util = float(_read_int("gpu_busy_percent"))
    name = _read_text("product_name") or "AMD GPU"

    return GpuInfo(
        backend="rocm",
        name=name,
        vram_total_gb=round(total_b / gb, 2) if total_b else 0.0,
        vram_used_gb=round(used_b / gb, 2),
        vram_free_gb=round(max(total_b - used_b, 0) / gb, 2),
        util_pct=util,
    )


def _chosen_amd_card_path() -> Path | None:
    """Test helper. Returns the cached AMD card path (cardN, not cardN/device)."""
    return _AMD_CARD_PATH
