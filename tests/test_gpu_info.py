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
    monkeypatch.setattr(gpu_info, "_AMD_CARD_PATH", None, raising=False)
    yield
    monkeypatch.setattr(gpu_info, "_BACKEND_CACHE", None, raising=False)
    monkeypatch.setattr(gpu_info, "_AMD_CARD_PATH", None, raising=False)


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
