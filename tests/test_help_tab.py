"""Tests for the Help / Docs tab discovery."""

from pathlib import Path

from gui.tabs import help as help_tab


def test_help_dir_exists_and_has_pages():
    """docs/help/ ships with the canonical Plia help pages."""
    assert help_tab._HELP_DIR.exists(), \
        f"docs/help directory missing at {help_tab._HELP_DIR}"
    md_files = list(help_tab._HELP_DIR.glob("*.md"))
    assert md_files, "expected at least one .md file in docs/help/"


def test_pretty_title_strips_numeric_prefix():
    assert help_tab._pretty_title(Path("02-live-agents.md")) == "Live Agents"
    assert help_tab._pretty_title(Path("welcome.md")) == "Welcome"
    assert help_tab._pretty_title(Path("99-some-doc-name.md")) == "Some Doc Name"
