# AMD GPU Detection — Design Spec

**Date:** 2026-05-17
**Status:** Draft — awaiting user review
**Scope:** Add full-parity AMD GPU detection (Linux / ROCm) across all four call sites that currently use `pynvml`.

---

## 1. Motivation

Plia's README and `requirements.txt` now document AMD GPUs as supported on Linux (via the ROCm PyTorch wheel). The runtime device-selection code in `core/router.py` and `core/stt.py` already works for AMD, because PyTorch's ROCm build exposes `torch.cuda.is_available()` as `True`.

However, the GUI's GPU-info surfaces still probe only NVIDIA:

| Call site | Purpose | Impact for AMD users today |
|-----------|---------|----------------------------|
| `gui/tabs/model_browser.py` `HardwareInfo.detect()` | Model recommendation scoring | **Functional** — falls back to CPU scoring, recommends smaller models than the card can run |
| `gui/components/system_monitor.py` | Title-bar VRAM/util widget | Cosmetic — shows no GPU |
| `gui/tabs/dashboard.py` (two probes) | Dashboard GPU panel | Cosmetic — shows no GPU |

The goal is to give AMD GPUs visibility everywhere NVIDIA already has it, with no new dependencies and no regression for NVIDIA users.

## 2. Non-Goals

- **Windows AMD** — no upstream ROCm wheel exists; README already documents this as unsupported.
- **macOS Apple Silicon (MPS)** — out of scope.
- **Intel Arc / SYCL / XPU** — out of scope.
- **Per-process VRAM accounting on AMD** — sysfs only exposes card-level totals.
- **Changing model-scoring constants** — `BACKEND_SPEED["rocm"] = 180` is already in `gui/tabs/model_browser.py:139`.
- **Auto-installing the ROCm PyTorch wheel** — users still pick CUDA vs ROCm in `requirements.txt` (already documented in README Step 5).

## 3. Architecture

### 3.1 New module: `core/gpu_info.py`

Single source of truth for GPU info. All current `pynvml`-direct call sites are migrated to call this module.

**Public API**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class GpuInfo:
    backend: str           # "cuda" | "rocm" | "cpu"
    name: str              # e.g. "AMD Radeon RX 7900 XTX" or "No GPU"
    vram_total_gb: float   # 0.0 when backend == "cpu"
    vram_used_gb: float
    vram_free_gb: float
    util_pct: float        # 0-100, 0.0 if unavailable

def detect_backend() -> str:
    """One-shot probe; cached at first call. Returns 'cuda' | 'rocm' | 'cpu'."""

def read_gpu() -> GpuInfo:
    """Cheap per-tick read; uses cached backend."""
