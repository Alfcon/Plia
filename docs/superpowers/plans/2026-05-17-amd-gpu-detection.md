# AMD GPU Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-parity AMD GPU detection (Linux / ROCm) across all four `pynvml` call sites in the GUI, with no new pip dependencies.

**Architecture:** A new `core/gpu_info.py` module exposes a single `GpuInfo` dataclass and two functions — `detect_backend()` (one-shot, cached) and `read_gpu()` (cheap per-tick). NVIDIA detection still uses `pynvml` then `nvidia-smi` fallback; AMD detection uses sysfs reads under `/sys/class/drm/cardN/device/`. All four GUI call sites are migrated to use this module.

**Tech Stack:** Python 3.11+, `pynvml` (existing), `pytest` (existing). No new dependencies. Linux sysfs (`/sys/class/drm/`) for AMD probing. Optional `lspci` subprocess for AMD GPU name resolution.

**Spec:** `docs/superpowers/specs/2026-05-17-amd-gpu-detection-design.md`

---

## File Structure

**New files:**

- `core/gpu_info.py` (~140 lines) — `GpuInfo` dataclass + `detect_backend()` + `read_gpu()` + private sysfs helpers
- `tests/test_gpu_info.py` (~200 lines) — full coverage of the four backend selection branches, per-tick reads, caching, and error fallbacks

**Modified files:**

- `gui/tabs/model_browser.py` — replace `HardwareInfo.detect()` body (lines 215–259) with a call to `gpu_info.read_gpu()` / `gpu_info.detect_backend()`
- `gui/components/system_monitor.py` — replace top-level `pynvml` import block (lines 14–20) and the worker's GPU block (lines 47–62) with `gpu_info.read_gpu()`; rename `GPU_AVAILABLE` to reflect new semantics
- `gui/tabs/dashboard.py` — replace top-level `pynvml` import block (lines 43–48), the `_MonitorWorker.collect` GPU block (lines 172–185), and the `_cmd_status` GPU block (lines 619–628), all using `gpu_info.read_gpu()`
- `core/agent_builder.py` — line 415 docstring tweak so generated agents are pointed at `core.gpu_info` instead of `pynvml`

---

## Task 1: Skeleton module + GpuInfo dataclass

**Files:**
- Create: `core/gpu_info.py`
- Create: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gpu_info.py
"""Tests for core.gpu_info — cross-vendor GPU detection."""

import pytest


def test_gpuinfo_dataclass_fields_and_frozen():
    from core.gpu_info import GpuInfo

    info = GpuInfo(
        backend="cpu",
        name="No GPU",
        vram_total_gb=0.0,
        vram_used_gb=0.0,
        vram_free_gb=0.0,
        util_pct=0.0,
    )
    assert info.backend == "cpu"
    assert info.name == "No GPU"
    assert info.vram_total_gb == 0.0

    # frozen — should raise on assignment
    with pytest.raises(Exception):
        info.backend = "cuda"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gpu_info.py::test_gpuinfo_dataclass_fields_and_frozen -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.gpu_info'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/gpu_info.py
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


@dataclass(frozen=True)
class GpuInfo:
    backend: str          # "cuda" | "rocm" | "cpu"
    name: str             # e.g. "AMD Radeon RX 7900 XTX" or "No GPU"
    vram_total_gb: float
    vram_used_gb: float
    vram_free_gb: float
    util_pct: float       # 0-100, 0.0 if unavailable
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gpu_info.py::test_gpuinfo_dataclass_fields_and_frozen -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/gpu_info.py tests/test_gpu_info.py
git commit -m "feat(gpu): add GpuInfo dataclass and module skeleton"
```

---

## Task 2: detect_backend() — NVIDIA via pynvml

**Files:**
- Modify: `core/gpu_info.py`
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gpu_info.py`:

```python
import sys
import types


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gpu_info.py::test_detect_backend_returns_cuda_when_pynvml_ok -v`
Expected: FAIL with `ImportError: cannot import name 'detect_backend'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/gpu_info.py`:

```python
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

    backend = _probe_nvidia_pynvml() or "cpu"
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gpu_info.py::test_detect_backend_returns_cuda_when_pynvml_ok -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/gpu_info.py tests/test_gpu_info.py
git commit -m "feat(gpu): detect_backend NVIDIA pynvml probe + caching"
```

