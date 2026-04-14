"""
gui/tabs/home_automation.py
Environmental Control tab – discovers and controls Kasa, Yeelight, and LIFX devices.

Changes from original:
  - DataFetchThread now discovers ALL brands (Kasa + Yeelight + LIFX) in parallel
  - DeviceCard shows a brand badge and handles all three device types
  - ActionThread routes on/off/brightness/color to the correct library per brand
  - Empty-state panel shown when zero devices are found
  - Kasa credential support read from settings_store (KASA_USERNAME / KASA_PASSWORD)
"""

import asyncio
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QScrollArea, QGridLayout, QPushButton
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor
from qfluentwidgets import (
    TitleLabel, BodyLabel,
    FluentIcon as FIF, IconWidget, SwitchButton, Slider,
    ColorPickerButton, ToolButton
)

from core.kasa_control import kasa_manager

# ── Brand accent colours ──────────────────────────────────────────────────────
BRAND_COLOURS = {
    "kasa":      "#33b5e5",   # Cyan  (app accent)
    "yeelight":  "#f0a500",   # Amber
    "lifx":      "#a855f7",   # Purple
}

BRAND_LABELS = {
    "kasa":      "KASA",
    "yeelight":  "YEELIGHT",
    "lifx":      "LIFX",
}


# ─────────────────────────────────────────────────────────────────────────────
# DISCOVERY THREAD  –  Kasa + Yeelight + LIFX
# ─────────────────────────────────────────────────────────────────────────────

class DataFetchThread(QThread):
    """Background thread that discovers all smart devices on the local network."""
    devices_found = Signal(list)

    def run(self):
        all_devices = []

        # ── 1. Kasa (async) ───────────────────────────────────────────────────
        try:
            print("[HomeAutomation] Discovering Kasa devices …")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Pass credentials if available via settings_store
            try:
                from core.settings_store import settings_store
                kasa_user = settings_store.get("kasa_username", "")
                kasa_pass = settings_store.get("kasa_password", "")
            except Exception:
                kasa_user, kasa_pass = "", ""

            devices_dict = loop.run_until_complete(
                kasa_manager.discover_devices(
                    username=kasa_user or None,
                    password=kasa_pass or None,
                )
            )
            loop.close()

            kasa_devices = list(devices_dict.values()) if isinstance(devices_dict, dict) else devices_dict
            for d in kasa_devices:
                d["brand"] = "kasa"
            all_devices.extend(kasa_devices)
            print(f"[HomeAutomation] Kasa: {len(kasa_devices)} device(s)")
        except Exception as exc:
            print(f"[HomeAutomation] Kasa discovery error: {exc}")

        # ── 2. Yeelight (sync) ────────────────────────────────────────────────
        try:
            print("[HomeAutomation] Discovering Yeelight devices …")
            from yeelight import discover_bulbs, Bulb
            bulbs = discover_bulbs(timeout=3)
            for b in bulbs:
                ip   = b.get("ip", "")
                caps = b.get("capabilities", {})
                # caps keys: id, model, fw_ver, power, bright, color_mode, ct, rgb, hue, sat, name
                power      = caps.get("power", "off")
                bright_raw = caps.get("bright", "100")
                model      = caps.get("model", "yeelight")
                name       = caps.get("name", "") or f"Yeelight {ip}"
                is_color   = caps.get("color_mode", "1") in ("1", 1)
                h          = int(caps.get("hue", 0))
                s          = int(caps.get("sat", 0))
                v          = int(bright_raw) if bright_raw else 100

                all_devices.append({
                    "alias":      name.strip() or f"Yeelight {ip}",
                    "ip":         ip,
                    "mac":        "",
                    "model":      model,
                    "brand":      "yeelight",
                    "is_on":      power == "on",
                    "type":       "Bulb",
                    "brightness": int(bright_raw) if bright_raw else 100,
                    "is_color":   is_color,
                    "hsv":        (h, s, v) if is_color else None,
                    "obj":        None,
                })
            print(f"[HomeAutomation] Yeelight: {len(bulbs)} device(s)")
        except ImportError:
            print("[HomeAutomation] yeelight package not installed – skipping")
        except Exception as exc:
            print(f"[HomeAutomation] Yeelight discovery error: {exc}")

        # ── 3. LIFX (sync) ────────────────────────────────────────────────────
        try:
            print("[HomeAutomation] Discovering LIFX devices …")
            from lifxlan import LifxLAN
            lan     = LifxLAN()
            lights  = lan.get_lights() or []
            for light in lights:
                try:
                    ip     = light.get_ip_addr()
                    mac    = light.get_mac_addr()
                    label  = light.get_label() or f"LIFX {ip}"
                    power  = light.get_power()           # 0 or 65535
                    color  = light.get_color()           # [H, S, B, K]  0-65535 range
                    bright = int(color[2] / 655) if color else 100

                    all_devices.append({
                        "alias":      label,
                        "ip":         ip,
                        "mac":        mac,
                        "model":      "LIFX",
                        "brand":      "lifx",
                        "is_on":      power == 65535,
                        "type":       "Bulb",
                        "brightness": bright,
                        "is_color":   True,
                        "hsv":        (
                            int(color[0] / 182),     # H → 0-360
                            int(color[1] / 655),     # S → 0-100
                            bright,                  # V → 0-100
                        ) if color else None,
                        "obj":        light,
                    })
                except Exception as device_exc:
                    print(f"[HomeAutomation] LIFX device error: {device_exc}")
            print(f"[HomeAutomation] LIFX: {len(lights)} device(s)")
        except ImportError:
            print("[HomeAutomation] lifxlan package not installed – skipping")
        except Exception as exc:
            print(f"[HomeAutomation] LIFX discovery error: {exc}")

        print(f"[HomeAutomation] Total devices found: {len(all_devices)}")
        self.devices_found.emit(all_devices)


