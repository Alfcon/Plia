"""End-to-end wake-trainer test. Slow (~30-60 s); gated by RUN_SLOW=1."""

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SLOW") != "1",
    reason="set RUN_SLOW=1 to run the slow wake-trainer integration test",
)


def test_train_tiny_wake_model_end_to_end(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    from core import wake_trainer

    # 1. Fake neg features so we don't download hundreds of MB in CI.
    neg = tmp_path / "neg"
    neg.mkdir()
    (neg / ".ready").write_text("ok\n")
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", neg)

    # 2. Tiny output dir.
    out = tmp_path / "custom"
    monkeypatch.setattr(wake_trainer, "_default_output_dir", lambda: out)

    # 3. Train with a tiny variant count + 2 epochs.
    path = wake_trainer.train_wake_word(
        "plia", variants=500, epochs=2,
        on_progress=lambda pct, msg: print(f"[{pct:5.1f}%] {msg}"),
    )

    assert path == out / "plia.onnx"
    assert path.exists()
    assert path.stat().st_size > 1024

    # 4. Loadable by openwakeword.
    from openwakeword.model import Model
    m = Model(wakeword_models=[str(path)], inference_framework="onnx")
    assert "plia" in m.prediction_buffer
