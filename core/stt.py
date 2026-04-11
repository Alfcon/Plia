"""
Speech-to-Text with Wake Word Detection for Voice Assistant.
Uses RealTimeSTT for real-time transcription with built-in wake word detection.

IMPORTANT — how wake words work:
  The Porcupine backend (pvporcupine) has a fixed list of built-in words that
  work without any API key or model files:
    alexa, americano, blueberry, bumblebee, computer, grapefruits, grasshopper,
    hey google, hey siri, jarvis, ok google, picovoice, porcupine, terminator

  The OpenWakeWord backend (oww) requires pre-trained .onnx model files for each
  word — you CANNOT pass an arbitrary text string. It does NOT accept the same
  word list as Porcupine.

  Therefore: we always use Porcupine (pvporcupine) for wake word detection since
  it works offline with no API key and supports all the words above. The wake word
  setting in Plia must be one of the supported words from that list.
"""

import threading
import time
from typing import Callable

from config import (
    REALTIMESTT_MODEL,
    PORCUPINE_ACCESS_KEY,
    GRAY, RESET, CYAN, YELLOW, GREEN
)
from core.settings_store import settings as app_settings

# ---------------------------------------------------------------------------
# The complete list of words supported by Porcupine without an API key.
# These are the ONLY valid choices for the wake word setting.
# ---------------------------------------------------------------------------
SUPPORTED_WAKE_WORDS = [
    "jarvis",
    "computer",
    "alexa",
    "hey google",
    "ok google",
    "hey siri",
    "terminator",
    "bumblebee",
    "grasshopper",
    "porcupine",
    "americano",
    "blueberry",
    "grapefruits",
    "picovoice",
]

DEFAULT_WAKE_WORD = "jarvis"


def _get_wake_word() -> str:
    """Read wake word from settings, validate it is supported."""
    word = app_settings.get("voice.wake_word", DEFAULT_WAKE_WORD)
    word = (word or DEFAULT_WAKE_WORD).strip().lower()
    if word not in SUPPORTED_WAKE_WORDS:
        print(f"[STT] ⚠ '{word}' is not a supported wake word — falling back to '{DEFAULT_WAKE_WORD}'")
        return DEFAULT_WAKE_WORD
    return word


def _get_sensitivity() -> float:
    """Read sensitivity from settings (stored as 0-100 int, returned as 0.0-1.0)."""
    try:
        val = app_settings.get("voice.sensitivity", 0.5)
        val = float(val)
        # Accept either 0-1 float or 0-100 int
        if val > 1.0:
            val = val / 100.0
        return max(0.0, min(1.0, val))
    except (TypeError, ValueError):
        return 0.5