---

## Task 3: detect_backend() — nvidia-smi fallback

**Files:**
- Modify: `core/gpu_info.py`
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gpu_info.py`:

```python
def test_detect_backend_falls_back_to_nvidia_smi(monkeypatch, reset_gpu_info):
    # No pynvml available
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))

    import subprocess

    def fake_run(cmd, *args, **kwargs):
        if "nvidia-smi" in cmd[0]:
            return types.SimpleNamespace(
                returncode=0,
                stdout="20480, NVIDIA GeForce RTX 4090\n",
                stderr="",
            )
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(subprocess, "run", fake_run)

    from core.gpu_info import detect_backend
    assert detect_backend() == "cuda"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gpu_info.py::test_detect_backend_falls_back_to_nvidia_smi -v`
Expected: FAIL — currently returns `"cpu"` because the nvidia-smi path is not implemented yet.

- [ ] **Step 3: Write minimal implementation**

In `core/gpu_info.py`, change `detect_backend` and add `_probe_nvidia_smi`:

```python
def detect_backend() -> str:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gpu_info.py::test_detect_backend_falls_back_to_nvidia_smi -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/gpu_info.py tests/test_gpu_info.py
git commit -m "feat(gpu): nvidia-smi second-chance probe"
```

---

## Task 4: detect_backend() — AMD sysfs scan

**Files:**
- Modify: `core/gpu_info.py`
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gpu_info.py`:

```python
def _make_amd_card(path, vendor="0x1002", vram_total=24 * 1024**3):
    """Create a fake /sys/class/drm/cardN/device/ tree."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "vendor").write_text(vendor + "\n")
    (path / "mem_info_vram_total").write_text(f"{vram_total}\n")
    (path / "mem_info_vram_used").write_text("0\n")
    (path / "gpu_busy_percent").write_text("0\n")


def test_detect_backend_returns_rocm_for_amd_sysfs(
    monkeypatch, reset_gpu_info, tmp_path
):
    # Force NVIDIA probes to fail
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    sysfs_root = tmp_path / "drm"
    _make_amd_card(sysfs_root / "card0" / "device")

    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", sysfs_root)

    assert gpu_info.detect_backend() == "rocm"


def test_detect_backend_picks_largest_vram_amd_card(
    monkeypatch, reset_gpu_info, tmp_path
):
    """On hybrid iGPU + dGPU systems, prefer the card with more VRAM."""
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    sysfs_root = tmp_path / "drm"
    # iGPU: 512 MB
    _make_amd_card(sysfs_root / "card0" / "device", vram_total=512 * 1024**2)
    # dGPU: 24 GB
    _make_amd_card(sysfs_root / "card1" / "device", vram_total=24 * 1024**3)

    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", sysfs_root)

    assert gpu_info.detect_backend() == "rocm"
    # The chosen card index should be 1 (the dGPU)
    assert gpu_info._chosen_amd_card_path().name == "card1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gpu_info.py::test_detect_backend_returns_rocm_for_amd_sysfs tests/test_gpu_info.py::test_detect_backend_picks_largest_vram_amd_card -v`
Expected: FAIL — `_SYSFS_DRM_ROOT` and `_chosen_amd_card_path` don't exist yet; backend returns "cpu".

- [ ] **Step 3: Write minimal implementation**

Add to `core/gpu_info.py` (near the top, after imports):

```python
from pathlib import Path

_SYSFS_DRM_ROOT = Path("/sys/class/drm")
_AMD_PCI_VENDOR = "0x1002"

# Cached after detect_backend so read_gpu() doesn't re-scan.
_AMD_CARD_PATH: Path | None = None
```

Add a private helper and wire it into the cascade:

```python
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
    _AMD_CARD_PATH = candidates[0][1]
    return "rocm"


def _chosen_amd_card_path() -> Path | None:
    """Test helper. Returns the cached AMD card device path."""
    return _AMD_CARD_PATH
```

Update the cascade in `detect_backend`:

```python
def detect_backend() -> str:
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
```

The fixture should also reset `_AMD_CARD_PATH`. Update `reset_gpu_info` in the test file:

