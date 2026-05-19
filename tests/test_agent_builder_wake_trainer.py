"""Agent template for wake-word trainer renders to valid Python."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from config import WAKE_TRAINER_ENABLED


def _render(plia_root="/fake/plia"):
    from core.agent_builder import _WAKE_TRAINER_TEMPLATE
    return _WAKE_TRAINER_TEMPLATE.format(
        slug="wake_word_trainer",
        timestamp="2026-05-18 12:00:00",
        word="plia",
        variants=5000,
        file_path="/tmp/wake_word_trainer.py",
        plia_root=plia_root,
    )


def test_wake_trainer_template_renders_to_valid_python():
    ast.parse(_render())


def test_detect_build_intent_matches_train_a_wake_word():
    from core.agent_builder import detect_build_intent
    intent = detect_build_intent("train a wake word for plia")
    assert intent is not None
    assert intent.get("kind") == "wake_trainer"


@pytest.mark.skipif(
    WAKE_TRAINER_ENABLED,
    reason="paused-behaviour guard; only runs while WAKE_TRAINER_ENABLED is False",
)
def test_build_agent_returns_paused_result_for_wake_trainer_intent():
    """While paused, build_agent must short-circuit on wake_trainer intents
    and NOT write any agent file or touch the registry."""
    from core.agent_builder import build_agent, detect_build_intent, AGENTS_DIR

    intent = detect_build_intent("train a wake word for plia")
    assert intent is not None and intent.get("kind") == "wake_trainer"

    before = set(AGENTS_DIR.glob("*.py")) if AGENTS_DIR.exists() else set()
    result = build_agent(
        intent=intent,
        ollama_url="http://localhost:11434",
        model="qwen3:8b",
        on_status=lambda s: None,
    )
    after = set(AGENTS_DIR.glob("*.py")) if AGENTS_DIR.exists() else set()

    assert result.success is False
    assert "paus" in result.error.lower()
    assert "colab" in result.error.lower()
    assert before == after, "no agent file should be written while paused"


def test_wake_trainer_template_bakes_plia_root_into_source():
    """build_agent must substitute the real Plia repo path so the agent's
    `import core.wake_trainer` works without manual editing. Previously
    the template used `THIS.parents[2]`, which resolves to ``$HOME`` for
    agents written to ``~/.plia_ai/agents/<slug>.py`` — wrong out of the
    box."""
    src = _render(plia_root="/opt/Plia")
    assert '"/opt/Plia"' in src or "r'/opt/Plia'" in src or 'r"/opt/Plia"' in src, (
        "expected plia_root to be baked into the generated source"
    )


def test_generated_agent_can_import_core_wake_trainer(tmp_path):
    """End-to-end: write the rendered template to a fake
    ~/.plia_ai/agents/ location, point plia_root at the real repo, and
    verify the file imports cleanly in a subprocess (i.e. the sys.path
    insert works and the resulting `from core.wake_trainer import …`
    succeeds)."""
    real_plia_root = Path(__file__).resolve().parents[1]
    assert (real_plia_root / "core" / "wake_trainer.py").exists(), (
        f"sanity check: core/wake_trainer.py not found under {real_plia_root}"
    )

    src = _render(plia_root=str(real_plia_root))

    agent_dir = tmp_path / ".plia_ai" / "agents"
    agent_dir.mkdir(parents=True)
    agent_file = agent_dir / "wake_word_trainer_plia.py"
    agent_file.write_text(src)

    # cwd MUST NOT be the Plia repo: `python -c` adds cwd to sys.path,
    # so running from the repo would mask a broken sys.path shim.
    result = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util, sys;"
         f"spec = importlib.util.spec_from_file_location('a', r'{agent_file}');"
         "m = importlib.util.module_from_spec(spec);"
         "spec.loader.exec_module(m);"
         "assert callable(m.run), 'run() missing'"],
        capture_output=True, text=True, timeout=30,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, (
        f"generated agent failed to import:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
