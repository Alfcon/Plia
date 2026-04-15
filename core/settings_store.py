"""
Centralized settings storage with persistence.

Saves to ~/.plia/settings.json  (modular PySide6 app settings).
Also exposes PLIA_DIR / PIPER_MODEL_DIR path constants used by
tts.py and the standalone plia2.py launcher.

Qt signals (setting_changed) are intact so all gui/ consumers work
without modification.
"""

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal

# ── Shared path constants (used by tts.py and plia2.py) ─────────────────
PLIA_DIR        = Path.home() / ".plia_ai"
PIPER_MODEL_DIR = PLIA_DIR / "tts_models"
PLIA_DIR.mkdir(parents=True, exist_ok=True)
PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ── Defaults ──────────────────────────────────────────────────────────────
DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "Dark",
    "ollama_url": "http://localhost:11434",
    "models": {
        "chat": "qwen3:1.7b",
        # qwen2.5vl:7b is the correct vision model tag in Ollama.
        # Install: ollama pull qwen2.5vl:7b  (or qwen2.5vl:3b for lower VRAM)
        "web_agent": "qwen2.5vl:7b",
    },
    "web_agent_params": {
        "temperature": 1.0,
        "top_k": 20,
        "top_p": 0.95,
    },
    # ── TTS settings (aligns with VoiceEngine / plia2.py) ───────────────
    "tts": {
        "voice":        "en_US-lessac-medium",   # default Python-library voice
        "length_scale": 1.0,    # 0.5 = fast, 1.0 = normal, 2.0 = slow
        "volume":       0.9,    # 0.0 – 1.0
        "muted":        False,
    },
    # ── Voice/STT settings ───────────────────────────────────────────────
    "voice": {
        "wake_word":              "jarvis",   # must be in SUPPORTED_WAKE_WORDS
        "sensitivity":            0.4,        # 0.0 – 1.0
        "enabled":                True,
        "auto_start":             True,       # activate voice listening on app startup
        "startup_greeting":       True,       # speak a greeting when voice goes active
        "stt_energy_threshold":   300,        # for SpeechEngine fallback (50-1000)
    },
    # ── General ──────────────────────────────────────────────────────────
    "general": {
        "max_history":      20,
        "auto_fetch_news":  True,
    },
    # ── Weather ──────────────────────────────────────────────────────────
    "weather": {
        "latitude":         -32.1151,
        "longitude":        116.0255,
        "city":             "Kelmscott, WA",
        "provider":         "BOM (Australia)",
        "bom_station":      "94609",
        "temperature_unit": "celsius",
        "custom_url":       "",
    },
    # ── Desktop agent ────────────────────────────────────────────────────
    "desktop_agent": {
        "model":     "",   # leave empty to use models.web_agent
        "max_steps": 25,
    },
    # ── UI (standalone plia2.py launcher) ────────────────────────────────
    "ui": {
        "opacity":       0.98,
        "accent_name":   "Arc Blue",
        "accent_color":  "#00b4d8",
    },
}


# ══════════════════════════════════════════════════════════════════════════
#  SettingsStore
# ══════════════════════════════════════════════════════════════════════════
class SettingsStore(QObject):
    """Thread-safe settings manager with Qt signals for reactive updates."""

    # Emitted when any setting changes: (dot-path, new_value)
    setting_changed = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._lock          = threading.RLock()
        self._settings: Dict[str, Any] = {}
        self._settings_dir  = Path.home() / ".plia"
        self._settings_file = self._settings_dir / "settings.json"
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self):
        """Load settings from disk; missing keys are filled from defaults."""
        with self._lock:
            if self._settings_file.exists():
                try:
                    with open(self._settings_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    self._settings = self._deep_merge(DEFAULT_SETTINGS.copy(), loaded)
                    self._save()
                except (json.JSONDecodeError, IOError) as exc:
                    print(f"[Settings] Error loading settings: {exc}. Using defaults.")
                    self._settings = DEFAULT_SETTINGS.copy()
                    self._save()
            else:
                self._settings = DEFAULT_SETTINGS.copy()
                self._save()

    def _save(self):
        """Persist settings to ~/.plia/settings.json."""
        with self._lock:
            try:
                self._settings_dir.mkdir(parents=True, exist_ok=True)
                with open(self._settings_file, "w", encoding="utf-8") as f:
                    json.dump(self._settings, f, indent=2)
            except IOError as exc:
                print(f"[Settings] Error saving settings: {exc}")

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """
        Recursively merge *override* into *base*.
        Keys in base that are absent from override are kept (new defaults).
        Keys in override that exist in base are overwritten (user wins).
        """
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # ── Public API ────────────────────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a setting by dot-notation path.
        Examples:
            get("models.chat")          → "qwen3:1.7b"
            get("tts.volume")           → 0.9
            get("voice.wake_word")      → "jarvis"
            get("ui.accent_color")      → "#00b4d8"
        """
        with self._lock:
            keys  = key_path.split(".")
            value = self._settings
            try:
                for k in keys:
                    value = value[k]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, key_path: str, value: Any):
        """
        Set a setting by dot-notation path and persist.
        Example: set("tts.volume", 0.75)
        Emits setting_changed(key_path, value) after saving.
        """
        with self._lock:
            keys   = key_path.split(".")
            target = self._settings
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
            self._save()
        self.setting_changed.emit(key_path, value)

    def get_all(self) -> Dict[str, Any]:
        """Return a shallow copy of the entire settings dict."""
        with self._lock:
            return self._settings.copy()

    def reset_to_defaults(self):
        """Reset all settings to built-in defaults."""
        with self._lock:
            self._settings = DEFAULT_SETTINGS.copy()
            self._save()
        self.setting_changed.emit("*", None)


# ── Module-level singleton ────────────────────────────────────────────────
settings_store = SettingsStore()

# Convenience alias used by gui/ modules
settings = settings_store