# ─────────────────────────────────────────────────────────────────────────────
# ACTION THREAD  –  routes on/off/brightness/color to the right library
# ─────────────────────────────────────────────────────────────────────────────

class ActionThread(QThread):
    """Executes a device action (on/off/brightness/color) in a background thread."""
    finished = Signal(bool)

    def __init__(self, action: str, device_info: dict, *args):
        super().__init__()
        self.action      = action
        self.device_info = device_info
        self.args        = args

    def run(self):
        brand  = self.device_info.get("brand", "kasa")
        ip     = self.device_info.get("ip", "")
        mac    = self.device_info.get("mac", "")
        success = False

        try:
            if brand == "kasa":
                success = self._kasa_action(ip)

            elif brand == "yeelight":
                success = self._yeelight_action(ip)

            elif brand == "lifx":
                success = self._lifx_action(ip, mac)

        except Exception as exc:
            print(f"[HomeAutomation] Action '{self.action}' on {brand}@{ip} error: {exc}")

        self.finished.emit(success)

    # ── Kasa ─────────────────────────────────────────────────────────────────

    def _kasa_action(self, ip: str) -> bool:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = False
        try:
            if self.action == "on":
                result = loop.run_until_complete(kasa_manager.turn_on(ip, dev=None))
            elif self.action == "off":
                result = loop.run_until_complete(kasa_manager.turn_off(ip, dev=None))
            elif self.action == "brightness" and self.args:
                result = loop.run_until_complete(
                    kasa_manager.set_brightness(ip, self.args[0], dev=None)
                )
            elif self.action == "color" and len(self.args) >= 3:
                result = loop.run_until_complete(
                    kasa_manager.set_hsv(ip, self.args[0], self.args[1], self.args[2], dev=None)
                )
        finally:
            loop.close()
        return result

    # ── Yeelight ─────────────────────────────────────────────────────────────

    def _yeelight_action(self, ip: str) -> bool:
        from yeelight import Bulb
        bulb = Bulb(ip)
        if self.action == "on":
            bulb.turn_on()
            return True
        elif self.action == "off":
            bulb.turn_off()
            return True
        elif self.action == "brightness" and self.args:
            # yeelight brightness: 1–100
            level = max(1, min(100, self.args[0]))
            bulb.set_brightness(level)
            return True
        elif self.action == "color" and len(self.args) >= 3:
            h, s, v = self.args[0], self.args[1], self.args[2]
            # Convert HSV to RGB for yeelight
            import colorsys
            r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
            bulb.set_rgb(int(r * 255), int(g * 255), int(b * 255))
            return True
        return False

    # ── LIFX ─────────────────────────────────────────────────────────────────

    def _lifx_action(self, ip: str, mac: str) -> bool:
        from lifxlan import Light
        light = Light(mac, ip)
        if self.action == "on":
            light.set_power("on")
            return True
        elif self.action == "off":
            light.set_power("off")
            return True
        elif self.action == "brightness" and self.args:
            # LIFX brightness: 0–65535
            level = int(max(0, min(100, self.args[0])) * 655)
            cur   = light.get_color()   # [H, S, B, K]
            light.set_color([cur[0], cur[1], level, cur[3]])
            return True
        elif self.action == "color" and len(self.args) >= 3:
            h, s, v = self.args[0], self.args[1], self.args[2]
            light.set_color([
                int(h * 182),    # 0-65535
                int(s * 655),    # 0-65535
                int(v * 655),    # 0-65535
                3500,            # colour temperature (K)
            ])
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DEVICE CARD
# ─────────────────────────────────────────────────────────────────────────────

