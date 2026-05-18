"""Tests for core.wake_trainer — in-app openWakeWord training pipeline."""

import pytest


def test_module_exposes_public_surface():
    from core import wake_trainer

    assert hasattr(wake_trainer, "train_wake_word")
    assert hasattr(wake_trainer, "ensure_negative_features")
    assert hasattr(wake_trainer, "synthesize_positives")
    assert issubclass(wake_trainer.TrainCancelled, Exception)
    assert issubclass(wake_trainer.WakeTrainerError, Exception)
    # Defaults
    assert "en_US-lessac-medium" in wake_trainer.DEFAULT_VOICES


def test_train_wake_word_is_not_implemented_yet():
    from core.wake_trainer import train_wake_word

    with pytest.raises(NotImplementedError):
        train_wake_word("plia")


@pytest.mark.parametrize("bad_word", ["", "   ", "@@@", "a" * 33, "💩"])
def test_validate_word_rejects_invalid(bad_word):
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="word"):
        train_wake_word(bad_word)


@pytest.mark.parametrize("good_word", ["plia", "Hey Jarvis", "ok nabu"])
def test_validate_word_accepts_reasonable(good_word):
    """Validation must NOT raise for these. The function will still raise
    NotImplementedError because Task 8 hasn't wired the pipeline yet."""
    from core.wake_trainer import train_wake_word
    with pytest.raises(NotImplementedError):
        train_wake_word(good_word)


@pytest.mark.parametrize("word, expected", [
    ("plia", "plia"),
    ("Hey Jarvis", "hey_jarvis"),
    ("OK  nabu", "ok_nabu"),
    ("plia_v2", "plia_v2"),
])
def test_slugify_word(word, expected):
    from core.wake_trainer import _slugify
    assert _slugify(word) == expected


def test_slugify_empty_raises():
    from core.wake_trainer import _slugify, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="empty"):
        _slugify("   ")


@pytest.mark.parametrize("bad_variants", [0, 100, 50000, -5])
def test_validate_variants_rejects_out_of_range(bad_variants):
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="variants"):
        train_wake_word("plia", variants=bad_variants)


def test_validate_voices_rejects_unknown():
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="voice"):
        train_wake_word("plia", voices=["en_ZZ-fake-medium"])


def test_train_wake_word_strips_surrounding_whitespace():
    """Whitespace-wrapped words must be normalised before being forwarded
    downstream — otherwise slug/synth/train bake the whitespace in."""
    from core.wake_trainer import train_wake_word
    # Wrapped word strips to "plia", passes validation, then hits NotImplementedError.
    with pytest.raises(NotImplementedError):
        train_wake_word("  plia  ")


def test_ensure_negative_features_is_idempotent(monkeypatch, tmp_path):
    """Second call must not re-download once the .ready marker is set."""
    from core import wake_trainer

    fake_root = tmp_path / "neg_features"
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", fake_root)

    download_calls = {"n": 0}
    def fake_download_and_unpack(dest: "Path") -> None:
        download_calls["n"] += 1
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".ready").write_text("ok\n")

    monkeypatch.setattr(
        wake_trainer, "_download_neg_features", fake_download_and_unpack
    )

    progress = []
    p1 = wake_trainer.ensure_negative_features(
        on_progress=lambda pct, msg: progress.append((pct, msg))
    )
    p2 = wake_trainer.ensure_negative_features(
        on_progress=lambda pct, msg: progress.append((pct, msg))
    )
    assert p1 == p2 == fake_root
    assert download_calls["n"] == 1, "second call must hit the cache"


def test_ensure_negative_features_retries_on_network_error(monkeypatch, tmp_path):
    """Three transient failures + one success → final call wins."""
    from core import wake_trainer

    fake_root = tmp_path / "neg_features"
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", fake_root)

    calls = {"n": 0}
    def flaky(dest: "Path") -> None:
        calls["n"] += 1
        if calls["n"] < 4:
            raise IOError("simulated network failure")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".ready").write_text("ok\n")
    monkeypatch.setattr(wake_trainer, "_download_neg_features", flaky)

    # _RETRY_DELAYS is shrunk for tests so this doesn't sleep for real.
    monkeypatch.setattr(wake_trainer, "_RETRY_DELAYS", [0.0, 0.0, 0.0])

    wake_trainer.ensure_negative_features()
    assert calls["n"] == 4


def test_ensure_negative_features_gives_up_after_retries(monkeypatch, tmp_path):
    from core import wake_trainer

    fake_root = tmp_path / "neg_features"
    monkeypatch.setattr(wake_trainer, "NEG_FEATURES_DIR", fake_root)
    monkeypatch.setattr(wake_trainer, "_RETRY_DELAYS", [0.0, 0.0, 0.0])
    monkeypatch.setattr(
        wake_trainer, "_download_neg_features",
        lambda dest: (_ for _ in ()).throw(IOError("nope"))
    )

    with pytest.raises(wake_trainer.WakeTrainerError, match="download"):
        wake_trainer.ensure_negative_features()


def test_synthesize_positives_writes_wav_files(monkeypatch, tmp_path):
    """Replaces PiperVoice.load with a fake so the test doesn't need a real
    voice model on disk."""
    from core import wake_trainer

    rendered: list[tuple[str, str]] = []

    class FakeVoice:
        def __init__(self, name: str):
            self.name = name

        def synthesize(self, text: str, wf, length_scale: float = 1.0):
            # WAV header + 0.2s of silence at 16 kHz mono.
            wf.writeframes(b"\x00\x00" * 3200)
            rendered.append((self.name, text))

    fake_loader = {"calls": 0}
    def fake_piper_load(name: str):
        fake_loader["calls"] += 1
        return FakeVoice(name)
    monkeypatch.setattr(wake_trainer, "_load_piper_voice", fake_piper_load)

    out_dir = tmp_path / "positives"
    wake_trainer.synthesize_positives(
        word="plia",
        voices=["en_US-lessac-medium", "en_US-amy-medium"],
        variants=50,
        out_dir=out_dir,
    )
    wavs = sorted(out_dir.glob("*.wav"))
    assert len(wavs) == 50, f"expected 50 wavs, got {len(wavs)}"
    # Both voices used at least once.
    voices_used = {name for name, _ in rendered}
    assert voices_used == {"en_US-lessac-medium", "en_US-amy-medium"}


