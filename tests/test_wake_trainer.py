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
