"""Agent template for wake-word trainer renders to valid Python."""

import ast


def test_wake_trainer_template_renders_to_valid_python():
    from core.agent_builder import _WAKE_TRAINER_TEMPLATE
    src = _WAKE_TRAINER_TEMPLATE.format(
        slug="wake_word_trainer",
        timestamp="2026-05-18 12:00:00",
        word="plia",
        variants=5000,
        file_path="/tmp/wake_word_trainer.py",
    )
    ast.parse(src)


def test_detect_build_intent_matches_train_a_wake_word():
    from core.agent_builder import detect_build_intent
    intent = detect_build_intent("train a wake word for plia")
    assert intent is not None
    assert intent.get("kind") == "wake_trainer"
