"""Settings UI cards for the remaining audit pass 2 surfaces:

- Discord Integration: discord.bot_token (masked password)
- Desktop Agent tuning: web_agent_params.{temperature, top_k, top_p}
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def save_settings(monkeypatch):
    """Save/restore the relevant settings keys per test."""
    from core.settings_store import settings as app_settings
    keys = [
        "discord.bot_token",
        "web_agent_params.temperature",
        "web_agent_params.top_k",
        "web_agent_params.top_p",
    ]
    saved = {k: app_settings.get(k) for k in keys}
    yield
    for k, v in saved.items():
        # Re-set to whatever was there; "" if it was None
        app_settings.set(k, v if v is not None else "")


def _build_tab(qapp):
    from PySide6.QtWidgets import QMainWindow
    from gui.tabs.settings import SettingsTab
    host = QMainWindow()
    host.resize(1200, 900)
    tab = SettingsTab()
    host.setCentralWidget(tab)
    host.show()
    qapp.processEvents()
    return host, tab


# ── Discord ──────────────────────────────────────────────────────────────


def test_discord_bot_token_card_present_and_masked(qapp, save_settings):
    from PySide6.QtWidgets import QLineEdit
    host, tab = _build_tab(qapp)
    assert hasattr(tab, "discord_token_card"), "missing discord_token_card"
    assert tab.discord_token_card.input.echoMode() == QLineEdit.Password
    host.close()


def test_discord_token_persists_as_string(qapp, save_settings):
    """All-digit Discord token must not be float-coerced (same bug class as
    the email password we fixed in 9d93f1b)."""
    from core.settings_store import settings as app_settings
    host, tab = _build_tab(qapp)
    tab.discord_token_card.input.setText("123456789")
    qapp.processEvents()
    assert app_settings.get("discord.bot_token") == "123456789"
    assert isinstance(app_settings.get("discord.bot_token"), str)
    host.close()


# ── web_agent_params ─────────────────────────────────────────────────────


def test_web_agent_params_cards_present(qapp, save_settings):
    host, tab = _build_tab(qapp)
    for attr in (
        "web_agent_temperature_card",
        "web_agent_top_k_card",
        "web_agent_top_p_card",
    ):
        assert hasattr(tab, attr), f"missing {attr}"
    host.close()


def test_web_agent_param_edits_persist(qapp, save_settings):
    from core.settings_store import settings as app_settings
    host, tab = _build_tab(qapp)

    tab.web_agent_temperature_card.slider.setValue(70)  # 0.70 with step 0.01
    qapp.processEvents()
    tab.web_agent_top_p_card.slider.setValue(80)        # 0.80
    qapp.processEvents()
    tab.web_agent_top_k_card.slider.setValue(40)
    qapp.processEvents()

    assert app_settings.get("web_agent_params.temperature") == pytest.approx(0.70, abs=0.01)
    assert app_settings.get("web_agent_params.top_p") == pytest.approx(0.80, abs=0.01)
    assert app_settings.get("web_agent_params.top_k") == 40
    host.close()