```python
@pytest.fixture
def reset_gpu_info(monkeypatch):
    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_BACKEND_CACHE", None, raising=False)
    monkeypatch.setattr(gpu_info, "_AMD_CARD_PATH", None, raising=False)
    yield
    monkeypatch.setattr(gpu_info, "_BACKEND_CACHE", None, raising=False)
    monkeypatch.setattr(gpu_info, "_AMD_CARD_PATH", None, raising=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gpu_info.py -v`
Expected: All four tests so far PASS.

- [ ] **Step 5: Commit**

```bash
git add core/gpu_info.py tests/test_gpu_info.py
git commit -m "feat(gpu): AMD sysfs scan + dGPU-over-iGPU selection"
```

---

## Task 5: detect_backend() — caching + CPU fallback

**Files:**
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gpu_info.py`:

```python
def test_detect_backend_returns_cpu_when_nothing(
    monkeypatch, reset_gpu_info, tmp_path
):
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    empty_root = tmp_path / "drm-empty"
    empty_root.mkdir()
    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", empty_root)

    assert gpu_info.detect_backend() == "cpu"


def test_detect_backend_is_cached(monkeypatch, reset_gpu_info):
    """Second call must hit the cache, not re-run probes."""
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml())

    from core import gpu_info
    assert gpu_info.detect_backend() == "cuda"

    # Now break pynvml. A re-probe would now return "cpu". The cache
    # should keep returning "cuda".
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    assert gpu_info.detect_backend() == "cuda"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_gpu_info.py -v`
Expected: All tests PASS (logic was implemented in Tasks 2-4; this task adds coverage only).

- [ ] **Step 3: Commit**

```bash
git add tests/test_gpu_info.py
git commit -m "test(gpu): cover CPU fallback and backend caching"
```

---

## Task 6: read_gpu() — NVIDIA path

**Files:**
- Modify: `core/gpu_info.py`
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gpu_info.py`:

```python
def test_read_gpu_cuda(monkeypatch, reset_gpu_info):
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml())

    from core.gpu_info import read_gpu
    info = read_gpu()
    assert info.backend == "cuda"
    assert info.name == "NVIDIA GeForce RTX 4090"
    assert info.vram_total_gb == pytest.approx(24.0, abs=0.1)
    assert info.vram_used_gb == pytest.approx(4.0, abs=0.1)
    assert info.vram_free_gb == pytest.approx(20.0, abs=0.1)
    assert info.util_pct == 42.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gpu_info.py::test_read_gpu_cuda -v`
Expected: FAIL — `read_gpu` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add to `core/gpu_info.py`:

```python
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
    # Stub for now — implemented in Task 7
    return GpuInfo(
        backend="rocm", name="AMD GPU",
        vram_total_gb=0.0, vram_used_gb=0.0, vram_free_gb=0.0, util_pct=0.0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gpu_info.py::test_read_gpu_cuda -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/gpu_info.py tests/test_gpu_info.py
git commit -m "feat(gpu): read_gpu cuda path with pynvml"
```

---

## Task 7: read_gpu() — AMD sysfs path

**Files:**
- Modify: `core/gpu_info.py`
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gpu_info.py`:

```python
def test_read_gpu_rocm_basic(monkeypatch, reset_gpu_info, tmp_path):
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    sysfs_root = tmp_path / "drm"
    device = sysfs_root / "card0" / "device"
    device.mkdir(parents=True)
    (device / "vendor").write_text("0x1002\n")
    (device / "mem_info_vram_total").write_text(f"{24 * 1024**3}\n")
    (device / "mem_info_vram_used").write_text(f"{8 * 1024**3}\n")
    (device / "gpu_busy_percent").write_text("55\n")
    (device / "product_name").write_text("AMD Radeon RX 7900 XTX\n")

    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", sysfs_root)

    info = gpu_info.read_gpu()
    assert info.backend == "rocm"
    assert info.name == "AMD Radeon RX 7900 XTX"
    assert info.vram_total_gb == pytest.approx(24.0, abs=0.1)
    assert info.vram_used_gb == pytest.approx(8.0, abs=0.1)
    assert info.vram_free_gb == pytest.approx(16.0, abs=0.1)
    assert info.util_pct == 55.0


