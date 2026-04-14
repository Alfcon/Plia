"""
Speech-to-Text for Plia Voice Assistant.

Two engines are provided:

1. STTListener  — full-featured engine used by the main PySide6 app.
   Uses RealTimeSTT + Porcupine wake word detection (pvporcupine).
   Wake words: see SUPPORTED_WAKE_WORDS below (no API key needed).

2. SpeechEngine — lightweight fallback from plia2.py standalone mode.
   Uses AudioToTextRecorder with the Whisper tiny.en model.
   No wake-word backend needed; uses a software prefix scan instead.
   Suitable for the standalone Tkinter launcher (plia2.py).

Wake word notes (Porcupine backend):
  Porcupine has a fixed list of built-in words that work offline with
  no API key:
    alexa, americano, blueberry, bumblebee, computer, grapefruits,
    grasshopper, hey google, hey siri, jarvis, ok google, picovoice,
    porcupine, terminator

  These are the ONLY valid choices for the STTListener wake word
  setting. The WAKE_WORDS list below is used by SpeechEngine (plia2)
  and can include any prefix strings.
"""

import threading
import time
from typing import Callable

from config import (
    REALTIMESTT_MODEL,
    PORCUPINE_ACCESS_KEY,
    GRAY, RESET, CYAN, YELLOW, GREEN,
)
from core.settings_store import settings as app_settings

# ── Wake words ────────────────────────────────────────────────────────────

