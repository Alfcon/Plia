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


@pytest.mark.parametrize("bad_variants", [0, 100, 50000, -5])
def test_validate_variants_rejects_out_of_range(bad_variants):
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="variants"):
        train_wake_word("plia", variants=bad_variants)


def test_validate_voices_rejects_unknown():
    from core.wake_trainer import train_wake_word, WakeTrainerError
    with pytest.raises(WakeTrainerError, match="voice"):
        train_wake_word("plia", voices=["en_ZZ-fake-medium"])
