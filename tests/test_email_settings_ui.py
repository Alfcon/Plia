"""Settings → Features → Email Integration card.

Audit pass 2 flagged email.{smtp,imap}_* + username/password/from_address
as configured only via hand-editing settings.json. core/email_manager.py
already reads all seven; these tests cover the new settings UI surface.
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
def fresh_email_settings(monkeypatch):
    """Save/restore the email.* settings so tests don't leak each other."""
    from core.settings_store import settings as app_settings
    keys = [
        "email.smtp_server", "email.smtp_port", "email.imap_server",
        "email.imap_port", "email.username", "email.password",
        "email.from_address",
    ]
    saved = {k: app_settings.get(k) for k in keys}
    yield
    for k, v in saved.items():
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


def test_email_cards_present(qapp, fresh_email_settings):
    host, tab = _build_tab(qapp)
    for attr in (
        "email_smtp_server_card",
        "email_smtp_port_card",
        "email_imap_server_card",
        "email_imap_port_card",
        "email_username_card",
        "email_password_card",
        "email_from_card",
        "email_test_card",
    ):
        assert hasattr(tab, attr), f"missing {attr}"
    host.close()


def test_password_field_is_masked(qapp, fresh_email_settings):
    from PySide6.QtWidgets import QLineEdit
    host, tab = _build_tab(qapp)
    assert tab.email_password_card.input.echoMode() == QLineEdit.Password, (
        "password card must use QLineEdit.Password echo mode"
    )
    host.close()


def test_password_stays_string_even_for_all_digit_input(qapp, fresh_email_settings):
    """Regression guard: TextInputCard coerces all-digit input to float, so
    a password "12345" would be stored as 12345.0 and login would fail.
    PasswordInputCard must store strings verbatim."""
    from core.settings_store import settings as app_settings
    host, tab = _build_tab(qapp)
    tab.email_password_card.input.setText("12345")
    qapp.processEvents()
    stored = app_settings.get("email.password")
    assert stored == "12345" and isinstance(stored, str), (
        f"password must persist as the string '12345', got {stored!r}"
    )
    host.close()


def test_text_fields_persist_to_settings(qapp, fresh_email_settings):
    from core.settings_store import settings as app_settings
    host, tab = _build_tab(qapp)

    tab.email_smtp_server_card.input.setText("smtp.example.com")
    tab.email_imap_server_card.input.setText("imap.example.com")
    tab.email_username_card.input.setText("me@example.com")
    tab.email_from_card.input.setText("me@example.com")
    qapp.processEvents()

    assert app_settings.get("email.smtp_server") == "smtp.example.com"
    assert app_settings.get("email.imap_server") == "imap.example.com"
    assert app_settings.get("email.username") == "me@example.com"
    assert app_settings.get("email.from_address") == "me@example.com"
    host.close()


def test_test_connection_button_runs_tester(qapp, fresh_email_settings, monkeypatch):
    """Clicking the Test button must spawn the email connection tester.
    We patch the tester so no real network calls happen."""
    from gui.tabs import settings as settings_mod

    started = {"n": 0}

    class _Sig:
        def connect(self, *a, **kw):
            pass
        def emit(self, *a, **kw):
            pass

    class _StubTester:
        def __init__(self, *args, **kwargs):
            self.done = _Sig()
            self.finished = _Sig()

        def start(self):
            started["n"] += 1

    monkeypatch.setattr(settings_mod, "EmailConnectionTester", _StubTester)

    host, tab = _build_tab(qapp)
    tab.email_smtp_server_card.input.setText("smtp.example.com")
    tab.email_username_card.input.setText("me@example.com")
    tab.email_password_card.input.setText("pw")
    qapp.processEvents()
    tab.email_test_card.clicked.emit()
    qapp.processEvents()
    assert started["n"] == 1, "Test button should kick off EmailConnectionTester"
    host.close()
