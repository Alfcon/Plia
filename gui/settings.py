"""
Comprehensive Settings Tab with model selection, connection settings, and preferences.
"""

from config import LOCAL_ROUTER_PATH, RESPONDER_MODEL

import requests
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QBrush

from qfluentwidgets import (
    ScrollArea, ExpandLayout, SettingCardGroup, PushSettingCard, FluentIcon as FIF,
    setTheme, Theme, PrimaryPushSettingCard, ComboBox, LineEdit,
    PrimaryPushButton, InfoBar, InfoBarPosition, SettingCard, Slider,
    StrongBodyLabel, SwitchButton
)

from core.settings_store import settings


# ---------------------------------------------------------------------------
# Background thread — plain model name list (kept for compatibility)
# ---------------------------------------------------------------------------

class ModelFetcher(QThread):
    """Background thread to fetch available Ollama models (names only)."""
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


# ---------------------------------------------------------------------------
# Background thread — rich model dicts (cross-referenced with lmfit database)
# ---------------------------------------------------------------------------

class RichModelFetcher(QThread):
    """Fetches installed Ollama models and cross-references with the llmfit
    database to produce enriched model dicts matching the Model Browser columns:
    Provider, Params, Use Case, Fit, Quant, File Size, VRAM, Speed.

    Falls back to Ollama API data only for models not found in llmfit.
    """

    models_ready   = Signal(list)   # list[dict] — rich model dicts
    error_occurred = Signal(str)

    def __init__(self, ollama_url: str):
        super().__init__()
        self.ollama_url = ollama_url

    def run(self):
        try:
            # ── Import shared helpers from the Model Browser ──────────────
            from gui.model_browser import (
                HardwareInfo, _load_raw_db, score_model,
                _hf_to_ollama, _parse_params_b,
            )

            # 1. Detect local hardware (RAM, VRAM, GPU) for scoring
            hw = HardwareInfo().detect()

            # 2. Load llmfit database (7-day cache → GitHub → built-in fallback)
            raw_db, _ = _load_raw_db()

            # Build lookup: ollama_name (no tag) -> scored model dict
            db_lookup: dict = {}
            for raw in raw_db:
                scored = score_model(raw, hw)
                if not scored:
                    continue
                key  = _hf_to_ollama(raw["name"])          # e.g. "qwen2.5-3b-instruct"
                base = key.split(":")[0]                    # strip any tag
                # Store under both the full key and the base name
                for k in (key, base):
                    if k not in db_lookup:
                        db_lookup[k] = scored

            # 3. Fetch installed Ollama models via REST API
            try:
                r = requests.get(f"{self.ollama_url}/api/tags", timeout=10)
                if r.status_code != 200:
                    self.error_occurred.emit(f"HTTP {r.status_code}")
                    return
                ollama_models = r.json().get("models", [])
            except requests.exceptions.ConnectionError:
                self.error_occurred.emit("Cannot connect to Ollama")
                return
            except Exception as e:
                self.error_occurred.emit(str(e))
                return

            # 4. Enrich each installed model
            rich: list = []
            for om in ollama_models:
                name    = om["name"]                                        # e.g. "qwen2.5vl:3b"
                details = om.get("details", {})
                size_gb = round(om.get("size", 0) / (1024 ** 3), 1)
                p_str   = details.get("parameter_size",    "—")            # e.g. "3.1B"
                q_str   = details.get("quantization_level","—")            # e.g. "Q8_0"
                base    = name.split(":")[0]                               # e.g. "qwen2.5vl"

                # Try multiple key variations for a match in the lmfit lookup
                db = (
                    db_lookup.get(name)
                    or db_lookup.get(base)
                    or db_lookup.get(base.replace(".", "-"))
                    or db_lookup.get(base.replace("-", ""))
                )

                if db:
                    rich.append({
                        "ollama_name":  name,
                        "display_name": name,
                        "provider":     db.get("provider",           "—"),
                        "params":       db.get("parameter_count",    p_str),
                        "use_case":     db.get("use_case",           "—"),
                        "fit_label":    db.get("fit_label",          "—"),
                        "fit_level":    db.get("fit_level",          ""),
                        "quant":        db.get("best_quant",         q_str),
                        "file_size_gb": db.get("file_size_gb",       size_gb),
                        "vram_gb":      db.get("memory_required_gb", 0.0),
                        "tps":          db.get("estimated_tps",      0.0),
                    })
                else:
                    # No lmfit entry — use Ollama API data; estimate VRAM from file size
                    vram_est = round(size_gb * 1.1, 1) if size_gb else 0.0
                    rich.append({
                        "ollama_name":  name,
                        "display_name": name,
                        "provider":     "—",
                        "params":       p_str,
                        "use_case":     "—",
                        "fit_label":    "—",
                        "fit_level":    "",
                        "quant":        q_str,
                        "file_size_gb": size_gb,
                        "vram_gb":      vram_est,
                        "tps":          0.0,
                    })

            self.models_ready.emit(rich)

        except Exception as e:
            self.error_occurred.emit(f"RichModelFetcher: {e}")


