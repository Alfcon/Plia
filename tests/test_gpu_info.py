"""Tests for core.gpu_info — cross-vendor GPU detection."""

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
