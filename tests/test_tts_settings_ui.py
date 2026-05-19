"""Settings → Voice & Audio TTS audio controls.

The 2026-05-19 audit flagged tts.volume / tts.length_scale / tts.muted as
configured-only-via-JSON. These tests cover:
  - the three settings cards exist on SettingsTab
  - changing a card persists to settings AND applies live to the tts singleton
  - VoiceEngine.initialize() honours the persisted values
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
def fresh_tts_state(monkeypatch):
    """Reset tts.* settings + the singleton attrs so each test starts clean.

    Any value the test writes is restored on teardown via monkeypatch's
    setattr tracking."""
    from core.settings_store import settings as app_settings
    from core.tts import tts
    saved = {
        "vol": app_settings.get("tts.volume", 0.9),
        "len": app_settings.get("tts.length_scale", 1.0),
        "muted": app_settings.get("tts.muted", False),
    }
    monkeypatch.setattr(tts, "volume", 0.9)
    monkeypatch.setattr(tts, "length_scale", 1.0)
    monkeypatch.setattr(tts, "muted", False)
    yield
    app_settings.set("tts.volume", saved["vol"])
    app_settings.set("tts.length_scale", saved["len"])
    app_settings.set("tts.muted", saved["muted"])


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


def test_tts_audio_cards_present(qapp, fresh_tts_state):
    host, tab = _build_tab(qapp)
    assert hasattr(tab, "tts_volume_card"), "missing tts_volume_card"
    assert hasattr(tab, "tts_length_scale_card"), "missing tts_length_scale_card"
    assert hasattr(tab, "tts_mute_card"), "missing tts_mute_card"
    host.close()


def test_volume_slider_persists_and_applies_live(qapp, fresh_tts_state):
    from core.settings_store import settings as app_settings
    from core.tts import tts

    host, tab = _build_tab(qapp)
    # Move slider to 50% (= 0.50).
    tab.tts_volume_card.slider.setValue(50)
    qapp.processEvents()

    assert app_settings.get("tts.volume") == pytest.approx(0.50, abs=0.01)
    assert tts.volume == pytest.approx(0.50, abs=0.01)
    host.close()


def test_length_scale_slider_persists_and_applies_live(qapp, fresh_tts_state):
    from core.settings_store import settings as app_settings
    from core.tts import tts

    host, tab = _build_tab(qapp)
    # Move slider to length_scale = 1.30 (= int slider position 26 with step 0.05).
    tab.tts_length_scale_card.slider.setValue(26)
    qapp.processEvents()

    assert app_settings.get("tts.length_scale") == pytest.approx(1.30, abs=0.01)
    assert tts.length_scale == pytest.approx(1.30, abs=0.01)
    host.close()


def test_mute_switch_persists_and_applies_live(qapp, fresh_tts_state):
    from core.settings_store import settings as app_settings
    from core.tts import tts

    host, tab = _build_tab(qapp)
    tab.tts_mute_card.switch.setChecked(True)
    qapp.processEvents()

    assert app_settings.get("tts.muted") is True
    assert tts.muted is True
    host.close()


def test_voice_engine_initialize_loads_persisted_values(monkeypatch):
    """VoiceEngine.initialize() must read the saved tts.* values on startup,
    not silently keep the constructor defaults."""
    from core.settings_store import settings as app_settings
    from core import tts as tts_mod

    saved = {
        "vol": app_settings.get("tts.volume", 0.9),
        "len": app_settings.get("tts.length_scale", 1.0),
        "muted": app_settings.get("tts.muted", False),
    }
    try:
        app_settings.set("tts.volume", 0.42)
        app_settings.set("tts.length_scale", 1.55)
        app_settings.set("tts.muted", True)

        # Skip the heavy library/exe init paths — we only care about the
        # settings-load branch at the top of initialize().
        monkeypatch.setattr(tts_mod, "HAS_PIPER_LIB", False)
        monkeypatch.setattr(tts_mod, "HAS_PIPER_EXE_DEPS", False)

        engine = tts_mod.VoiceEngine()
        engine.initialize()  # returns False (no piper) but still runs settings load

        assert engine.volume == pytest.approx(0.42, abs=0.001)
        assert engine.length_scale == pytest.approx(1.55, abs=0.001)
        assert engine.muted is True
    finally:
        app_settings.set("tts.volume", saved["vol"])
        app_settings.set("tts.length_scale", saved["len"])
        app_settings.set("tts.muted", saved["muted"])
