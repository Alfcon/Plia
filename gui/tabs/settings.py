"""
Comprehensive Settings Tab with model selection, connection settings, and preferences.

FIXES applied (2026-04-16):
  Bug 1 – update_models() used to fire _on_changed(first_model) via addItems() BEFORE
           setCurrentText() could restore the previously-saved value.  Added blockSignals()
           around the repopulation block so the intermediate wrong value is never persisted.

  Bug 2 – Models were only fetched once at SettingsTab.__init__ time.  If the user visited
           Model Browser, downloaded a new model, then returned to Settings, the new model
           never appeared in the Chat / Web Agent dropdowns without a manual Refresh click.
           Fixed by overriding showEvent() to re-fetch on every subsequent visit.

  Bug 3 – _fetch_models() replaced self.model_fetcher each call, leaving the previous
           ModelFetcher thread without a Python reference.  Python's GC could destroy the
           QThread wrapper while the C++ thread was still running ("QThread: Destroyed while
           thread is still running").  Fixed by keeping active threads in self._fetcher_refs.

  Bug 4 – InfoBar(parent=self.window()) could fail silently if the widget wasn't yet
           attached to the main window when the background thread replied.  Added guard.

  Bug 5 – Default web_agent model "qwen2.5vl:7b" is rarely installed, so the Web Agent
           combo started with a stale/unknown value until Refresh ran.  The combo now
           shows a placeholder until the live Ollama list arrives.
"""

from config import LOCAL_ROUTER_PATH, RESPONDER_MODEL

import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout
)
from PySide6.QtCore import Qt, QThread, Signal, Slot

from qfluentwidgets import (
    ScrollArea, ExpandLayout, SettingCardGroup, PushSettingCard, FluentIcon as FIF,
    setTheme, Theme, PrimaryPushSettingCard, ComboBox, LineEdit,
    PrimaryPushButton, InfoBar, InfoBarPosition, SettingCard, Slider,
    StrongBodyLabel, SwitchButton
)

from core.settings_store import settings


