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
