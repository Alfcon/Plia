from pathlib import Path

from core.multi_agent import multi_agent_system


def test_singleton_roles_dir_is_under_plia_home():
    expected = Path.home() / ".plia_ai" / "roles"
    assert Path(multi_agent_system.roles_dir) == expected


def test_roles_dir_exists_after_import():
    # importing core.multi_agent must create the directory
    assert (Path.home() / ".plia_ai" / "roles").is_dir()