class ModelFetcher(QThread):
    """Background thread to fetch available Ollama models."""
    models_fetched = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, ollama_url: str):
        super().__init__()
        self.ollama_url = ollama_url

    def run(self):
        try:
            # Normalise URL — handles both "http://localhost:11434" and
            # "http://localhost:11434/api" so we always hit /api/tags correctly.
            base = self.ollama_url.rstrip("/")
            if base.endswith("/api"):
                base = base[:-4]
            response = requests.get(f"{base}/api/tags", timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = [m['name'] for m in data.get('models', [])]
                self.models_fetched.emit(models)
            else:
                self.error_occurred.emit(f"HTTP {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.error_occurred.emit("Cannot connect to Ollama")
        except Exception as e:
            self.error_occurred.emit(str(e))


class ConnectionTester(QThread):
    """Background thread to test Ollama connection."""
    success = Signal()
    failed = Signal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            base = self.url.rstrip("/")
            if base.endswith("/api"):
                base = base[:-4]
            response = requests.get(f"{base}/api/tags", timeout=5)
            if response.status_code == 200:
                self.success.emit()
            else:
                self.failed.emit(f"HTTP {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.failed.emit("Connection refused")
        except Exception as e:
            self.failed.emit(str(e))


class ComboBoxCard(SettingCard):
    """Setting card with a ComboBox for selection."""

    value_changed = Signal(str)

    def __init__(self, icon, title, description, options: list, key_path: str, parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path

        self.combo = ComboBox(self)
        self.combo.setMinimumWidth(180)
        self.combo.addItems(options)

        current = settings.get(key_path, options[0] if options else "")
        if current in options:
            self.combo.setCurrentText(current)

        self.combo.currentTextChanged.connect(self._on_changed)
        self.hBoxLayout.addWidget(self.combo, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_changed(self, text: str):
        settings.set(self.key_path, text)
        self.value_changed.emit(text)


class ModelSelectCard(SettingCard):
    """Custom setting card with a ComboBox for model selection."""

    model_changed = Signal(str)

    def __init__(self, icon, title, description, key_path: str, parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path

        self.combo = ComboBox(self)
        self.combo.setMinimumWidth(180)
        self.combo.setPlaceholderText("Fetching models…")   # Bug 5 fix: informative placeholder

        # Pre-populate with saved value so there is always *something* visible
        # while the background Ollama fetch is in flight.
        current = settings.get(key_path, "")
        if current:
            self.combo.addItem(current)
            self.combo.setCurrentText(current)

        self.combo.currentTextChanged.connect(self._on_changed)
        self.hBoxLayout.addWidget(self.combo, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_changed(self, text: str):
        if text:
            settings.set(self.key_path, text)
            self.model_changed.emit(text)

    def update_models(self, models: list):
        """
        Repopulate the combo with *models* and restore the previously-saved
        selection if it is still available.

        Bug 1 fix: blockSignals() prevents the intermediate wrong save that
        occurred when addItems() fired currentTextChanged(first_model) before
        setCurrentText() had a chance to restore the user's actual choice.
        """
        current = self.combo.currentText()

        # -- Block signals to prevent spurious settings writes during repopulation
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            self.combo.addItems(models)
            if current in models:
                self.combo.setCurrentText(current)
            elif models:
                self.combo.setCurrentIndex(0)
        finally:
            self.combo.blockSignals(False)

        # Explicitly persist the final selection so settings.json is always correct.
        final = self.combo.currentText()
        if final:
            settings.set(self.key_path, final)
            self.model_changed.emit(final)


class UrlInputCard(SettingCard):
    """Setting card with URL input and test button."""

    def __init__(self, icon, title, description, key_path: str, parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path
        self.tester = None

        self.url_input = LineEdit(self)
        self.url_input.setMinimumWidth(250)
        self.url_input.setText(settings.get(key_path, "http://localhost:11434"))
        self.url_input.textChanged.connect(self._on_url_changed)

        self.test_btn = PrimaryPushButton("Test", self)
        self.test_btn.setFixedWidth(70)
        self.test_btn.clicked.connect(self._test_connection)

        self.hBoxLayout.addWidget(self.url_input, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.test_btn, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_url_changed(self, text: str):
        settings.set(self.key_path, text)

    def _test_connection(self):
        url = self.url_input.text().strip()
        if not url:
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("...")
        self.tester = ConnectionTester(url)
        self.tester.success.connect(self._on_test_success)
        self.tester.failed.connect(self._on_test_failed)
        self.tester.finished.connect(self._on_test_done)
        self.tester.start()

    @Slot()
    def _on_test_success(self):
        win = self.window()
        if win is None:
            return
        InfoBar.success(
            title="Connected",
            content="Ollama is reachable!",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=win
        )

    @Slot(str)
    def _on_test_failed(self, error: str):
        win = self.window()
        if win is None:
            return
        InfoBar.error(
            title="Connection Failed",
            content=error,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=win
        )

    @Slot()
    def _on_test_done(self):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test")


class SliderCard(SettingCard):
    """Setting card with a slider and value label."""

    value_changed = Signal(int)

    def __init__(self, icon, title, description, key_path: str,
                 min_val: int, max_val: int, parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path

        self.value_label = StrongBodyLabel(self)
        self.value_label.setMinimumWidth(30)

        self.slider = Slider(Qt.Horizontal, self)
        self.slider.setMinimumWidth(150)
        self.slider.setRange(min_val, max_val)

        current = settings.get(key_path, min_val)
        self.slider.setValue(current)
        self.value_label.setText(str(current))

        self.slider.valueChanged.connect(self._on_changed)

        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.slider, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_changed(self, value: int):
        self.value_label.setText(str(value))
        settings.set(self.key_path, value)
        self.value_changed.emit(value)


class SwitchCard(SettingCard):
    """Setting card with a switch toggle."""

    checked_changed = Signal(bool)

    def __init__(self, icon, title, description, key_path: str, parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path

        self.switch = SwitchButton(self)
        self.switch.setChecked(settings.get(key_path, False))
        self.switch.checkedChanged.connect(self._on_changed)

        self.hBoxLayout.addWidget(self.switch, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_changed(self, checked: bool):
        settings.set(self.key_path, checked)
        self.checked_changed.emit(checked)


class TextInputCard(SettingCard):
    """Setting card with a text input field."""

    value_changed = Signal(str)

    def __init__(self, icon, title, description, key_path: str,
                 placeholder: str = "", parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path

        self.input = LineEdit(self)
        self.input.setMinimumWidth(200)
        self.input.setPlaceholderText(placeholder)

        current = settings.get(key_path, "")
        self.input.setText(str(current))

        self.input.textChanged.connect(self._on_changed)

        self.hBoxLayout.addWidget(self.input, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _on_changed(self, text: str):
        try:
            value = float(text) if text else text
            settings.set(self.key_path, value)
            self.value_changed.emit(text)
        except ValueError:
            settings.set(self.key_path, text)
            self.value_changed.emit(text)


# ---------------------------------------------------------------------------
# Main Settings Tab
# ---------------------------------------------------------------------------

class SettingsTab(ScrollArea):
    """
    Comprehensive Settings Tab with model selection and preferences.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsInterface")
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)

        self.setStyleSheet("background-color: transparent;")
        self.scrollWidget.setObjectName("scrollWidget")

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)

        # Bug 3 fix: keep a list of active fetcher threads so Python's GC
        # cannot destroy a QThread wrapper while the C++ thread is still running.
        self._fetcher_refs: list = []

        self._available_models: list = []

        # Bug 2 fix: track whether the first showEvent has already triggered the
        # initial fetch so we don't double-fetch on first open.
        self._shown_once: bool = False

        self._init_ui()
        self._fetch_models()   # Kick off fetch immediately at init time

    # ── Bug 2 fix: re-fetch models every time the tab becomes visible ─────
    def showEvent(self, event):
        super().showEvent(event)
        if self._shown_once:
            # Subsequent visits (e.g. user returned from Model Browser after
            # downloading a new model) — silently refresh the combos.
            self._fetch_models()
        self._shown_once = True

    def _init_ui(self):

        # ── Apply & Refresh ───────────────────────────────────────────────────
        self.apply_group = SettingCardGroup("Apply Changes", self.scrollWidget)

        self.apply_card = PrimaryPushSettingCard(
            "Apply & Refresh All",
            FIF.SYNC,
            "Apply Settings",
            "Save all changes and refresh the dashboard, weather, and news immediately",
            self.apply_group
        )
        self.apply_card.clicked.connect(self._on_apply)
        self.apply_group.addSettingCard(self.apply_card)
        self.expandLayout.addWidget(self.apply_group)

        # ── Personalization ──────────────────────────────────────────────────
        self.personal_group = SettingCardGroup("Personalization", self.scrollWidget)

        self.theme_card = ComboBoxCard(
            FIF.BRUSH,
            "Application Theme",
            "Change the appearance of the application",
            ["Light", "Dark", "Auto"],
            "theme",
            self.personal_group
        )
        self.theme_card.value_changed.connect(self._on_theme_changed)
        self.personal_group.addSettingCard(self.theme_card)
        self.expandLayout.addWidget(self.personal_group)

        # ── AI Models ────────────────────────────────────────────────────────
        self.ai_group = SettingCardGroup("AI Models", self.scrollWidget)

        self.chat_model_card = ModelSelectCard(
            FIF.CHAT,
            "Chat Model",
            "Ollama model for general chat responses",
            "models.chat",
            self.ai_group
        )
        self.ai_group.addSettingCard(self.chat_model_card)

        self.web_agent_model_card = ModelSelectCard(
            FIF.GLOBE,
            "Web Agent Model",
            "Vision-language model for browser automation",
            "models.web_agent",
            self.ai_group
        )
        self.ai_group.addSettingCard(self.web_agent_model_card)

        self.router_model_card = SettingCard(
            FIF.ROBOT,
            "Function Router Model",
            f"Local FunctionGemma model at: {LOCAL_ROUTER_PATH}",
            self.ai_group
        )
        self.ai_group.addSettingCard(self.router_model_card)

        self.refresh_models_card = PushSettingCard(
            "Refresh",
            FIF.SYNC,
            "Refresh Models",
            "Fetch available models from Ollama",
            self.ai_group
        )
        self.refresh_models_card.clicked.connect(self._fetch_models)
        self.ai_group.addSettingCard(self.refresh_models_card)
        self.expandLayout.addWidget(self.ai_group)

        # ── Connection ───────────────────────────────────────────────────────
        self.connection_group = SettingCardGroup("Connection", self.scrollWidget)

        self.ollama_url_card = UrlInputCard(
            FIF.LINK,
            "Ollama URL",
            "API endpoint for Ollama server",
            "ollama_url",
            self.connection_group
        )
        self.connection_group.addSettingCard(self.ollama_url_card)
        self.expandLayout.addWidget(self.connection_group)

        # ── Voice & Audio ────────────────────────────────────────────────────
        self.voice_group = SettingCardGroup("Voice & Audio", self.scrollWidget)

        self.auto_start_card = SwitchCard(
            FIF.MICROPHONE,
            "Auto-Start Voice on Launch",
            "Automatically activate wake-word listening when Plia starts",
            "voice.auto_start",
            self.voice_group
        )
        self.voice_group.addSettingCard(self.auto_start_card)

        self.startup_greeting_card = SwitchCard(
            FIF.VOLUME,
            "Startup Voice Greeting",
            "Speak a confirmation message when voice assistant goes online at startup",
            "voice.startup_greeting",
            self.voice_group
        )
        self.voice_group.addSettingCard(self.startup_greeting_card)

        from core.stt import SUPPORTED_WAKE_WORDS
        self.wake_word_card = ComboBoxCard(
            FIF.MICROPHONE,
            "Wake Word",
            "The word you say to activate the voice assistant",
            SUPPORTED_WAKE_WORDS,
            "voice.wake_word",
            self.voice_group
        )
        self.voice_group.addSettingCard(self.wake_word_card)

        self.wake_sensitivity_card = SliderCard(
            FIF.SPEED_HIGH,
            "Wake Word Sensitivity",
            "Higher = activates more easily but risks false triggers (recommended: 40-60)",
            "voice.sensitivity_pct",
            0, 100,
            self.voice_group
        )
        self.voice_group.addSettingCard(self.wake_sensitivity_card)

        piper_voices = [
            "en_GB-northern_english_male-medium",
            "en_GB-alba-medium",
            "en_US-amy-medium",
            "en_US-lessac-medium",
            "en_US-libritts-high",
        ]
        self.tts_voice_card = ComboBoxCard(
            FIF.VOLUME,
            "TTS Voice",
            "Voice model for text-to-speech",
            piper_voices,
            "tts.voice",
            self.voice_group
        )
        self.voice_group.addSettingCard(self.tts_voice_card)
        self.expandLayout.addWidget(self.voice_group)

        # ── Weather Location ─────────────────────────────────────────────────
        self.weather_group = SettingCardGroup("Weather", self.scrollWidget)

        from core.weather import PROVIDER_NAMES, BOM_STATIONS
        self.weather_provider_card = ComboBoxCard(
            FIF.CLOUD,
            "Weather Provider",
            "Select your preferred weather data source",
            PROVIDER_NAMES,
            "weather.provider",
            self.weather_group
        )
        self.weather_provider_card.value_changed.connect(self._on_weather_provider_changed)
        self.weather_group.addSettingCard(self.weather_provider_card)

        station_labels = list(BOM_STATIONS.keys())
        self.bom_station_card = ComboBoxCard(
            FIF.PIN,
            "BOM Observation Station",
            "Choose the nearest BOM station to your location",
            station_labels,
            "weather.bom_station_label",
            self.weather_group
        )
        self.bom_station_card.value_changed.connect(self._on_bom_station_changed)
        self.weather_group.addSettingCard(self.bom_station_card)

        self.weather_custom_url_card = TextInputCard(
            FIF.LINK,
            "Custom Weather URL",
            "Your Open-Meteo-compatible API endpoint (e.g. https://api.open-meteo.com/v1/forecast)",
            "weather.custom_url",
            "https://",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.weather_custom_url_card)
        provider_now = settings.get("weather.provider", "BOM (Australia)")
        self.weather_custom_url_card.setVisible(provider_now == "Custom URL")
        self.bom_station_card.setVisible(provider_now == "BOM (Australia)")

        self.weather_unit_card = ComboBoxCard(
            FIF.SPEED_HIGH,
            "Temperature Unit",
            "Display temperature in Celsius or Fahrenheit",
            ["celsius", "fahrenheit"],
            "weather.temperature_unit",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.weather_unit_card)

        self.city_card = TextInputCard(
            FIF.PIN,
            "City Name",
            "Display name for your location",
            "weather.city",
            "New York, NY",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.city_card)

        self.latitude_card = TextInputCard(
            FIF.PIN,
            "Latitude",
            "Latitude coordinate (-90 to 90)",
            "weather.latitude",
            "40.7128",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.latitude_card)

        self.longitude_card = TextInputCard(
            FIF.GLOBE,
            "Longitude",
            "Longitude coordinate (-180 to 180)",
            "weather.longitude",
            "-74.0060",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.longitude_card)
        self.expandLayout.addWidget(self.weather_group)

        # ── General ──────────────────────────────────────────────────────────
        self.general_group = SettingCardGroup("General", self.scrollWidget)

        self.max_history_card = SliderCard(
            FIF.HISTORY,
            "Max Chat History",
            "Number of messages to keep in context",
            "general.max_history",
            5, 50,
            self.general_group
        )
        self.general_group.addSettingCard(self.max_history_card)

        self.auto_news_card = SwitchCard(
            FIF.DOCUMENT,
            "Auto-fetch News",
            "Automatically fetch news on startup",
            "general.auto_fetch_news",
            self.general_group
        )
        self.general_group.addSettingCard(self.auto_news_card)
        self.expandLayout.addWidget(self.general_group)

        # ── News Cache Management ─────────────────────────────────────────────
        self.news_group = SettingCardGroup("News Cache", self.scrollWidget)

        self.news_retention_card = ComboBoxCard(
            FIF.DATE_TIME,
            "Article Retention Period",
            "Automatically remove locally stored Briefing articles after this period",
            ["1 day", "3 days", "7 days", "14 days", "30 days", "Never"],
            "news.retention",
            self.news_group
        )
        self.news_group.addSettingCard(self.news_retention_card)

        self.auto_purge_card = SwitchCard(
            FIF.SYNC,
            "Auto-purge on Startup",
            "Automatically remove expired articles each time Plia starts",
            "news.auto_purge",
            self.news_group
        )
        self.news_group.addSettingCard(self.auto_purge_card)

        self.purge_now_card = PushSettingCard(
            "Clear Now",
            FIF.DELETE,
            "Clear Cached Articles",
            "Immediately remove all locally stored Briefing articles",
            self.news_group
        )
        self.purge_now_card.clicked.connect(self._on_purge_now)
        self.news_group.addSettingCard(self.purge_now_card)

        self.expandLayout.addWidget(self.news_group)

        # ── Calendar Integration ──────────────────────────────────────────────
        self.calendar_group = SettingCardGroup("Calendar Integration", self.scrollWidget)

        self.google_enable_card = SwitchCard(
            FIF.CALENDAR,
            "Google Calendar",
            "Sync Google Calendar events into the Planner tab",
            "calendar.google.enabled",
            self.calendar_group
        )
        self.calendar_group.addSettingCard(self.google_enable_card)

        self.google_client_id_card = TextInputCard(
            FIF.EDIT,
            "Google Client ID",
            "OAuth 2.0 Client ID from Google Cloud Console",
            "calendar.google.client_id",
            "your-client-id.apps.googleusercontent.com",
            self.calendar_group
        )
        self.calendar_group.addSettingCard(self.google_client_id_card)

        self.google_client_secret_card = TextInputCard(
            FIF.HIDE,
            "Google Client Secret",
            "OAuth 2.0 Client Secret from Google Cloud Console",
            "calendar.google.client_secret",
            "your-client-secret",
            self.calendar_group
        )
        self.calendar_group.addSettingCard(self.google_client_secret_card)

        self.google_connect_card = PushSettingCard(
            "Connect Google",
            FIF.LINK,
            "Authorise Google Calendar",
            "Opens your browser to sign in and grant calendar access",
            self.calendar_group
        )
        self.google_connect_card.clicked.connect(self._on_google_connect)
        self.calendar_group.addSettingCard(self.google_connect_card)

        self.google_disconnect_card = PushSettingCard(
            "Disconnect",
            FIF.CANCEL,
            "Remove Google Calendar",
            "Revoke access and delete stored Google tokens",
            self.calendar_group
        )
        self.google_disconnect_card.clicked.connect(self._on_google_disconnect)
        self.calendar_group.addSettingCard(self.google_disconnect_card)

        self.outlook_enable_card = SwitchCard(
            FIF.CALENDAR,
            "Outlook / Microsoft 365 Calendar",
            "Sync Outlook Calendar events into the Planner tab",
            "calendar.outlook.enabled",
            self.calendar_group
        )
        self.calendar_group.addSettingCard(self.outlook_enable_card)

        self.outlook_client_id_card = TextInputCard(
            FIF.EDIT,
            "Outlook Application (Client) ID",
            "App ID from Azure Portal → App registrations",
            "calendar.outlook.client_id",
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            self.calendar_group
        )
        self.calendar_group.addSettingCard(self.outlook_client_id_card)

        self.outlook_tenant_card = TextInputCard(
            FIF.GLOBE,
            "Tenant ID",
            "Azure Tenant ID — use 'common' for personal accounts",
            "calendar.outlook.tenant_id",
            "common",
            self.calendar_group
        )
        self.calendar_group.addSettingCard(self.outlook_tenant_card)

        self.outlook_connect_card = PushSettingCard(
            "Connect Outlook",
            FIF.LINK,
            "Authorise Outlook Calendar",
            "Opens your browser to sign in and grant calendar access",
            self.calendar_group
        )
        self.outlook_connect_card.clicked.connect(self._on_outlook_connect)
        self.calendar_group.addSettingCard(self.outlook_connect_card)

        self.outlook_disconnect_card = PushSettingCard(
            "Disconnect",
            FIF.CANCEL,
            "Remove Outlook Calendar",
            "Revoke access and delete stored Outlook tokens",
            self.calendar_group
        )
        self.outlook_disconnect_card.clicked.connect(self._on_outlook_disconnect)
        self.calendar_group.addSettingCard(self.outlook_disconnect_card)

        self.expandLayout.addWidget(self.calendar_group)

        # ── Desktop Agent ────────────────────────────────────────────────────
        self.desktop_group = SettingCardGroup("Desktop Agent (AI Computer Control)", self.scrollWidget)

        self.desktop_info_card = SettingCard(
            FIF.ROBOT,
            "How it works",
            "Takes screenshots of your screen and uses Qwen VL to control the mouse and "
            "keyboard. No API keys or bot tokens required. Just say 'Open Discord and "
            "summarise #general' — the agent opens it and reads it visually.",
            self.desktop_group
        )
        self.desktop_group.addSettingCard(self.desktop_info_card)

        self.desktop_model_card = ModelSelectCard(
            FIF.GLOBE,
            "Desktop Agent Model",
            "Vision-language model used to see and control the screen (default: qwen3-vl:4b)",
            "models.web_agent",
            self.desktop_group
        )
        self.desktop_group.addSettingCard(self.desktop_model_card)

        self.desktop_steps_card = SliderCard(
            FIF.SPEED_HIGH,
            "Max Agent Steps",
            "Maximum screenshot→action cycles before the agent stops (safety limit)",
            "desktop_agent.max_steps",
            5, 50,
            self.desktop_group
        )
        self.desktop_group.addSettingCard(self.desktop_steps_card)
        self.expandLayout.addWidget(self.desktop_group)

        # ── About ────────────────────────────────────────────────────────────
        self.about_group = SettingCardGroup("About", self.scrollWidget)

        self.about_card = PrimaryPushSettingCard(
            "Check Update",
            FIF.INFO,
            "About Plia",
            "Version 0.2.0 (Alpha)",
            self.about_group
        )
        self.about_group.addSettingCard(self.about_card)

        self.reset_card = PushSettingCard(
            "Reset",
            FIF.CANCEL,
            "Reset Settings",
            "Restore all settings to defaults",
            self.about_group
        )
        self.reset_card.clicked.connect(self._on_reset)
        self.about_group.addSettingCard(self.reset_card)

        self.delete_settings_card = PushSettingCard(
            "Delete & Restart",
            FIF.DELETE,
            "Delete Settings File",
            "Delete ~/.plia/settings.json and restart — fixes missing setting keys",
            self.about_group
        )
        self.delete_settings_card.clicked.connect(self._on_delete_settings)
        self.about_group.addSettingCard(self.delete_settings_card)
        self.expandLayout.addWidget(self.about_group)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_apply(self):
        """Apply all settings and refresh every live display immediately."""
        errors = []

        try:
            main_win = self.window()
            if main_win and hasattr(main_win, 'dashboard_view') and main_win.dashboard_view:
                main_win.dashboard_view.refresh()
        except Exception as e:
            errors.append(f"Dashboard: {e}")

        try:
            main_win = self.window()
            if main_win and hasattr(main_win, 'briefing_view') and main_win.briefing_view:
                main_win.briefing_view.load_news()
        except Exception as e:
            errors.append(f"Briefing: {e}")

        try:
            from core.news import news_manager
            news_manager.cache.clear()
        except Exception as e:
            errors.append(f"News cache: {e}")

        try:
            pct = settings.get("voice.sensitivity_pct", 40)
            settings.set("voice.sensitivity", round(pct / 100.0, 2))
        except Exception as e:
            errors.append(f"Sensitivity: {e}")

        try:
            from core.tts import tts
            new_voice = settings.get("tts.voice", "en_GB-northern_english_male-medium")
            if new_voice:
                import threading
                threading.Thread(target=lambda: tts.change_voice(new_voice), daemon=True).start()
        except Exception as e:
            errors.append(f"TTS voice: {e}")

        try:
            from core.voice_assistant import voice_assistant
            if voice_assistant.running:
                voice_assistant.stop()
                import threading, time
                def _restart_va():
                    time.sleep(1.5)
                    if voice_assistant.initialize():
                        voice_assistant.start()
                    else:
                        print("[Settings] Voice assistant failed to restart.")
                threading.Thread(target=_restart_va, daemon=True).start()
        except Exception as e:
            errors.append(f"Voice assistant: {e}")

        win = self.window()
        if win is None:
            return

        if errors:
            InfoBar.warning(
                title="Partially Applied",
                content="Some components could not refresh: " + "; ".join(errors),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=win
            )
        else:
            InfoBar.success(
                title="Settings Applied",
                content="All displays refreshed. Voice assistant restarting with new wake word.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=win
            )

    def _on_weather_provider_changed(self, value: str):
        self.weather_custom_url_card.setVisible(value == "Custom URL")
        self.bom_station_card.setVisible(value == "BOM (Australia)")

    def _on_bom_station_changed(self, label: str):
        from core.weather import BOM_STATIONS
        station_id = BOM_STATIONS.get(label, "94609")
        settings.set("weather.bom_station", station_id)
        settings.set("weather.bom_station_label", label)

    def _on_theme_changed(self, value: str):
        theme_map = {"Dark": Theme.DARK, "Light": Theme.LIGHT, "Auto": Theme.AUTO}
        setTheme(theme_map.get(value, Theme.DARK))

    def _on_delete_settings(self):
        import os
        from pathlib import Path
        settings_file = Path.home() / ".plia" / "settings.json"
        win = self.window()
        try:
            if settings_file.exists():
                settings_file.unlink()
                if win:
                    InfoBar.success(
                        title="Settings File Deleted",
                        content="Please restart Plia — a fresh settings.json will be created with all defaults.",
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=8000,
                        parent=win
                    )
            else:
                if win:
                    InfoBar.warning(
                        title="File Not Found",
                        content=f"Settings file not found at {settings_file}",
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=4000,
                        parent=win
                    )
        except Exception as e:
            if win:
                InfoBar.error(
                    title="Error",
                    content=f"Could not delete settings file: {e}",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=win
                )

    def _on_reset(self):
        settings.reset_to_defaults()
        win = self.window()
        if win:
            InfoBar.success(
                title="Settings Reset",
                content="All settings restored to defaults. Please restart the app.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=win
            )

    def _on_purge_now(self):
        win = self.window()
        try:
            from gui.tabs.briefing import save_local_cache
            save_local_cache({})
            if win:
                InfoBar.success(
                    title="Cache Cleared",
                    content="All locally stored Briefing articles have been removed.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=win
                )
        except Exception as e:
            if win:
                InfoBar.error(
                    title="Error",
                    content=f"Could not clear cache: {e}",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=win
                )

    # ── Model fetching ────────────────────────────────────────────────────────

    def _fetch_models(self):
        """
        Start a background thread to fetch the list of Ollama models.

        Bug 3 fix: append each new ModelFetcher to self._fetcher_refs so Python
        cannot GC the wrapper while the C++ thread is still running.  Each thread
        removes itself from the list via its finished signal once Qt is done with it.
        """
        url = settings.get("ollama_url", "http://localhost:11434")
        fetcher = ModelFetcher(url)
        fetcher.models_fetched.connect(self._on_models_fetched)
        fetcher.error_occurred.connect(self._on_models_error)

        # Bug 3 fix: keep Python reference alive until the Qt thread is fully done.
        self._fetcher_refs.append(fetcher)
        fetcher.finished.connect(
            lambda f=fetcher: self._fetcher_refs.remove(f)
            if f in self._fetcher_refs else None
        )

        fetcher.start()
        # Keep compat attribute for any code that checked self.model_fetcher
        self.model_fetcher = fetcher

    @Slot(list)
    def _on_models_fetched(self, models: list):
        """
        Populate all ModelSelectCard combos with the fresh model list.
        Bug 1 fix is inside ModelSelectCard.update_models (blockSignals).
        Bug 4 fix: guard self.window() before calling InfoBar.
        """
        self._available_models = models
        self.chat_model_card.update_models(models)
        self.web_agent_model_card.update_models(models)
        self.desktop_model_card.update_models(models)

        # Bug 4 fix: only call InfoBar if the widget is attached to a window.
        win = self.window()
        if win is None:
            return
        InfoBar.success(
            title="Models Loaded",
            content=f"Found {len(models)} model(s)",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=win
        )

    @Slot(str)
    def _on_models_error(self, error: str):
        """
        Show an error toast if Ollama could not be reached.
        Bug 4 fix: guard self.window().
        """
        win = self.window()
        if win is None:
            # Widget not yet in a window — log and move on.
            print(f"[Settings] Could not fetch models (no window yet): {error}")
            return
        InfoBar.warning(
            title="Could not fetch models",
            content=error,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=win
        )

    # ── Calendar handlers ─────────────────────────────────────────────────────

    def _on_google_connect(self):
        client_id = settings.get("calendar.google.client_id", "").strip()
        client_secret = settings.get("calendar.google.client_secret", "").strip()
        win = self.window()

        if not client_id or not client_secret:
            if win:
                InfoBar.warning(
                    title="Missing Credentials",
                    content="Please enter your Google Client ID and Client Secret first.",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=4000,
                    parent=win
                )
            return

        try:
            from core.calendar_sync import google_auth_flow
            google_auth_flow(client_id, client_secret)
            if win:
                InfoBar.success(
                    title="Google Calendar Connected",
                    content="Authorisation complete. Events will appear in the Planner.",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=4000,
                    parent=win
                )
        except Exception as e:
            if win:
                InfoBar.error(
                    title="Google Auth Failed",
                    content=str(e),
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=6000,
                    parent=win
                )

    def _on_google_disconnect(self):
        win = self.window()
        try:
            from core.calendar_sync import google_revoke
            google_revoke()
            settings.set("calendar.google.enabled", False)
            self.google_enable_card.switch.setChecked(False)
            if win:
                InfoBar.success(
                    title="Google Calendar Removed",
                    content="Stored tokens deleted. Calendar no longer synced.",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=3000,
                    parent=win
                )
        except Exception as e:
            if win:
                InfoBar.error(
                    title="Error", content=str(e),
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=4000,
                    parent=win
                )

    def _on_outlook_connect(self):
        client_id = settings.get("calendar.outlook.client_id", "").strip()
        tenant_id = settings.get("calendar.outlook.tenant_id", "common").strip()
        win = self.window()

        if not client_id:
            if win:
                InfoBar.warning(
                    title="Missing Credentials",
                    content="Please enter your Outlook Application (Client) ID first.",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=4000,
                    parent=win
                )
            return

        try:
            from core.calendar_sync import outlook_auth_flow
            outlook_auth_flow(client_id, tenant_id)
            if win:
                InfoBar.success(
                    title="Outlook Calendar Connected",
                    content="Authorisation complete. Events will appear in the Planner.",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=4000,
                    parent=win
                )
        except Exception as e:
            if win:
                InfoBar.error(
                    title="Outlook Auth Failed",
                    content=str(e),
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=6000,
                    parent=win
                )

    def _on_outlook_disconnect(self):
        win = self.window()
        try:
            from core.calendar_sync import outlook_revoke
            outlook_revoke()
            settings.set("calendar.outlook.enabled", False)
            self.outlook_enable_card.switch.setChecked(False)
            if win:
                InfoBar.success(
                    title="Outlook Calendar Removed",
                    content="Stored tokens deleted. Calendar no longer synced.",
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=3000,
                    parent=win
                )
        except Exception as e:
            if win:
                InfoBar.error(
                    title="Error", content=str(e),
                    orient=Qt.Horizontal, isClosable=True,
                    position=InfoBarPosition.TOP, duration=4000,
                    parent=win
                )