class STTListener:
    """
    Real-time STT listener using Porcupine wake word detection (no API key needed).
    Wake word is re-read from settings each time initialize() is called, so
    Apply & Refresh All in Settings picks up the new word immediately.
    """

    def __init__(self, wake_word_callback: Callable, speech_callback: Callable):
        self.wake_word_callback = wake_word_callback
        self.speech_callback    = speech_callback
        self.running            = False
        self.listening_thread   = None
        self.recorder           = None
        self.initialized        = False
        self._wake_word         = _get_wake_word()
        self._sensitivity       = _get_sensitivity()

        print(f"{CYAN}[STT] Initializing RealTimeSTT listener...{RESET}")
        print(f"{CYAN}[STT] Wake word: '{self._wake_word}'{RESET}")

    def initialize(self) -> bool:
        """Initialize RealTimeSTT. Re-reads wake word from settings each call."""
        # Always re-read so Apply & Refresh All picks up changes
        self._wake_word   = _get_wake_word()
        self._sensitivity = _get_sensitivity()

        print(f"{CYAN}[STT] Wake word: '{self._wake_word}'  Sensitivity: {self._sensitivity}{RESET}")

        try:
            from RealtimeSTT import AudioToTextRecorder
            import torch

            cuda_available = torch.cuda.is_available()
            if cuda_available:
                cuda_name = torch.cuda.get_device_name(torch.cuda.current_device())
                print(f"{GREEN}[STT] ✓ CUDA available ({cuda_name}){RESET}")
            else:
                print(f"{YELLOW}[STT] ⚠ CUDA not available — using CPU{RESET}")

            # Always use pvporcupine — it supports all SUPPORTED_WAKE_WORDS
            # without any API key. oww requires custom-trained .onnx model files
            # and cannot accept arbitrary text wake word strings.
            print(f"{CYAN}[STT] Wake word backend: Porcupine (built-in, no API key needed){RESET}")

            device = "cuda" if cuda_available else "cpu"
            print(f"{CYAN}[STT] Initializing AudioToTextRecorder on {device}...{RESET}")

            self.recorder = AudioToTextRecorder(
                model=REALTIMESTT_MODEL,
                language="en",
                device=device,
                spinner=False,
                wakeword_backend="pvporcupine",
                wake_words=self._wake_word,
                wake_words_sensitivity=self._sensitivity,
                on_wakeword_detected=self._on_wakeword_detected,
            )

            self.initialized = True
            print(f"{CYAN}[STT] ✓ Ready — say '{self._wake_word}' to activate{RESET}")
            return True

        except ImportError:
            print(f"{GRAY}[STT] ✗ RealTimeSTT not installed. Run: pip install realtimestt{RESET}")
            return False
        except Exception as e:
            print(f"{GRAY}[STT] ✗ Initialization error: {e}{RESET}")
            import traceback
            traceback.print_exc()
            return False

    def _on_wakeword_detected(self):
        """Called when the wake word is detected."""
        print(f"\n{CYAN}[STT] 👂 '{self._wake_word}' detected! Listening...{RESET}")
        if self.wake_word_callback:
            self.wake_word_callback()

    def start(self):
        """Start the listening loop in a background thread."""
        if not self.initialized:
            print(f"{YELLOW}[STT] Not initialized — call initialize() first.{RESET}")
            return False
        if self.running:
            print(f"{YELLOW}[STT] Already running.{RESET}")
            return True

        self.running = True
        try:
            self.listening_thread = threading.Thread(
                target=self._run_listener, daemon=True
            )
            self.listening_thread.start()
            print(f"{CYAN}[STT] ✓ Listener started{RESET}")
            return True
        except Exception as e:
            print(f"{GRAY}[STT] Failed to start: {e}{RESET}")
            self.running = False
            return False

    def _run_listener(self):
        """Main transcription loop — blocks on recorder.text() until wake word heard."""
        try:
            print(f"{GRAY}[STT] Waiting for wake word '{self._wake_word}'...{RESET}")
            while self.running:
                if not self.recorder:
                    break

                try:
                    text = self.recorder.text()
                except (BrokenPipeError, OSError) as pipe_err:
                    # [WinError 109] or similar: the audio subprocess pipe was broken.
                    # This can happen on Windows when another QThread is destroyed
                    # abruptly (e.g. after an Ollama model download completes).
                    # Log it, pause briefly, and continue — the recorder's own
                    # reconnect logic will usually re-establish the connection.
                    if not self.running:
                        break
                    print(f"{GRAY}[STT] Audio pipe interrupted ({pipe_err}) — retrying in 2 s…{RESET}")
                    time.sleep(2.0)
                    continue
                except Exception as inner_err:
                    if not self.running:
                        break
                    print(f"{GRAY}[STT] recorder.text() error: {inner_err} — retrying in 1 s…{RESET}")
                    time.sleep(1.0)
                    continue

                if text and text.strip():
                    # Strip the wake word from the transcribed text
                    wake  = self._wake_word
                    clean = text.replace(wake, "").replace(wake.capitalize(), "")
                    clean = clean.replace(wake.upper(), "").strip()

                    print(f"{CYAN}[STT] Heard: '{clean}'{RESET}")

                    if clean:
                        self.speech_callback(clean)
                    else:
                        print(f"{GRAY}[STT] Empty after wake word removal — skipping{RESET}")

        except Exception as e:
            print(f"{GRAY}[STT] Listener error: {e}{RESET}")
            import traceback
            traceback.print_exc()
            self.running = False

    def stop(self):
        """Stop listening and shut down the recorder."""
        self.running = False
        if self.recorder:
            try:
                self.recorder.shutdown()
            except Exception as e:
                print(f"{GRAY}[STT] Error stopping recorder: {e}{RESET}")
        if self.listening_thread:
            self.listening_thread.join(timeout=2.0)
        self.initialized = False
        print(f"{CYAN}[STT] Listener stopped{RESET}")