def test_synthesize_positives_respects_cancellation(monkeypatch, tmp_path):
    """should_cancel() returning True between WAVs aborts cleanly."""
    from core import wake_trainer

    class FakeVoice:
        def synthesize(self, text, wf, length_scale=1.0):
            wf.writeframes(b"\x00\x00" * 3200)

    monkeypatch.setattr(wake_trainer, "_load_piper_voice", lambda n: FakeVoice())

    cancel_after = {"n": 3}
    def should_cancel():
        cancel_after["n"] -= 1
        return cancel_after["n"] <= 0

    with pytest.raises(wake_trainer.TrainCancelled):
        wake_trainer.synthesize_positives(
            word="plia",
            voices=["en_US-lessac-medium"],
            variants=100,
            out_dir=tmp_path / "p",
            should_cancel=should_cancel,
        )


def test_synthesize_positives_raises_when_all_voices_fail(monkeypatch, tmp_path):
    """If every voice's loader raises, the function must raise WakeTrainerError."""
    from core import wake_trainer

    def always_fails(name):
        raise RuntimeError(f"voice {name} broken")
    monkeypatch.setattr(wake_trainer, "_load_piper_voice", always_fails)

    with pytest.raises(wake_trainer.WakeTrainerError, match="all loads failed"):
        wake_trainer.synthesize_positives(
            word="plia",
            voices=["en_US-lessac-medium", "en_US-amy-medium"],
            variants=12,
            out_dir=tmp_path / "p",
        )


def test_synthesize_positives_aborts_when_too_many_synth_failures(monkeypatch, tmp_path):
    """After the first WAV succeeds, every subsequent synth call raises; once
    the failure count exceeds variants // 10, the function aborts with
    WakeTrainerError mentioning '>10%'."""
    from core import wake_trainer

    class FlakyVoice:
        def __init__(self):
            self.calls = 0
        def synthesize(self, text, wf, length_scale=1.0):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("synth error")
            wf.writeframes(b"\x00\x00" * 3200)

    monkeypatch.setattr(wake_trainer, "_load_piper_voice", lambda n: FlakyVoice())

    with pytest.raises(wake_trainer.WakeTrainerError, match=">10%"):
        wake_trainer.synthesize_positives(
            word="plia",
            voices=["en_US-lessac-medium"],
            variants=12,
            out_dir=tmp_path / "p",
        )


def test_train_loop_returns_module_and_reports_progress(monkeypatch, tmp_path):
    """Tiny end-to-end: 4 positives + a 4-feature fake neg pack, 2 epochs.
    We don't care about model quality — only that the loop runs, reports
    progress, and returns a torch.nn.Module."""
    pytest.importorskip("torch")
    from core import wake_trainer
    import torch

    # Build a fake positives dir with 4 silent 0.2s WAVs.
    positives = tmp_path / "positives"
    positives.mkdir()
    import wave
    for i in range(4):
        with wave.open(str(positives / f"{i:05d}.wav"), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)  # 1s — embedding needs ≥76 mel frames

    # Fake neg-feature pack: tiny .npy files with the right shape.
    # _train_loop expects neg_features_dir to contain:
    #   - neg_features.npy : shape (N, n_frames, 96) float32
    #   - .ready            : marker file
    neg = tmp_path / "neg"
    neg.mkdir()
    (neg / ".ready").write_text("ok\n")
    import numpy as np
    # shape: (8 samples, 3 frames, 96 features) matching 1s-clip embeddings
    neg_arr = np.zeros((8, 3, 96), dtype=np.float32)
    np.save(str(neg / "neg_features.npy"), neg_arr)

    progress: list[tuple[float, str]] = []
    model = wake_trainer._train_loop(
        positives_dir=positives,
        neg_features_dir=neg,
        epochs=2,
        on_progress=lambda pct, msg: progress.append((pct, msg)),
        should_cancel=lambda: False,
    )
    assert isinstance(model, torch.nn.Module)
    assert any(30.0 <= pct <= 95.0 for pct, _ in progress)
    assert any("epoch" in msg for _, msg in progress)


def test_train_loop_cancel_between_epochs(monkeypatch, tmp_path):
    pytest.importorskip("torch")
    from core import wake_trainer

    positives = tmp_path / "positives"
    positives.mkdir()
    import wave
    for i in range(4):
        with wave.open(str(positives / f"{i:05d}.wav"), "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)  # 1s — embedding needs ≥76 mel frames

    neg = tmp_path / "neg"
    neg.mkdir()
    (neg / ".ready").write_text("ok\n")
    import numpy as np
    neg_arr = np.zeros((8, 1, 96), dtype=np.float32)
    np.save(str(neg / "neg_features.npy"), neg_arr)

    epoch_count = {"n": 0}
    def cancel_after_one_epoch():
        epoch_count["n"] += 1
        return epoch_count["n"] > 1

    with pytest.raises(wake_trainer.TrainCancelled):
        wake_trainer._train_loop(
            positives_dir=positives,
            neg_features_dir=neg,
            epochs=10,
            on_progress=lambda pct, msg: None,
            should_cancel=cancel_after_one_epoch,
        )