def test_read_gpu_rocm_handles_missing_files(
    monkeypatch, reset_gpu_info, tmp_path
):
    """If mem_info_vram_used or gpu_busy_percent are missing/unreadable,
    return zeros for those fields without raising."""
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    sysfs_root = tmp_path / "drm"
    device = sysfs_root / "card0" / "device"
    device.mkdir(parents=True)
    (device / "vendor").write_text("0x1002\n")
    (device / "mem_info_vram_total").write_text(f"{16 * 1024**3}\n")
    # NB: mem_info_vram_used and gpu_busy_percent intentionally absent
    # No product_name either — should fall through to "AMD GPU"

    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", sysfs_root)

    info = gpu_info.read_gpu()
    assert info.backend == "rocm"
    assert info.vram_total_gb == pytest.approx(16.0, abs=0.1)
    assert info.vram_used_gb == 0.0
    assert info.util_pct == 0.0
    assert info.name == "AMD GPU"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_gpu_info.py::test_read_gpu_rocm_basic tests/test_gpu_info.py::test_read_gpu_rocm_handles_missing_files -v`
Expected: FAIL — current `_read_rocm()` returns a stub with all zeros.

- [ ] **Step 3: Write the real `_read_rocm` implementation**

Replace the stub `_read_rocm` in `core/gpu_info.py` with:

```python
def _read_rocm() -> GpuInfo:
    """Read VRAM/util from the cached AMD card sysfs path."""
    card = _AMD_CARD_PATH
    if card is None:
        return GpuInfo(
            backend="rocm", name="AMD GPU",
            vram_total_gb=0.0, vram_used_gb=0.0, vram_free_gb=0.0, util_pct=0.0,
        )

    def _read_int(name: str) -> int:
        try:
            return int((card / name).read_text().strip())
        except (OSError, ValueError):
            return 0

    def _read_text(name: str) -> str:
        try:
            return (card / name).read_text().strip()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_gpu_info.py -v`
Expected: All tests so far PASS.

- [ ] **Step 5: Commit**

```bash
git add core/gpu_info.py tests/test_gpu_info.py
git commit -m "feat(gpu): read_gpu rocm path via sysfs with graceful fallbacks"
```

---

## Task 8: read_gpu() — CPU path and full-stack integration test

**Files:**
- Modify: `tests/test_gpu_info.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gpu_info.py`:

```python
def test_read_gpu_cpu_returns_empty(
    monkeypatch, reset_gpu_info, tmp_path
):
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml(init_ok=False))
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""),
    )

    empty_root = tmp_path / "drm-empty"
    empty_root.mkdir()
    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", empty_root)

    info = gpu_info.read_gpu()
    assert info.backend == "cpu"
    assert info.name == "No GPU"
    assert info.vram_total_gb == 0.0


def test_nvidia_wins_when_both_present(
    monkeypatch, reset_gpu_info, tmp_path
):
    """When both NVIDIA (pynvml) and AMD (sysfs) are present, NVIDIA wins
    to preserve today's precedence."""
    monkeypatch.setitem(sys.modules, "pynvml", _make_fake_pynvml())

    sysfs_root = tmp_path / "drm"
    _make_amd_card(sysfs_root / "card0" / "device")

    from core import gpu_info
    monkeypatch.setattr(gpu_info, "_SYSFS_DRM_ROOT", sysfs_root)

    assert gpu_info.detect_backend() == "cuda"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_gpu_info.py -v`
Expected: All tests PASS — these exercise behaviour already implemented.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gpu_info.py
git commit -m "test(gpu): cover CPU read path and NVIDIA-wins-on-hybrid"
```

---

## Task 9: Migrate `gui/tabs/model_browser.py` HardwareInfo.detect

**Files:**
- Modify: `gui/tabs/model_browser.py:213-259`

- [ ] **Step 1: Read the current implementation**

Read `gui/tabs/model_browser.py` lines 213-259 to confirm the structure of `HardwareInfo.detect()` before editing. The current method sets `self.ram_gb`, `self.cpu_cores`, `self.vram_gb`, `self.gpu_name`, `self.backend`.

- [ ] **Step 2: Replace the pynvml + nvidia-smi blocks**