# Porcupine-supported words (STTListener / full app)
SUPPORTED_WAKE_WORDS: list[str] = [
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

# Prefix-scan wake words (SpeechEngine / plia2 standalone mode)
# These can be any free-form strings — checked via startswith().
WAKE_WORDS: list[str] = [
    "plia",
    "hey plia",
    "ok plia",
    "friday",
    "jarvis",
    "hey jarvis",
]


# ── Settings helpers ───────────────────────────────────────────────────────

def _get_wake_word() -> str:
    """Read wake word from settings, validate it is Porcupine-supported."""
    word = app_settings.get("voice.wake_word", DEFAULT_WAKE_WORD)
    word = (word or DEFAULT_WAKE_WORD).strip().lower()
    if word not in SUPPORTED_WAKE_WORDS:
        print(
            f"[STT] ⚠ '{word}' is not a Porcupine wake word — "
            f"falling back to '{DEFAULT_WAKE_WORD}'"
        )
        return DEFAULT_WAKE_WORD
    return word


def _get_sensitivity() -> float:
    """Read sensitivity from settings (0-100 int or 0.0-1.0 float → 0.0-1.0)."""
    try:
        val = float(app_settings.get("voice.sensitivity", 0.5))
        if val > 1.0:
            val /= 100.0
        return max(0.0, min(1.0, val))
    except (TypeError, ValueError):
        return 0.5


# ══════════════════════════════════════════════════════════════════════════
#  STTListener  — full-featured engine (main PySide6 app)
# ══════════════════════════════════════════════════════════════════════════
class STTListener:
    """
    Real-time STT listener using Porcupine wake word detection.
    No API key needed; works offline with SUPPORTED_WAKE_WORDS.
    Wake word is re-read from settings on each initialize() call so
    Settings → Apply & Refresh All picks up changes immediately.
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

        print(f"{CYAN}[STT] Initializing RealTimeSTT listener…{RESET}")
        print(f"{CYAN}[STT] Wake word: '{self._wake_word}'{RESET}")

    def initialize(self) -> bool:
        """Initialize RealTimeSTT. Re-reads wake word from settings each call."""
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

            print(f"{CYAN}[STT] Wake word backend: Porcupine (built-in, no API key){RESET}")

            device = "cuda" if cuda_available else "cpu"
            print(f"{CYAN}[STT] Initializing AudioToTextRecorder on {device}…{RESET}")

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
        except Exception as exc:
            print(f"{GRAY}[STT] ✗ Initialization error: {exc}{RESET}")
            import traceback
            traceback.print_exc()
            return False

    def _on_wakeword_detected(self):
        print(f"\n{CYAN}[STT] 👂 '{self._wake_word}' detected! Listening…{RESET}")
        if self.wake_word_callback:
            self.wake_word_callback()

    def start(self) -> bool:
        """Start the listening loop in a background daemon thread."""
        if not self.initialized:
            print(f"{YELLOW}[STT] Not initialized — call initialize() first.{RESET}")
            return False
        if self.running:
            return True
        self.running = True
        try:
            self.listening_thread = threading.Thread(
                target=self._run_listener, daemon=True
            )
            self.listening_thread.start()
            print(f"{CYAN}[STT] ✓ Listener started{RESET}")
            return True
        except Exception as exc:
            print(f"{GRAY}[STT] Failed to start: {exc}{RESET}")
            self.running = False
            return False

    def _run_listener(self):
        """Main transcription loop — blocks on recorder.text()."""
        try:
            print(f"{GRAY}[STT] Waiting for wake word '{self._wake_word}'…{RESET}")
            while self.running:
                if not self.recorder:
                    break
                try:
                    text = self.recorder.text()
                except (BrokenPipeError, OSError) as pipe_err:
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
                    wake  = self._wake_word
                    clean = text.replace(wake, "").replace(wake.capitalize(), "")
                    clean = clean.replace(wake.upper(), "").strip()
                    print(f"{CYAN}[STT] Heard: '{clean}'{RESET}")
                    if clean:
                        self.speech_callback(clean)
                    else:
                        print(f"{GRAY}[STT] Empty after wake word removal — skipping{RESET}")

        except Exception as exc:
            print(f"{GRAY}[STT] Listener error: {exc}{RESET}")
            import traceback
            traceback.print_exc()
            self.running = False

    def stop(self):
        """Stop listening and shut down the recorder."""
        self.running = False
        if self.recorder:
            try:
                self.recorder.shutdown()
            except Exception as exc:
                print(f"{GRAY}[STT] Error stopping recorder: {exc}{RESET}")
        if self.listening_thread:
            self.listening_thread.join(timeout=2.0)
        self.initialized = False
        print(f"{CYAN}[STT] Listener stopped{RESET}")


# ══════════════════════════════════════════════════════════════════════════
#  SpeechEngine  — lightweight engine (plia2.py standalone Tkinter mode)
#
#  Uses AudioToTextRecorder with Whisper tiny.en (no Porcupine).
#  Wake word detection is done by prefix-scanning transcribed text
#  against the WAKE_WORDS list.  Suitable for the plia2.py launcher.
# ══════════════════════════════════════════════════════════════════════════
class SpeechEngine:
    """
    Simplified STT for standalone (Tkinter) mode.

    Install: pip install realtimestt>=0.3.0 PyAudio>=0.2.14
    First-run model download: ~75 MB (Whisper tiny.en, automatic).
    """

    def __init__(self, settings: dict | None = None):
        s = settings or {}
        self._listening = False
        self.recorder   = None

        try:
            from RealtimeSTT import AudioToTextRecorder
            energy = int(s.get("stt_energy_threshold", 300))
            # Map energy_threshold (50-1000) to WebRTC sensitivity (1-3)
            webrtc_sens = max(1, min(3, round(energy / 333)))
            self.recorder = AudioToTextRecorder(
                model="tiny.en",
                language="en",
                compute_type="int8",
                spinner=False,
                silero_sensitivity=0.4,
                webrtc_sensitivity=webrtc_sens,
                post_speech_silence_duration=0.5,
                min_length_of_recording=0.3,
                min_gap_between_recordings=0.2,
            )
            self.enabled = True
        except Exception as exc:
            print(f"  [RealtimeSTT] Initialization error: {exc}")
            self.enabled = False

    def listen_once(self, timeout: int = 8) -> str | None:
        """
        Block until one phrase is transcribed (or timeout expires).
        Returns the text string, "" for silence, or None on error/timeout.
        """
        if not self.enabled or not self.recorder:
            return None
        result = [None]
        done   = threading.Event()

        def _transcribe():
            try:
                text      = self.recorder.text()
                result[0] = text.strip() if text else ""
            except Exception:
                pass
            finally:
                done.set()

        threading.Thread(target=_transcribe, daemon=True).start()
        done.wait(timeout=timeout)
        return result[0]

    def listen_for_wake_word(
        self,
        callback_found: Callable | None = None,
        callback_not: Callable | None   = None,
    ):
        """
        Continuously transcribe audio. When a WAKE_WORDS prefix is
        detected, the command remainder is passed to callback_found;
        otherwise callback_not receives the raw text.
        """
        if not self.enabled:
            if callback_not:
                callback_not("Speech recognition not available")
            return
        self._listening = True

        def _loop():
            while self._listening:
                text = self.listen_once(timeout=5)
                if not text or not text.strip():
                    continue
                low     = text.lower().strip()
                matched = False
                for ww in WAKE_WORDS:
                    if low.startswith(ww):
                        cmd = low[len(ww):].strip()
                        if callback_found:
                            callback_found(cmd if cmd else None)
                        matched = True
                        break
                if not matched and callback_not:
                    callback_not(text)

        threading.Thread(target=_loop, daemon=True).start()

    def stop_listening(self):
        """Signal the listen loop to exit on its next iteration."""
        self._listening = False