```

**Backend selection** (cached on first call to `detect_backend`):

1. Try `import pynvml; pynvml.nvmlInit(); pynvml.nvmlDeviceGetHandleByIndex(0)` — success ⇒ `"cuda"`. Both `ImportError` (pynvml not installed) and `pynvml.NVMLError` (no NVIDIA driver / GPU) are caught and fall through to step 2. Matches today's "NVIDIA wins on multi-GPU" behavior. No behavior change for existing NVIDIA setups.
2. If pynvml is unavailable but a system `nvidia-smi` binary exists, try the existing `nvidia-smi --query-gpu=memory.free,name` subprocess fallback (moved here from `model_browser.py`). Success ⇒ `"cuda"`. This preserves today's second-chance NVIDIA probe.
3. Else scan `/sys/class/drm/card*/device/vendor` for `0x1002` (AMD's PCI vendor ID). Of all AMD cards with `mem_info_vram_total > 0`, pick the one with the largest VRAM — this naturally favors a discrete Radeon over an integrated Ryzen iGPU on hybrid systems. Success ⇒ `"rocm"`.
4. Else ⇒ `"cpu"`.

**Per-tick read implementation**

| Backend | Source |
|---------|--------|
| `cuda`  | `pynvml.nvmlDeviceGetMemoryInfo` + `nvmlDeviceGetUtilizationRates` (existing logic, moved into this module) |
| `rocm`  | Read `mem_info_vram_total`, `mem_info_vram_used`, `gpu_busy_percent` from the chosen `/sys/class/drm/cardN/device/` directory; cache `name` at backend-detection time |
| `cpu`   | Return `GpuInfo(backend="cpu", name="No GPU", 0.0, 0.0, 0.0, 0.0)` |

**Name resolution for AMD**: read the `product_name` sysfs file (exposed by the AMDGPU kernel driver since 5.14, which predates ROCm 6.x's supported kernels). Fall back to the literal string `"AMD GPU"` if the file is missing or unreadable. No subprocess is invoked — a per-tick `lspci` call was considered and rejected as over-engineering for a corner case affecting only legacy kernels we don't support.

**Error handling**: every sysfs read is wrapped in try/except → returns zeros on `PermissionError`, `FileNotFoundError`, or parse error. No exceptions ever escape `read_gpu`. The pynvml path keeps its existing try/except behavior.

### 3.2 Call site changes

All four sites collapse to a single call:

```python
from core import gpu_info
info = gpu_info.read_gpu()
# ...use info.backend / info.vram_used_gb / info.util_pct...
```

- **`gui/tabs/model_browser.py`** `HardwareInfo.detect()` — replace the pynvml block + `nvidia-smi` subprocess fallback with one call. `self.backend = info.backend`, `self.vram_gb = info.vram_free_gb`, `self.gpu_name = info.name`. The `nvidia-smi` subprocess fallback moves into `gpu_info.detect_backend()` step 2 (see §3.1) so all backend-selection logic lives in one place.
- **`gui/components/system_monitor.py`** — tick callback drops its pynvml block.
- **`gui/tabs/dashboard.py`** — both pynvml call sites (lines 174, 621) drop their inline init/probe and call `gpu_info.read_gpu()` instead.

The module-level `import pynvml` lines in each file are removed and replaced with `from core import gpu_info`.

### 3.3 Dependency posture

- `pynvml>=13.0.0` stays in `requirements.txt` — NVIDIA users still need it. Wrapped in a try/import inside `core/gpu_info.py` so an AMD-only Linux install with no pynvml installed degrades gracefully (will skip step 1 and try the sysfs path).
- No new pip dependencies.
- No new system packages required on AMD — sysfs is part of the AMDGPU kernel driver.

## 4. Testing

New file `tests/test_gpu_info.py`. Uses `tmp_path` and `monkeypatch` to fake the `/sys/class/drm/` tree; mocks `pynvml` to be either successful, failing, or absent.

| Case | Setup | Expectation |
|------|-------|-------------|
| NVIDIA-only via pynvml | pynvml init succeeds | `backend == "cuda"`, name/VRAM from mocked pynvml |
| NVIDIA-only via nvidia-smi fallback | pynvml import fails; `nvidia-smi` mock returns valid CSV | `backend == "cuda"`, name/VRAM parsed from CSV |
| AMD-only (single dGPU) | Fake `card0` with vendor `0x1002`, VRAM 24 GB | `backend == "rocm"`, vram_total_gb ≈ 24.0 |
| AMD iGPU + AMD dGPU | `card0` = APU (small VRAM), `card1` = dGPU (large VRAM) | Picks `card1` |
| NVIDIA + AMD | pynvml init succeeds | NVIDIA wins (`backend == "cuda"`) — preserves existing precedence |
| No GPU | pynvml init fails, no `/sys/class/drm/card*` | `backend == "cpu"`, all zeros |
| Sysfs permission denied | Fake `card0` with unreadable `mem_info_vram_used` | Backend still detected; usage read returns 0.0 |
| Stale cache invariant | `detect_backend()` called twice | Second call returns cached value without re-probing |

No GUI tests — the four call sites are mechanical swaps and integration testing them through Qt is over-engineering. Manual verification: launch Plia on the dev machine post-change, confirm title-bar VRAM widget reads correctly.

## 5. Migration / Rollout

Single PR, no feature flag. The change is:

1. Add `core/gpu_info.py` + `tests/test_gpu_info.py`.
2. Migrate four call sites in `gui/`.
3. Update `core/agent_builder.py:415` docstring listing available packages (mention `core.gpu_info` is preferred over `pynvml` for generated agents that want GPU info).
4. Run the full test suite — must stay at 188/188 (no test currently exercises pynvml directly, so no churn expected).
5. Manual smoke test on the dev machine (NVIDIA) before merge.

## 6. Open Questions

None at spec time — all design choices were resolved during brainstorming:
- Scope: full parity across all four call sites.
- Method: sysfs reads, no new pip dep, no subprocess on the hot path.
- Precedence: NVIDIA still wins on hybrid systems (matches today's behavior).

## 7. Files Touched

**New**
- `core/gpu_info.py` (~120 lines)
- `tests/test_gpu_info.py` (~150 lines)

**Modified**
- `gui/tabs/model_browser.py` — replace pynvml block in `HardwareInfo.detect()` (~30 lines deleted, ~5 added)
- `gui/components/system_monitor.py` — replace pynvml block in tick callback (~10 lines deleted, ~5 added)
- `gui/tabs/dashboard.py` — replace two pynvml blocks (~25 lines deleted, ~10 added)
- `core/agent_builder.py` — minor docstring tweak

Estimated net diff: +~150 lines, −~70 lines.