class DeviceCard(QFrame):
    """Visual card for a single smart device."""

    def __init__(self, device_info: dict, parent=None):
        super().__init__(parent)
        self.device_info = device_info
        self.brand       = device_info.get("brand", "kasa")
        self.ip          = device_info.get("ip", "")
        self.is_bulb     = (
            "Bulb" in device_info.get("type", "")
            or device_info.get("brightness") is not None
        )
        accent = BRAND_COLOURS.get(self.brand, "#33b5e5")

        self.setFixedSize(300, 170)
        self.setStyleSheet(f"""
            DeviceCard {{
                background-color: #1a2236;
                border: 1px solid {accent}40;
                border-radius: 20px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        # ── Header: icon  +  brand badge  +  toggle ──────────────────────────
        header = QHBoxLayout()

        icon_box = QFrame()
        icon_box.setFixedSize(40, 40)
        icon_box.setStyleSheet(f"background-color: {accent}22; border-radius: 12px;")
        ib_lay = QVBoxLayout(icon_box)
        ib_lay.setAlignment(Qt.AlignCenter)
        ib_lay.setContentsMargins(0, 0, 0, 0)
        icon = FIF.BRIGHTNESS if self.is_bulb else FIF.TILES
        iw = IconWidget(icon)
        iw.setFixedSize(20, 20)
        ib_lay.addWidget(iw)
        header.addWidget(icon_box)

        # Brand badge
        badge = QLabel(BRAND_LABELS.get(self.brand, self.brand.upper()))
        badge.setStyleSheet(f"""
            color: {accent};
            font-size: 9px;
            font-weight: bold;
            background-color: {accent}18;
            border: 1px solid {accent}40;
            border-radius: 6px;
            padding: 2px 6px;
        """)
        header.addWidget(badge)
        header.addStretch()

        self.toggle = SwitchButton()
        self.toggle.setChecked(device_info.get("is_on", False))
        self.toggle.checkedChanged.connect(self._on_toggle)
        header.addWidget(self.toggle)

        layout.addLayout(header)

        # ── Device name ───────────────────────────────────────────────────────
        name_label = QLabel(device_info.get("alias", "Unknown Device"))
        name_label.setStyleSheet(
            "color: #e8eaed; font-weight: bold; font-size: 15px; background: transparent;"
        )
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        # ── Status  +  model ─────────────────────────────────────────────────
        status_row = QHBoxLayout()
        status = QLabel("● ONLINE")
        status.setStyleSheet("color: #2ecc71; font-size: 10px; font-weight: bold; background: transparent;")
        model_lbl = QLabel(device_info.get("model", ""))
        model_lbl.setStyleSheet("color: #4a5568; font-size: 10px; background: transparent;")
        status_row.addWidget(status)
        status_row.addStretch()
        status_row.addWidget(model_lbl)
        layout.addLayout(status_row)

        # ── Controls: brightness slider + color picker ────────────────────────
        if self.is_bulb:
            ctrl_layout = QHBoxLayout()
            ctrl_layout.setContentsMargins(0, 4, 0, 0)

            self.slider = Slider(Qt.Horizontal)
            self.slider.setRange(1, 100)
            val = device_info.get("brightness") or 100
            self.slider.setValue(int(val))
            self.slider.sliderReleased.connect(self._on_brightness_change)
            ctrl_layout.addWidget(self.slider)

            if device_info.get("is_color"):
                self.color_btn = ColorPickerButton(QColor("#ffffff"), "Color")
                self.color_btn.setFixedSize(30, 24)
                self.color_btn.colorChanged.connect(self._on_color_changed)
                ctrl_layout.addWidget(self.color_btn)

            layout.addLayout(ctrl_layout)
        else:
            layout.addStretch()

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _on_toggle(self, checked: bool):
        action = "on" if checked else "off"
        self._run_action(action)

    def _on_brightness_change(self):
        self._run_action("brightness", self.slider.value())

    def _on_color_changed(self, color: QColor):
        h = color.hsvHue()
        s = int(color.hsvSaturationF() * 100)
        v = int(color.valueF() * 100)
        self._run_action("color", h, s, v)

    def _run_action(self, action: str, *args):
        self._worker = ActionThread(action, self.device_info, *args)
        self._worker.finished.connect(
            lambda ok: print(
                f"[HomeAutomation] {action} on {self.brand}@{self.ip}: {'OK' if ok else 'FAILED'}"
            )
        )
        self._worker.start()


# ─────────────────────────────────────────────────────────────────────────────
# EMPTY STATE
# ─────────────────────────────────────────────────────────────────────────────

class EmptyStateWidget(QWidget):
    """Shown when no devices are found."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)

        icon = IconWidget(FIF.WIFI)
        icon.setFixedSize(48, 48)
        lay.addWidget(icon, alignment=Qt.AlignCenter)

        title = QLabel("No Devices Found")
        title.setStyleSheet("color: #e8eaed; font-size: 18px; font-weight: bold; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        hint = QLabel(
            "Make sure your Kasa, Yeelight, or LIFX devices\n"
            "are powered on and connected to the same Wi-Fi network.\n\n"
            "For newer Kasa devices add your TP-Link credentials in Settings."
        )
        hint.setStyleSheet("color: #4a5568; font-size: 13px; background: transparent;")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TAB WIDGET
# ─────────────────────────────────────────────────────────────────────────────

class HomeAutomationTab(QWidget):
    """Environmental Control Dashboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeAutomationView")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(24)

        self._setup_header(main_layout)
        self._setup_filters(main_layout)

        # Scroll area containing the device grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")

        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(20)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.scroll.setWidget(self.grid_widget)
        main_layout.addWidget(self.scroll)

        # Use cached Kasa devices while multi-brand discovery runs
        if kasa_manager.devices:
            cached = []
            for d in kasa_manager.devices.values():
                d.setdefault("brand", "kasa")
                cached.append(d)
            print("[HomeAutomation] Using cached Kasa devices; background refresh running")
            self._on_devices_loaded(cached)

        # Always kick off a fresh full discovery
        self._load_devices()

    # ── Header ────────────────────────────────────────────────────────────────

    def _setup_header(self, parent_layout):
        header = QHBoxLayout()

        text_layout = QVBoxLayout()
        title = TitleLabel("Environmental Control", self)
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #e8eaed;")
        sub = BodyLabel("Localized automation interface.", self)
        sub.setStyleSheet("color: #6e7a8e; font-size: 14px;")
        text_layout.addWidget(title)
        text_layout.addWidget(sub)
        header.addLayout(text_layout)
        header.addStretch()

        refresh_btn = ToolButton(FIF.SYNC, self)
        refresh_btn.setToolTip("Refresh Devices")
        refresh_btn.clicked.connect(self._load_devices)
        header.addWidget(refresh_btn)
        header.addSpacing(10)

        ha_bubble = QLabel("⬤  Home Assistant Coming Soon!")
        ha_bubble.setStyleSheet("""
            background-color: #0d121d;
            color: #33b5e5;
            border: 1px solid #1a2236;
            border-radius: 18px;
            padding: 8px 20px;
            font-weight: bold;
            font-size: 12px;
        """)
        header.addWidget(ha_bubble)

        parent_layout.addLayout(header)

    # ── Brand / Room filter bar ───────────────────────────────────────────────

    def _setup_filters(self, parent_layout):
        self.filter_layout = QHBoxLayout()
        self.filter_layout.setSpacing(10)
        self.filter_layout.addStretch()
        parent_layout.addLayout(self.filter_layout)

    def _update_filters(self):
        # Remove all except the trailing stretch
        while self.filter_layout.count() > 1:
            child = self.filter_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # Build filter list: All + brands present + rooms
        brands_present = sorted({d.get("brand", "kasa") for d in self.all_devices})
        brand_filters  = [BRAND_LABELS.get(b, b.upper()) for b in brands_present]
        rooms          = sorted(self.room_groups.keys())
        filters        = ["All"] + brand_filters + rooms

        for i, label in enumerate(filters):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, lbl=label: self._filter_grid(lbl))
            if i == 0:
                btn.setChecked(True)
                self.current_filter = label
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1a2236;
                    color: #6e7a8e;
                    border-radius: 15px;
                    padding: 6px 16px;
                    border: none;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:checked {
                    background-color: #33b5e5;
                    color: #0f1524;
                }
                QPushButton:hover {
                    background-color: #232d45;
                }
            """)
            self.filter_layout.insertWidget(i, btn)

    def _filter_grid(self, filter_name: str):
        # Update button check states
        for i in range(self.filter_layout.count() - 1):
            item = self.filter_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QPushButton):
                item.widget().setChecked(item.widget().text() == filter_name)

        # Clear grid
        for i in reversed(range(self.grid_layout.count())):
            w = self.grid_layout.itemAt(i).widget()
            if w:
                w.setParent(None)

        # Determine device list
        if filter_name == "All":
            devices = self.all_devices
        elif filter_name in BRAND_LABELS.values():
            # filter by brand
            brand_key = next(
                (k for k, v in BRAND_LABELS.items() if v == filter_name), None
            )
            devices = [d for d in self.all_devices if d.get("brand") == brand_key]
        else:
            devices = self.room_groups.get(filter_name, [])

        if not devices:
            self.grid_layout.addWidget(EmptyStateWidget(), 0, 0)
            return

        row, col = 0, 0
        max_cols = 3
        for dev in devices:
            card = DeviceCard(dev)
            self.grid_layout.addWidget(card, row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    # ── Device loading ────────────────────────────────────────────────────────

    def _load_devices(self):
        if hasattr(self, "loader") and self.loader and self.loader.isRunning():
            print("[HomeAutomation] Discovery already in progress, skipping")
            return
        self.loader = DataFetchThread()
        self.loader.devices_found.connect(self._on_devices_loaded)
        self.loader.finished.connect(self.loader.deleteLater)
        self.loader.start()

    def _on_devices_loaded(self, devices: list):
        self.all_devices  = devices
        self.room_groups  = {}

        keywords = {
            "Office":      ["office", "desk", "work", "pc", "monitor"],
            "Living Room": ["living", "sofa", "tv", "lounge"],
            "Kitchen":     ["kitchen", "dining", "cook", "oven", "fridge"],
            "Bedroom":     ["bed", "sleep", "night"],
            "Exterior":    ["exterior", "garden", "patio", "porch", "garage"],
            "Hallway":     ["hall", "corridor", "stairs"],
        }

        for dev in devices:
            alias    = dev.get("alias", "").lower()
            assigned = False
            for room, keys in keywords.items():
                if any(k in alias for k in keys):
                    self.room_groups.setdefault(room, []).append(dev)
                    assigned = True
                    break
            if not assigned:
                self.room_groups.setdefault("Other", []).append(dev)

        self._update_filters()
        self._filter_grid("All")