In `gui/tabs/model_browser.py`, replace lines 213-259 (`class HardwareInfo:` through end of `detect`) with:

```python
# ---------------------------------------------------------------------------
# Hardware detection — delegates GPU probing to core.gpu_info, which handles
# NVIDIA (pynvml / nvidia-smi) and AMD (sysfs on Linux) uniformly.
# ---------------------------------------------------------------------------
class HardwareInfo:
    def __init__(self):
        self.ram_gb    = 0.0
        self.vram_gb   = 0.0
        self.gpu_name  = "Unknown"
        self.backend   = "cpu_x86"
        self.cpu_cores = 0

    def detect(self) -> "HardwareInfo":
        mem = psutil.virtual_memory()
        self.ram_gb    = round(mem.available / (1024 ** 3), 1)
        self.cpu_cores = psutil.cpu_count(logical=False) or 2

        from core import gpu_info
        info = gpu_info.read_gpu()
        self.vram_gb  = info.vram_free_gb
        self.gpu_name = info.name if info.backend != "cpu" else "Unknown"
        if info.backend in ("cuda", "rocm"):
            self.backend = info.backend
        else:
            import platform
            self.backend = (
                "cpu_arm"
                if platform.machine().lower() in ("arm64", "aarch64")
                else "cpu_x86"
            )

        return self
```

Note: the `BACKEND_SPEED` table at line 139 already contains `"rocm": 180`, so no further changes are needed for scoring to work.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `pytest -q`
Expected: All existing tests PASS plus the new `tests/test_gpu_info.py` tests. Confirm 188+ tests pass (188 was the pre-change baseline per memory).

- [ ] **Step 4: Smoke-test imports**

Run: `python -c "from gui.tabs.model_browser import HardwareInfo; print(HardwareInfo().detect().backend)"`
Expected: Prints `cuda`, `rocm`, `cpu_x86`, or `cpu_arm` depending on the test machine. No exceptions.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/model_browser.py
git commit -m "refactor(gpu): migrate model_browser HardwareInfo to core.gpu_info"
```

---

## Task 10: Migrate `gui/components/system_monitor.py`

**Files:**
- Modify: `gui/components/system_monitor.py:14-20, 47-62, 164, 175, 332-337`

- [ ] **Step 1: Replace the top-level pynvml import block**

In `gui/components/system_monitor.py`, replace lines 14-20:

```python
# Try to import pynvml for GPU monitoring
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False
```

with:

```python
# GPU monitoring is delegated to core.gpu_info (cross-vendor: NVIDIA + AMD)
from core import gpu_info
GPU_AVAILABLE = gpu_info.detect_backend() != "cpu"
```

- [ ] **Step 2: Replace the worker's GPU block**

In the same file, replace lines 46-62 (the `# GPU` comment through the closing `else: stats['gpu'] = None`) with:

```python
            # GPU (NVIDIA via pynvml, AMD via sysfs — both handled by core.gpu_info)
            if GPU_AVAILABLE:
                try:
                    info = gpu_info.read_gpu()
                    if info.vram_total_gb > 0:
                        stats['gpu'] = {
                            'percent': info.util_pct,
                            'vram_used': info.vram_used_gb,
                            'vram_total': info.vram_total_gb,
                            'vram_percent':
                                (info.vram_used_gb / info.vram_total_gb) * 100,
                        }
                    else:
                        stats['gpu'] = None
                except Exception:
                    stats['gpu'] = None
            else:
                stats['gpu'] = None
```

- [ ] **Step 3: Run lint / sanity checks**

Run: `python -c "from gui.components.system_monitor import GPU_AVAILABLE, MonitorWorker; print(GPU_AVAILABLE)"`
Expected: Prints `True` or `False` without exception.

Run: `pytest -q`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add gui/components/system_monitor.py
git commit -m "refactor(gpu): migrate title-bar SystemMonitor to core.gpu_info"
```

---

## Task 11: Migrate `gui/tabs/dashboard.py` (two call sites)

**Files:**
- Modify: `gui/tabs/dashboard.py:42-48, 172-185, 619-628`

- [ ] **Step 1: Replace the top-level pynvml block**

In `gui/tabs/dashboard.py`, replace lines 42-48:

```python
# ── GPU monitoring ────────────────────────────────────────────
try:
    import pynvml
    pynvml.nvmlInit()
    _GPU_OK = True
