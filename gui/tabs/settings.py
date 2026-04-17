"""
Comprehensive Settings Tab with model selection, connection settings, and preferences.
"""

from config import LOCAL_ROUTER_PATH, RESPONDER_MODEL

import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame, QSizePolicy
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
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
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
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            if response.status_code == 200:
                self.success.emit()
            else:
                self.failed.emit(f"HTTP {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.failed.emit("Connection refused")
        except Exception as e:
            self.failed.emit(str(e))


class GeocoderThread(QThread):
    """
    Calls the Open-Meteo Geocoding API in a background thread so the
    Settings UI stays responsive during city searches.
    """
    results_ready = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, city: str, country_code: str):
        super().__init__()
        self.city         = city
        self.country_code = country_code

    def run(self):
        try:
            from core.weather import geocode_city
            results = geocode_city(self.city, self.country_code)
            self.results_ready.emit(results)
        except Exception as e:
            self.error_occurred.emit(str(e))


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
        self.combo.setPlaceholderText("Select model...")

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
        current = self.combo.currentText()
        self.combo.clear()
        self.combo.addItems(models)
        if current in models:
            self.combo.setCurrentText(current)
        elif models:
            self.combo.setCurrentIndex(0)


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
        InfoBar.success(
            title="Connected",
            content="Ollama is reachable!",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self.window()
        )

    @Slot(str)
    def _on_test_failed(self, error: str):
        InfoBar.error(
            title="Connection Failed",
            content=error,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.window()
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


class WeatherLocationCard(QFrame):
    """
    Full-width, multi-row weather location card.

    Inherits QFrame instead of SettingCard so it can use a proper
    QVBoxLayout with every field on its own clearly visible line.

    Flow:
      1. User selects Country from dropdown — City dropdown auto-populates
         with major cities for that country (from CITIES_BY_COUNTRY).
      2. User selects a City from the city dropdown — geocoding fires
         automatically via Open-Meteo Geocoding API (free, no API key).
      3. Resolved coordinates appear in the location label.
      4. User clicks Apply → saves weather.country, weather.city,
         weather.latitude, weather.longitude to settings_store.

      Alternative: If the desired city is not in the City dropdown, use
      the "Not listed? Search:" text field and press Search.
    """

    location_applied = Signal(str, str, float, float)  # country, city_display, lat, lon

    # ── Card-level styling ───────────────────────────────────────────────
    _CARD_STYLE = """
        WeatherLocationCard {
            background-color: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
        }
    """
    _LABEL_STYLE   = "color: rgba(255,255,255,0.85); font-size: 13px;"
    _DESC_STYLE    = "color: rgba(255,255,255,0.45); font-size: 12px;"
    _COORDS_STYLE  = (
        "color: rgba(255,255,255,0.65); font-size: 12px; "
        "padding: 6px 10px; "
        "background: rgba(255,255,255,0.04); "
        "border-radius: 4px;"
    )
    _DIVIDER_STYLE = "background: rgba(255,255,255,0.08);"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WeatherLocationCard")
        self.setStyleSheet(self._CARD_STYLE)
        # Allow the card to grow vertically to show all rows — never clip
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumHeight(320)
        self._geocoder = None
        self._results: list = []
        self._initializing = False   # guard against spurious signals during init
        self._build_ui()
        self._restore_saved()

    # ── UI construction ──────────────────────────────────────────────────

    def _build_ui(self):
        from core.weather import COUNTRIES
        from PySide6.QtWidgets import QLayout

        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSizeConstraint(QLayout.SetMinimumSize)

        # ── Header: icon + title + description ──────────────────────────
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        pin_lbl = QLabel(self)
        pin_lbl.setPixmap(FIF.PIN.icon().pixmap(18, 18))
        pin_lbl.setFixedSize(18, 18)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = StrongBodyLabel("Weather Location", self)
        desc_lbl = QLabel(
            "Select your Country and City — coordinates are resolved automatically", self
        )
        desc_lbl.setStyleSheet(self._DESC_STYLE)
        title_col.addWidget(title_lbl)
        title_col.addWidget(desc_lbl)

        header_row.addWidget(pin_lbl, 0, Qt.AlignTop)
        header_row.addLayout(title_col, 1)
        outer.addLayout(header_row)

        outer.addSpacing(12)

        # ── Thin horizontal divider ──────────────────────────────────────
        divider = QFrame(self)
        divider.setFixedHeight(1)
        divider.setStyleSheet(self._DIVIDER_STYLE)
        outer.addWidget(divider)

        outer.addSpacing(14)

        # ── Row 1: Country dropdown ──────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        country_lbl = QLabel("Country:", self)
        country_lbl.setFixedWidth(80)
        country_lbl.setStyleSheet(self._LABEL_STYLE)
        self.country_combo = ComboBox(self)
        self.country_combo.setMinimumWidth(220)
        for display_name, _ in COUNTRIES:
            self.country_combo.addItem(display_name)
        self.country_combo.currentIndexChanged.connect(self._on_country_changed)
        row1.addWidget(country_lbl, 0, Qt.AlignVCenter)
        row1.addWidget(self.country_combo, 1)
        outer.addLayout(row1)

        outer.addSpacing(10)

        # ── Row 2: City dropdown (auto-populated from CITIES_BY_COUNTRY) ─
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        city_lbl = QLabel("City:", self)
        city_lbl.setFixedWidth(80)
        city_lbl.setStyleSheet(self._LABEL_STYLE)
        self.city_combo = ComboBox(self)
        self.city_combo.setMinimumWidth(220)
        self.city_combo.setPlaceholderText("Select country first…")
        # Populated by _populate_city_combo; signals connected after init guard is set
        self.city_combo.currentIndexChanged.connect(self._on_city_combo_changed)
        row2.addWidget(city_lbl, 0, Qt.AlignVCenter)
        row2.addWidget(self.city_combo, 1)
        outer.addLayout(row2)

        outer.addSpacing(12)

        # ── Search section: for cities not listed in the dropdown ────────
        search_hdr = QLabel("Not listed? Search for any city:", self)
        search_hdr.setStyleSheet(self._DESC_STYLE)
        outer.addWidget(search_hdr)
        outer.addSpacing(6)

        row3 = QHBoxLayout()
        row3.setSpacing(12)
        spacer_lbl = QLabel("", self)
        spacer_lbl.setFixedWidth(80)
        self.city_input = LineEdit(self)
        self.city_input.setPlaceholderText("Type any city name and press Search…")
        self.city_input.returnPressed.connect(self._do_search)
        self.search_btn = PrimaryPushButton("Search", self)
        self.search_btn.setFixedWidth(90)
        self.search_btn.clicked.connect(self._do_search)
        row3.addWidget(spacer_lbl, 0, Qt.AlignVCenter)
        row3.addWidget(self.city_input, 1)
        row3.addWidget(self.search_btn, 0)
        outer.addLayout(row3)

        outer.addSpacing(10)

        # ── Results dropdown (hidden until geocoding returns results) ────
        self.results_combo = ComboBox(self)
        self.results_combo.setPlaceholderText("Search results appear here…")
        self.results_combo.setVisible(False)
        self.results_combo.currentIndexChanged.connect(self._on_result_selected)
        outer.addWidget(self.results_combo)

        outer.addSpacing(8)

        # ── Resolved location + coordinates ─────────────────────────────
        self.location_label = QLabel("", self)
        self.location_label.setWordWrap(True)
        self.location_label.setStyleSheet(self._COORDS_STYLE)
        self.location_label.setVisible(False)
        outer.addWidget(self.location_label)

        outer.addSpacing(12)

        # ── Apply button (left-aligned) ──────────────────────────────────
        btn_row = QHBoxLayout()
        self.apply_btn = PrimaryPushButton("Apply Location", self)
        self.apply_btn.setFixedWidth(150)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_location)
        btn_row.addWidget(self.apply_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

    # ── City dropdown helpers ────────────────────────────────────────────

    def _populate_city_combo(self, country_name: str):
        """
        Fill the City dropdown with major cities for *country_name*.
        Signals are blocked during population so _on_city_combo_changed
        is not triggered spuriously.
        """
        from core.weather import CITIES_BY_COUNTRY
        self.city_combo.blockSignals(True)
        self.city_combo.clear()
        cities = CITIES_BY_COUNTRY.get(country_name, [])
        if cities:
            self.city_combo.addItems(cities)
            self.city_combo.setPlaceholderText("Select city…")
        else:
            self.city_combo.setPlaceholderText("No preset cities — use Search below")
        self.city_combo.blockSignals(False)

    # ── Restore saved values on startup ─────────────────────────────────

    def _restore_saved(self):
        """Pre-fill the card from persisted settings so current location is visible."""
        from core.weather import COUNTRIES
        self._initializing = True

        country = settings.get("weather.country", "Australia")
        city    = settings.get("weather.city",    "Kelmscott, Western Australia, Australia")
        lat     = settings.get("weather.latitude",  -32.1151)
        lon     = settings.get("weather.longitude", 116.0255)

        # Restore country selection
        for i, (name, _) in enumerate(COUNTRIES):
            if name == country:
                self.country_combo.blockSignals(True)
                self.country_combo.setCurrentIndex(i)
                self.country_combo.blockSignals(False)
                break

        # Populate city dropdown for the saved country
        self._populate_city_combo(country)

        # Try to pre-select the saved city in the city dropdown
        if city:
            city_base = city.split(",")[0].strip()
            idx = self.city_combo.findText(city_base)
            if idx >= 0:
                self.city_combo.blockSignals(True)
                self.city_combo.setCurrentIndex(idx)
                self.city_combo.blockSignals(False)
            else:
                # City is not in the preset list — show it in the search field
                self.city_input.setText(city_base)

        # Show the currently saved coordinates
        if city and (lat or lon):
            self.location_label.setText(
                f"📍  {city}\n"
                f"    Lat {float(lat):.4f}  ·  Lon {float(lon):.4f}"
            )
            self.location_label.setVisible(True)
            # Apply is disabled on startup — no unsaved change pending yet
            self.apply_btn.setEnabled(False)

        self._initializing = False

    # ── Slots ────────────────────────────────────────────────────────────

    def _on_country_changed(self, _index: int):
        """Update the City dropdown and clear stale results when country changes."""
        if self._initializing:
            return
        country_name = self.country_combo.currentText()
        self._populate_city_combo(country_name)
        self._results = []
        self.results_combo.clear()
        self.results_combo.setVisible(False)
        self.apply_btn.setEnabled(False)

    def _on_city_combo_changed(self, index: int):
        """Auto-geocode when the user selects a city from the City dropdown."""
        if self._initializing:
            return
        city_text = self.city_combo.currentText()
        if not city_text:
            return
        self._start_geocode(city_text)

    def _get_country_code(self) -> str:
        from core.weather import COUNTRIES
        idx = self.country_combo.currentIndex()
        if 0 <= idx < len(COUNTRIES):
            return COUNTRIES[idx][1]   # ISO-3166-1 alpha-2, or "" for Any
        return ""

    def _do_search(self):
        """Manual search — used when the desired city is not in the City dropdown."""
        city_text = self.city_input.text().strip()
        if not city_text:
            return
        self._start_geocode(city_text)

    def _start_geocode(self, city_text: str):
        """Kick off GeocoderThread for *city_text* filtered by the selected country."""
        self.search_btn.setEnabled(False)
        self.search_btn.setText("…")
        self.results_combo.setVisible(False)
        self.apply_btn.setEnabled(False)
        self._results = []

        self._geocoder = GeocoderThread(city_text, self._get_country_code())
        self._geocoder.results_ready.connect(self._on_results)
        self._geocoder.error_occurred.connect(self._on_search_error)
        self._geocoder.finished.connect(self._on_search_done)
        self._geocoder.start()

    def _on_results(self, results: list):
        self._results = results
        self.results_combo.clear()
        if results:
            for r in results:
                self.results_combo.addItem(r["display"])
            self.results_combo.setVisible(True)
            self.results_combo.setCurrentIndex(0)
            self._on_result_selected(0)
        else:
            self.results_combo.addItem("No results — try a different spelling or country")
            self.results_combo.setVisible(True)
            self.apply_btn.setEnabled(False)

    def _on_result_selected(self, index: int):
        if 0 <= index < len(self._results):
            r = self._results[index]
            lat, lon = r["latitude"], r["longitude"]
            self.location_label.setText(
                f"📍  {r['display']}\n"
                f"    Lat {lat:.4f}  ·  Lon {lon:.4f}"
            )
            self.location_label.setVisible(True)
            self.apply_btn.setEnabled(True)
        else:
            self.apply_btn.setEnabled(False)

    def _on_search_error(self, error: str):
        self.results_combo.clear()
        self.results_combo.addItem(f"Search failed: {error}")
        self.results_combo.setVisible(True)
        self.apply_btn.setEnabled(False)

    def _on_search_done(self):
        self.search_btn.setEnabled(True)
        self.search_btn.setText("Search")

    def _apply_location(self):
        """Persist the selected city's coordinates and display name."""
        idx = self.results_combo.currentIndex()
        if not (0 <= idx < len(self._results)):
            return

        r            = self._results[idx]
        country_name = self.country_combo.currentText()

        settings.set("weather.latitude",     r["latitude"])
        settings.set("weather.longitude",    r["longitude"])
        settings.set("weather.city",         r["display"])
        settings.set("weather.country",      country_name)
        settings.set("weather.country_code", r["country_code"])

        self.location_applied.emit(
            country_name, r["display"], r["latitude"], r["longitude"]
        )
        InfoBar.success(
            title="Location Saved",
            content=f"Weather location set to {r['display']}",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self.window(),
        )


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

        self.model_fetcher = None
        self._available_models = []

        self._init_ui()
        self._fetch_models()

    def _init_ui(self):

        # ── Apply & Refresh ───────────────────────────────────────────────────
        # Pinned at the top so it's always visible without scrolling
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

        # Wake word — dropdown restricted to words supported by Porcupine
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

        # Sensitivity slider (0 = strict, 100 = very sensitive)
        self.wake_sensitivity_card = SliderCard(
            FIF.SPEED_HIGH,
            "Wake Word Sensitivity",
            "Higher = activates more easily but risks false triggers (recommended: 40-60)",
            "voice.sensitivity_pct",
            0, 100,
            self.voice_group
        )
        self.voice_group.addSettingCard(self.wake_sensitivity_card)
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

        # Provider selector
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

        # BOM station selector (shown only for BOM provider)
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

        # Custom URL (shown only when "Custom URL" is selected)
        self.weather_custom_url_card = TextInputCard(
            FIF.LINK,
            "Custom Weather URL",
            "Your Open-Meteo-compatible API endpoint (e.g. https://api.open-meteo.com/v1/forecast)",
            "weather.custom_url",
            "https://",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.weather_custom_url_card)
        # Hide unless Custom URL is already selected
        provider_now = settings.get("weather.provider", "BOM (Australia)")
        self.weather_custom_url_card.setVisible(provider_now == "Custom URL")
        self.bom_station_card.setVisible(provider_now == "BOM (Australia)")

        # Temperature unit
        self.weather_unit_card = ComboBoxCard(
            FIF.SPEED_HIGH,
            "Temperature Unit",
            "Display temperature in Celsius or Fahrenheit",
            ["celsius", "fahrenheit"],
            "weather.temperature_unit",
            self.weather_group
        )
        self.weather_group.addSettingCard(self.weather_unit_card)
        self.expandLayout.addWidget(self.weather_group)

        # ── Weather Location ─────────────────────────────────────────────────
        # Added directly to expandLayout — NOT via SettingCardGroup.addSettingCard,
        # which internally clips children to a standard single-row card height.
        # The QFrame-based WeatherLocationCard needs unrestricted vertical space.
        self.location_card = WeatherLocationCard(self.scrollWidget)
        self.expandLayout.addWidget(self.location_card)

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

        # Retention period dropdown
        self.news_retention_card = ComboBoxCard(
            FIF.DATE_TIME,
            "Article Retention Period",
            "Automatically remove locally stored Briefing articles after this period",
            ["1 day", "3 days", "7 days", "14 days", "30 days", "Never"],
            "news.retention",
            self.news_group
        )
        self.news_group.addSettingCard(self.news_retention_card)

        # Auto-purge on startup toggle
        self.auto_purge_card = SwitchCard(
            FIF.SYNC,
            "Auto-purge on Startup",
            "Automatically remove expired articles each time Plia starts",
            "news.auto_purge",
            self.news_group
        )
        self.news_group.addSettingCard(self.auto_purge_card)

        # Manual purge button
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

        # ── Google Calendar ──────────────────────────────────────────────────
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

        # ── Outlook Calendar ─────────────────────────────────────────────────
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

        # 1. Refresh dashboard weather + data feed
        try:
            main_win = self.window()
            if hasattr(main_win, 'dashboard_view') and main_win.dashboard_view:
                main_win.dashboard_view.refresh()
        except Exception as e:
            errors.append(f"Dashboard: {e}")

        # 2. Refresh briefing news feed
        try:
            main_win = self.window()
            if hasattr(main_win, 'briefing_view') and main_win.briefing_view:
                main_win.briefing_view.load_news()
        except Exception as e:
            errors.append(f"Briefing: {e}")

        # 3. Flush in-memory news cache so next fetch uses fresh settings
        try:
            from core.news import news_manager
            news_manager.cache.clear()
        except Exception as e:
            errors.append(f"News cache: {e}")

        # 4. Convert sensitivity percentage to float and save
        try:
            pct = settings.get("voice.sensitivity_pct", 40)
            settings.set("voice.sensitivity", round(pct / 100.0, 2))
        except Exception as e:
            errors.append(f"Sensitivity: {e}")

        # 5. Apply TTS voice change immediately
        try:
            from core.tts import tts
            new_voice = settings.get("tts.voice", "en_GB-northern_english_male-medium")
            if new_voice:
                import threading
                def _change_voice():
                    tts.change_voice(new_voice)
                threading.Thread(target=_change_voice, daemon=True).start()
        except Exception as e:
            errors.append(f"TTS voice: {e}")

        # 6. Restart STT listener with new wake word / sensitivity
        try:
            from core.voice_assistant import voice_assistant
            if voice_assistant.running:
                voice_assistant.stop()
                import threading, time
                def _restart_va():
                    time.sleep(1.5)   # let the old recorder shut down fully
                    if voice_assistant.initialize():
                        voice_assistant.start()
                    else:
                        print("[Settings] Voice assistant failed to restart.")
                threading.Thread(target=_restart_va, daemon=True).start()
        except Exception as e:
            errors.append(f"Voice assistant: {e}")

        if errors:
            InfoBar.warning(
                title="Partially Applied",
                content="Some components could not refresh: " + "; ".join(errors),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window()
            )
        else:
            InfoBar.success(
                title="Settings Applied",
                content="All displays refreshed. Voice assistant restarting with new wake word.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window()
            )

    def _on_weather_provider_changed(self, value: str):
        """Show/hide relevant cards based on selected provider."""
        self.weather_custom_url_card.setVisible(value == "Custom URL")
        self.bom_station_card.setVisible(value == "BOM (Australia)")

    def _on_bom_station_changed(self, label: str):
        """Save the BOM station ID when the user picks a station."""
        from core.weather import BOM_STATIONS
        station_id = BOM_STATIONS.get(label, "94609")
        settings.set("weather.bom_station", station_id)
        settings.set("weather.bom_station_label", label)

    def _on_theme_changed(self, value: str):
        theme_map = {"Dark": Theme.DARK, "Light": Theme.LIGHT, "Auto": Theme.AUTO}
        setTheme(theme_map.get(value, Theme.DARK))

    def _on_delete_settings(self):
        """Delete settings.json so it gets recreated with all current defaults on next restart."""
        import os
        from pathlib import Path
        settings_file = Path.home() / ".plia" / "settings.json"
        try:
            if settings_file.exists():
                settings_file.unlink()
                InfoBar.success(
                    title="Settings File Deleted",
                    content="Please restart Plia — a fresh settings.json will be created with all defaults.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=8000,
                    parent=self.window()
                )
            else:
                InfoBar.warning(
                    title="File Not Found",
                    content=f"Settings file not found at {settings_file}",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=self.window()
                )
        except Exception as e:
            InfoBar.error(
                title="Error",
                content=f"Could not delete settings file: {e}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self.window()
            )

    def _on_reset(self):
        settings.reset_to_defaults()
        InfoBar.success(
            title="Settings Reset",
            content="All settings restored to defaults. Please restart the app.",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.window()
        )

    def _on_purge_now(self):
        """Immediately clear all cached news articles."""
        try:
            from gui.tabs.briefing import save_local_cache
            save_local_cache({})
            InfoBar.success(
                title="Cache Cleared",
                content="All locally stored Briefing articles have been removed.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window()
            )
        except Exception as e:
            InfoBar.error(
                title="Error",
                content=f"Could not clear cache: {e}",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self.window()
            )

    def _fetch_models(self):
        url = settings.get("ollama_url", "http://localhost:11434")
        self.model_fetcher = ModelFetcher(url)
        self.model_fetcher.models_fetched.connect(self._on_models_fetched)
        self.model_fetcher.error_occurred.connect(self._on_models_error)
        self.model_fetcher.start()

    @Slot(list)
    def _on_models_fetched(self, models: list):
        self._available_models = models
        self.chat_model_card.update_models(models)
        self.web_agent_model_card.update_models(models)
        self.desktop_model_card.update_models(models)
        InfoBar.success(
            title="Models Loaded",
            content=f"Found {len(models)} models",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self.window()
        )

    @Slot(str)
    def _on_models_error(self, error: str):
        InfoBar.warning(
            title="Could not fetch models",
            content=error,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self.window()
        )

    # ── Calendar handlers ─────────────────────────────────────────────────────

    def _on_google_connect(self):
        """Launch Google OAuth flow in a background thread."""
        client_id = settings.get("calendar.google.client_id", "").strip()
        client_secret = settings.get("calendar.google.client_secret", "").strip()

        if not client_id or not client_secret:
            InfoBar.warning(
                title="Missing Credentials",
                content="Please enter your Google Client ID and Client Secret first.",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000,
                parent=self.window()
            )
            return

        try:
            from core.calendar_sync import google_auth_flow
            google_auth_flow(client_id, client_secret)
            InfoBar.success(
                title="Google Calendar Connected",
                content="Authorisation complete. Events will appear in the Planner.",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000,
                parent=self.window()
            )
        except Exception as e:
            InfoBar.error(
                title="Google Auth Failed",
                content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=6000,
                parent=self.window()
            )

    def _on_google_disconnect(self):
        """Delete stored Google tokens."""
        try:
            from core.calendar_sync import google_revoke
            google_revoke()
            settings.set("calendar.google.enabled", False)
            self.google_enable_card.switch.setChecked(False)
            InfoBar.success(
                title="Google Calendar Removed",
                content="Stored tokens deleted. Calendar no longer synced.",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000,
                parent=self.window()
            )
        except Exception as e:
            InfoBar.error(
                title="Error", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000,
                parent=self.window()
            )

    def _on_outlook_connect(self):
        """Launch Outlook OAuth flow."""
        client_id = settings.get("calendar.outlook.client_id", "").strip()
        tenant_id = settings.get("calendar.outlook.tenant_id", "common").strip()

        if not client_id:
            InfoBar.warning(
                title="Missing Credentials",
                content="Please enter your Outlook Application (Client) ID first.",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000,
                parent=self.window()
            )
            return

        try:
            from core.calendar_sync import outlook_auth_flow
            outlook_auth_flow(client_id, tenant_id)
            InfoBar.success(
                title="Outlook Calendar Connected",
                content="Authorisation complete. Events will appear in the Planner.",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000,
                parent=self.window()
            )
        except Exception as e:
            InfoBar.error(
                title="Outlook Auth Failed",
                content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=6000,
                parent=self.window()
            )

    def _on_outlook_disconnect(self):
        """Delete stored Outlook tokens."""
        try:
            from core.calendar_sync import outlook_revoke
            outlook_revoke()
            settings.set("calendar.outlook.enabled", False)
            self.outlook_enable_card.switch.setChecked(False)
            InfoBar.success(
                title="Outlook Calendar Removed",
                content="Stored tokens deleted. Calendar no longer synced.",
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=3000,
                parent=self.window()
            )
        except Exception as e:
            InfoBar.error(
                title="Error", content=str(e),
                orient=Qt.Horizontal, isClosable=True,
                position=InfoBarPosition.TOP, duration=4000,
                parent=self.window()
            )
