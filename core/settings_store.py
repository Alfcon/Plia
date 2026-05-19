"""
Centralized settings storage with persistence.

Saves to ~/.plia/settings.json  (modular PySide6 app settings).
Also exposes PLIA_DIR / PIPER_MODEL_DIR path constants used by
tts.py and the standalone plia2.py launcher.

A Qt signal ``setting_changed(key_path, value)`` is emitted on every
``set()`` call. No GUI consumer currently subscribes to it (cards bind
their own keys at construction and persist on edit), but the signal is
available for any future component that needs to react to settings
changes from elsewhere in the app.
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
        # qwen3:8b is the recommended chat model for 8GB+ VRAM systems —
        # solid tool-calling and reasoning for live agents. For lower-spec
        # hardware fall back to "qwen3:1.7b" (poor tool use, fast).
        "chat": "qwen3:8b",
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
        # Multi-select wake-word models. Each entry:
        #   id:          stable identifier (filename stem of the .onnx)
        #   display:     human label shown in Settings
        #   path:        relative to models/wake/  (e.g. "bundled/plia.onnx")
        #   enabled:     bool — whether this model is loaded by WakeDetector
        #   sensitivity: 0.0–1.0 — openwakeword score threshold
        #   builtin:     True for ships-with-Plia models; False for user uploads
        "wake_models": [
            {"id": "hey_jarvis",  "display": "Hey Jarvis",  "path": "bundled/hey_jarvis.onnx",
             "enabled": True,  "sensitivity": 0.5, "builtin": True},
            {"id": "plia",        "display": "Plia",        "path": "bundled/plia.onnx",
             "enabled": True,  "sensitivity": 0.5, "builtin": True},
            {"id": "alexa",       "display": "Alexa",       "path": "bundled/alexa.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
            {"id": "hey_mycroft", "display": "Hey Mycroft", "path": "bundled/hey_mycroft.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
            {"id": "ok_nabu",     "display": "OK Nabu",     "path": "bundled/ok_nabu.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
            {"id": "hey_rhasspy", "display": "Hey Rhasspy", "path": "bundled/hey_rhasspy.onnx",
             "enabled": False, "sensitivity": 0.5, "builtin": True},
        ],
        "enabled":                True,
        "auto_start":             True,
        "startup_greeting":       True,
        "stt_energy_threshold":   300,
    },
    # ── General ──────────────────────────────────────────────────────────
    "general": {
        "max_history":      20,
        "auto_fetch_news":  True,
    },

    # ── Privacy / Redaction ─────────────────────────────────────────────
    "redaction": {
        "enabled": True,
        "strictness": "normal",  # "light" | "normal" | "strict"
        "blocklist": [],         # list[str] of regex or substring patterns
    },

    # ── Morning Digest (daily scheduled briefing) ───────────────────────
    "morning_digest": {
        "enabled": True,
        "time": "08:00",      # local time HH:MM (24h)
        "use_ai": True,       # curated via Ollama/local LLM
        "speak": True,        # speak a short summary via TTS
        "categories": ["Technology", "Science", "World", "Space", "Top Stories"],
    },

    # ── Weather ──────────────────────────────────────────────────────────
    "weather": {
        "latitude":         -32.1151,
        "longitude":        116.0255,
        "city":             "Kelmscott, Western Australia, Australia",
        "country":          "Australia",
        "country_code":     "AU",
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
    # ── Email ───────────────────────────────────────────────────────────
    "email": {
        "smtp_server":   "",
        "smtp_port":     587,
        "imap_server":   "",
        "imap_port":     993,
        "username":      "",
        "password":      "",
        "from_address":  "",
    },
    # ── Notes ───────────────────────────────────────────────────────────
    "notes": {
        "max_notes": 500,
    },
    # ── Finance ─────────────────────────────────────────────────────────
    "finance": {
        "currency": "USD",
    },
    # ── Web search backend ──────────────────────────────────────────────
    # Backend "brave" requires a (free) API key from https://api.search.brave.com.
    # With an empty key Plia falls back to DuckDuckGo automatically.
    "search": {
        "backend":      "auto",   # "auto" | "brave" | "duckduckgo"
        "brave_api_key": "",
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
                    self._migrate_voice_wake_word()
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

    def _migrate_voice_wake_word(self):
        """One-time migration: voice.wake_word (str) → voice.wake_models (list).

        Runs when the loaded config still has the old single-string key. Maps
        the old default 'jarvis' to ['hey_jarvis', 'plia'] enabled; any other
        Porcupine keyword (which has no openWakeWord equivalent) gets the
        same default plus a flag so the UI can show a one-time toast.

        Defensive: on any failure (e.g. a malformed `voice` value), resets the
        voice section to defaults so the app can start.
        """
        try:
            voice = self._settings.get("voice")
            if not isinstance(voice, dict):
                # Malformed config — reset to defaults.
                self._settings["voice"] = {
                    k: (v.copy() if isinstance(v, (dict, list)) else v)
                    for k, v in DEFAULT_SETTINGS["voice"].items()
                }
                return

            if "wake_word" not in voice:
                return  # Already migrated or never seen the old schema.

            old_word = voice.pop("wake_word", None)
            voice.pop("sensitivity", None)
            voice.pop("sensitivity_pct", None)

            if "wake_models" not in voice or not voice["wake_models"]:
                voice["wake_models"] = [
                    m.copy() for m in DEFAULT_SETTINGS["voice"]["wake_models"]
                ]

            if old_word and old_word != "jarvis":
                voice["_migration_toast_pending"] = True

            self._settings["voice"] = voice
        except Exception as exc:
            print(f"[Settings] Wake-word migration failed: {exc}. Resetting voice section to defaults.")
            self._settings["voice"] = {
                k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in DEFAULT_SETTINGS["voice"].items()
            }

    # ── Public API ────────────────────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a setting by dot-notation path.
        Examples:
            get("models.chat")          → "qwen3:1.7b"
            get("tts.volume")           → 0.9
            get("voice.wake_models")    → [{"id": "plia", ...}, ...]
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