except Exception:
    _GPU_OK = False
```

with:

```python
# ── GPU monitoring (cross-vendor: NVIDIA via pynvml, AMD via sysfs) ──
from core import gpu_info
_GPU_OK = gpu_info.detect_backend() != "cpu"
```

- [ ] **Step 2: Replace the `_MonitorWorker.collect` GPU block**

Replace lines 172-185 (the `if _GPU_OK:` block in `collect`) with:

```python
            if _GPU_OK:
                try:
                    info = gpu_info.read_gpu()
                    if info.vram_total_gb > 0:
                        data["gpu"]  = info.util_pct
                        data["vram"] = (
                            (info.vram_used_gb / info.vram_total_gb) * 100
                        )
                        data["vram_gb"] = (
                            f"{info.vram_used_gb:.1f} / "
                            f"{info.vram_total_gb:.1f} GB"
                        )
                    else:
                        data["gpu"] = data["vram"] = None
                except Exception:
                    data["gpu"] = data["vram"] = None
            else:
                data["gpu"] = data["vram"] = None
```

- [ ] **Step 3: Replace the `_cmd_status` GPU block**

Replace lines 619-628 (the `if _GPU_OK:` inside `_cmd_status`) with:

```python
            if _GPU_OK:
                try:
                    info = gpu_info.read_gpu()
                    if info.vram_total_gb > 0:
                        msg += (
                            f"  GPU: {info.util_pct:.0f}%  "
                            f"VRAM: {info.vram_used_gb:.1f}/"
                            f"{info.vram_total_gb:.1f} GB"
                        )
                    else:
                        msg += "  GPU: no data"
                except Exception:
                    msg += "  GPU: read error"
```

- [ ] **Step 4: Sanity-check the imports**

Run: `python -c "import gui.tabs.dashboard"`
Expected: No exceptions.

Run: `pytest -q`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add gui/tabs/dashboard.py
git commit -m "refactor(gpu): migrate dashboard pynvml call sites to core.gpu_info"
```

---

## Task 12: Update `core/agent_builder.py` docstring + final smoke test

**Files:**
- Modify: `core/agent_builder.py:415`

- [ ] **Step 1: Update the docstring**

Find the line in `core/agent_builder.py` near line 415 that reads:

```
PySide6, requests, psutil, pynvml, python-kasa, playwright,
```

Replace `pynvml` with `pynvml (NVIDIA only — prefer core.gpu_info for cross-vendor GPU info)`. The full edit context will resemble:

```python
          PySide6, requests, psutil, pynvml (NVIDIA only — prefer
          core.gpu_info for cross-vendor GPU info), python-kasa,
          playwright,
```

- [ ] **Step 2: Run the full test suite one final time**

Run: `pytest -q`
Expected: All tests PASS (the new `tests/test_gpu_info.py` adds 10 tests; old test count stays unchanged otherwise).

- [ ] **Step 3: Manual smoke test on the dev machine**

If this dev machine has an NVIDIA GPU available, launch Plia and verify the title-bar widget still reports VRAM/util correctly:

```bash
python main.py
```

Visually confirm:
- Title bar shows non-zero GPU%/VRAM values (NVIDIA dev machine) or "N/A" (CPU-only)
- Model Browser tab shows correct GPU name/VRAM in its hardware panel
- Dashboard `status` command (type `status` into the dashboard input) prints a line with GPU + VRAM info

Close Plia cleanly. No new console errors compared to the baseline.

- [ ] **Step 4: Final commit**

```bash
git add core/agent_builder.py
git commit -m "docs(gpu): point generated agents at core.gpu_info"
```

---

## Done Criteria

- New `core/gpu_info.py` module with `GpuInfo`, `detect_backend()`, `read_gpu()`.
- 10 new tests in `tests/test_gpu_info.py`, all passing.
- All four pynvml call sites (model_browser, system_monitor, dashboard ×2) call `core.gpu_info` instead of `pynvml` directly.
- Full test suite remains at 188+ tests, all passing.
- Manual smoke test on the dev machine confirms no GUI regressions.
- `core/agent_builder.py` docstring nudges generated agents toward `core.gpu_info`.