class ConnectionTester(QThread):
    """Background thread to test Ollama connection."""
    success = Signal()
    failed  = Signal(str)

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


# ---------------------------------------------------------------------------
# Simple combo-box card (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Legacy plain-ComboBox model card (kept but no longer used for AI Models)
# ---------------------------------------------------------------------------

class ModelSelectCard(SettingCard):
    """Simple setting card with a ComboBox for model selection (names only)."""

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


# ---------------------------------------------------------------------------
# Rich model selector — 4 visible rows, same columns as the Model Browser
# ---------------------------------------------------------------------------

class RichModelSelectCard(QFrame):
    """Replaces ModelSelectCard for the AI Models section.

    Displays installed Ollama models in a scrollable QTableWidget showing
    exactly four rows at a time.  Columns match the Model Browser exactly:
    Model · Provider · Params · Use Case · Fit · Quant · File Size · VRAM · Speed

    Data comes from RichModelFetcher which cross-references Ollama's /api/tags
    with the llmfit database.  Models not found in llmfit show "—" for the
    computed columns (Fit / Speed) but still show Params, Quant, and File Size
    from the Ollama REST API.
    """

    model_changed = Signal(str)

    # ── Layout constants ────────────────────────────────────────────────────
    ROW_H        = 36
    VISIBLE_ROWS = 4

    # (header label, column pixel width)  — last column stretches to fill
    COLUMNS = [
        ("Model",     168),
        ("Provider",   82),
        ("Params",     58),
        ("Use Case",   76),
        ("Fit",        80),
        ("Quant",      62),
        ("File Size",  72),
        ("VRAM",       62),
        ("Speed",      62),
    ]

    FIT_COLOURS = {
        "perfect":   "#4caf50",
        "good":      "#8bc34a",
        "marginal":  "#ffb300",
        "too_tight": "#555e70",
    }

    def __init__(self, icon, title: str, description: str,
                 key_path: str, parent=None):
        super().__init__(parent)
        self.key_path = key_path
        self._models: list = []

        # ── Frame styling — matches qfluentwidgets dark card appearance ─────
        self.setObjectName("richModelCard")
        self.setStyleSheet("""
            QFrame#richModelCard {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Header row (icon · title · description · current-selection) ─────
        hdr = QHBoxLayout()
        hdr.setSpacing(12)

        from qfluentwidgets import IconWidget
        ico = IconWidget(icon, self)
        ico.setFixedSize(20, 20)
        hdr.addWidget(ico)

        txt_col = QVBoxLayout()
        txt_col.setSpacing(1)
        title_lbl = StrongBodyLabel(title, self)
        desc_lbl  = QLabel(description, self)
        desc_lbl.setStyleSheet("color: rgba(255,255,255,0.45); font-size: 11px;")
        txt_col.addWidget(title_lbl)
        txt_col.addWidget(desc_lbl)
        hdr.addLayout(txt_col)
        hdr.addStretch()

        self._sel_lbl = QLabel("", self)
        self._sel_lbl.setStyleSheet(
            "color: #33b5e5; font-size: 11px; font-weight: 600;"
        )
        hdr.addWidget(self._sel_lbl)
        root.addLayout(hdr)

        # ── Model table ──────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(self.COLUMNS), self)
        self._table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self._table.horizontalHeader().setFixedHeight(24)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._table.horizontalHeader().setStretchLastSection(True)

        for col, (_, width) in enumerate(self.COLUMNS):
            self._table.setColumnWidth(col, width)

        # Fix height to show exactly VISIBLE_ROWS rows plus the header
        table_h = 24 + self.VISIBLE_ROWS * self.ROW_H + 4
        self._table.setFixedHeight(table_h)

        self._table.setStyleSheet("""
            QTableWidget {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 4px;
                color: #e8eaed;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 4px 6px;
                border-bottom: 1px solid rgba(0, 0, 0, 0.25);
            }
            QTableWidget::item:selected {
                background: #1a2a50;
                color: #e8eaed;
            }
            QHeaderView::section {
                background: rgba(0, 0, 0, 0.20);
                color: #8b9bb4;
                font-size: 10px;
                font-weight: 600;
                border: none;
                border-right: 1px solid rgba(255, 255, 255, 0.06);
                padding: 3px 6px;
            }
            QScrollBar:vertical {
                width: 6px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 3px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table)

        # Restore persisted model name in the label
        cur = settings.get(self.key_path, "")
        self._sel_lbl.setText(cur if cur else "—")

    # ── Public API ────────────────────────────────────────────────────────────

    def update_models(self, rich_models: list):
        """Populate the table.  Called by SettingsTab._on_models_fetched."""
        self._models = rich_models
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rich_models))

        RA = Qt.AlignRight | Qt.AlignVCenter
        LA = Qt.AlignLeft  | Qt.AlignVCenter
        current = settings.get(self.key_path, "")
        restore_row = -1

        def mk(txt, align=LA, colour=None):
            it = QTableWidgetItem(str(txt))
            it.setTextAlignment(align)
            if colour:
                it.setForeground(QBrush(QColor(colour)))
            return it

        for row, m in enumerate(rich_models):
            ol_name  = m["ollama_name"]
            fc       = self.FIT_COLOURS.get(m.get("fit_level", ""), "#8b9bb4")
            fsz      = m.get("file_size_gb", 0.0)
            vram     = m.get("vram_gb",      0.0)
            tps      = m.get("tps",          0.0)
            fl       = m.get("fit_label",    "—")
            fit_txt  = f"● {fl}" if fl != "—" else "—"

            cells = [
                mk(m["display_name"]),
                mk(m.get("provider",  "—"),  colour="#8b9bb4"),
                mk(m.get("params",    "—"), RA),
                mk(m.get("use_case",  "—"),  colour="#8b9bb4"),
                mk(fit_txt,                  colour=fc),
                mk(m.get("quant",     "—"),  colour="#33b5e5"),
                mk(f"{fsz:.1f} GB"   if fsz  else "—", RA),
                mk(f"{vram:.1f} GB"  if vram else "—", RA),
                mk(f"{tps:.0f} t/s"  if tps  else "—", RA),
            ]

            for col, it in enumerate(cells):
                it.setData(Qt.UserRole, ol_name)   # store name on every cell
                self._table.setItem(row, col, it)
            self._table.setRowHeight(row, self.ROW_H)

            if ol_name == current:
                restore_row = row

        self._table.setSortingEnabled(True)

        if restore_row >= 0:
            self._table.selectRow(restore_row)

    # ── Private ───────────────────────────────────────────────────────────────

    def _on_selection_changed(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        name = rows[0].data(Qt.UserRole)
        if name:
            settings.set(self.key_path, name)
            self._sel_lbl.setText(name)
            self.model_changed.emit(name)


# ---------------------------------------------------------------------------
# URL input card (unchanged)
# ---------------------------------------------------------------------------

class UrlInputCard(SettingCard):
    """Setting card with URL input and test button."""

    def __init__(self, icon, title, description, key_path: str, parent=None):
        super().__init__(icon, title, description, parent)
        self.key_path = key_path
        self.tester   = None

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


# ---------------------------------------------------------------------------
# Slider card (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Switch card (unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Text input card (unchanged)
# ---------------------------------------------------------------------------

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
        self.scrollWidget  = QWidget()
        self.expandLayout  = ExpandLayout(self.scrollWidget)

        self.setStyleSheet("background-color: transparent;")
        self.scrollWidget.setObjectName("scrollWidget")

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)

        self.model_fetcher     = None
        self._available_models = []   # list of rich model dicts after fetch

        self._init_ui()
        self._fetch_models()          # kick off background fetch on startup

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
        # Each card is a RichModelSelectCard: a 4-row scrollable table with
        # columns matching the Model Browser (Provider, Params, Use Case, Fit,
        # Quant, File Size, VRAM, Speed).  Data loads via RichModelFetcher.
        self.ai_group = SettingCardGroup("AI Models", self.scrollWidget)

        self.chat_model_card = RichModelSelectCard(
            FIF.CHAT,
            "Chat Model",
            "Ollama model for general chat responses",
            "models.chat",
            self.ai_group
        )
        self.ai_group.addSettingCard(self.chat_model_card)

        self.web_agent_model_card = RichModelSelectCard(
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
        self.desktop_group = SettingCardGroup(
            "Desktop Agent (AI Computer Control)", self.scrollWidget
        )

        self.desktop_info_card = SettingCard(
            FIF.ROBOT,
            "How it works",
            "Takes screenshots of your screen and uses Qwen VL to control the mouse and "
            "keyboard. No API keys or bot tokens required. Just say 'Open Discord and "
            "summarise #general' — the agent opens it and reads it visually.",
            self.desktop_group
        )
        self.desktop_group.addSettingCard(self.desktop_info_card)

        self.desktop_model_card = RichModelSelectCard(
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
            if hasattr(main_win, 'dashboard_view') and main_win.dashboard_view:
                main_win.dashboard_view.refresh()
        except Exception as e:
            errors.append(f"Dashboard: {e}")

        try:
            main_win = self.window()
            if hasattr(main_win, 'briefing_view') and main_win.briefing_view:
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
                def _change_voice():
                    tts.change_voice(new_voice)
                threading.Thread(target=_change_voice, daemon=True).start()
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

    # ── Model fetching ────────────────────────────────────────────────────────

    def _fetch_models(self):
        """Start RichModelFetcher in a background thread.
        On success it calls _on_models_fetched with a list of rich model dicts.
        """
        url = settings.get("ollama_url", "http://localhost:11434")
        self.model_fetcher = RichModelFetcher(url)
        self.model_fetcher.models_ready.connect(self._on_models_fetched)
        self.model_fetcher.error_occurred.connect(self._on_models_error)
        self.model_fetcher.start()

    @Slot(list)
    def _on_models_fetched(self, rich_models: list):
        """Populate all three RichModelSelectCards with the enriched model list."""
        self._available_models = rich_models
        self.chat_model_card.update_models(rich_models)
        self.web_agent_model_card.update_models(rich_models)
        self.desktop_model_card.update_models(rich_models)
        InfoBar.success(
            title="Models Loaded",
            content=f"Found {len(rich_models)} installed models",
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
        client_id     = settings.get("calendar.google.client_id",     "").strip()
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
