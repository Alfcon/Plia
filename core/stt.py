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

Torchaudio note:
  Silero VAD (used internally by RealtimeSTT) imports torchaudio at
  module-load time.  On Windows, if torchaudio and torch were built for
  different CUDA versions, this triggers:
      OSError: [WinError 127] The specified procedure could not be found
  Additionally, if torch itself failed to initialise in a parallel
  thread (e.g. via the torch.hub/tqdm circular-import bug fixed in
  router.py), the broken sys.modules state can produce:
      KeyError: 'torch'

  _patch_torchaudio_if_broken() below intercepts ALL of these failures
  and injects a minimal stub so that silero_vad can import cleanly.
  Silero inference itself runs on raw PyTorch tensors and does NOT need
  the torchaudio native extension; WebRTC VAD handles all activity
  detection when silero_sensitivity=0.0.

  To permanently fix the environment (recommended):
      conda activate plia
      pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 ^
          --index-url https://download.pytorch.org/whl/cu124
  Verify afterwards:
      python -c "import torchaudio; print(torchaudio.__version__)"

Log file location:
  All RealTimeSTT log output is redirected to Plia/log/realtimesst.log
  by configuring the 'realtimestt' Python logger here, before the
  library is imported for the first time.
"""

import sys
import threading
import time
import types
import logging
import os
from typing import Callable

from config import (
    REALTIMESTT_MODEL,
    PORCUPINE_ACCESS_KEY,
    GRAY, RESET, CYAN, YELLOW, GREEN,
)
from core.settings_store import settings as app_settings

# ── Log directory setup ────────────────────────────────────────────────────
# Redirect the RealTimeSTT logger to Plia/log/realtimesst.log BEFORE
# the library is imported for the first time.  Python's logging.basicConfig
# is a no-op if the root logger already has handlers, so we also add a
# NullHandler to root to prevent the library from creating a stray
# realtimestt.log in the project root.

def _setup_stt_logging() -> None:
    """Redirect the realtimestt logger to Plia/log/realtimesst.log.

    Root-cause note (RealtimeSTT library behaviour):
      AudioToTextRecorder.__init__() calls
          logging.FileHandler('realtimesst.log')
      with a *relative* path, which creates the file in the current working
      directory (the Plia project root) — not in log/.
      The definitive fix is to pass  no_log_file=True  to every
      AudioToTextRecorder() call so the library never opens that FileHandler.
      This function then remains the sole owner of the 'realtimestt' logger's
      FileHandler, correctly pointing to  Plia/log/realtimesst.log.
    """
    # Resolve the log directory relative to this file's package root
    # core/stt.py  →  project root  →  log/
    _core_dir   = os.path.dirname(os.path.abspath(__file__))
    _proj_root  = os.path.dirname(_core_dir)
    _log_dir    = os.path.join(_proj_root, "log")
    os.makedirs(_log_dir, exist_ok=True)

    _log_path = os.path.join(_log_dir, "realtimesst.log")

    # Prevent Python logging.basicConfig (called inside RealtimeSTT) from
    # creating its own log file in the project root by ensuring the root
    # logger already has a handler before the library is imported.
    _root = logging.getLogger()
    if not _root.handlers:
        _root.addHandler(logging.NullHandler())

    # Configure the specific realtimestt logger.
    # no_log_file=True on AudioToTextRecorder() means the library will NOT add
    # its own FileHandler here, so Plia's handler below is the only one.
    _rtstt = logging.getLogger("realtimestt")
    if not any(isinstance(h, logging.FileHandler) for h in _rtstt.handlers):
        _fh = logging.FileHandler(_log_path, mode="a", encoding="utf-8")
        _fh.setLevel(logging.DEBUG)
        _fh.setFormatter(logging.Formatter(
            "%(asctime)s.%(msecs)03d - RealTimeSTT: %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        _rtstt.addHandler(_fh)
        _rtstt.setLevel(logging.DEBUG)
        _rtstt.propagate = False   # Keep realtimestt logs out of the root logger


_setup_stt_logging()   # Run immediately at module import


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


# ── Torchaudio pre-flight patch ────────────────────────────────────────────

def _patch_torchaudio_if_broken() -> bool:
    """
    Try importing torchaudio.  Three classes of failure are handled:

    1. OSError [WinError 127]
       torch and torchaudio DLLs were compiled for different CUDA versions.
       Classic environment mismatch; inject stub.

    2. KeyError('torch')
       torch itself failed to initialise in a parallel thread (e.g. the
       torch.hub/tqdm circular-import bug that was fixed in router.py by
       making torch a lazy import).  The broken partial-load can leave
       sys.modules in an inconsistent state where accessing 'torch'
       raises KeyError inside the frozen importlib bootstrap.
       Inject stub.

    3. Any other Exception
       Unexpected torchaudio import failure (missing DLL, broken install,
       etc.).  Inject stub so the rest of Plia can still function.

    When the stub is active, silero_sensitivity is forced to 0.0 in the
    caller so that Silero's runtime code is never reached; WebRTC VAD
    handles all activity detection instead.

    Returns True  if torchaudio imported cleanly (no action taken).
    Returns False if a stub was injected or torchaudio is absent.
    """
    try:
        import torchaudio  # noqa: F401
        return True

    except OSError as exc:
        if getattr(exc, "winerror", None) == 127 or "WinError 127" in str(exc):
            print(
                f"{YELLOW}[STT] ⚠  torchaudio DLL mismatch (WinError 127) detected.{RESET}"
            )
            print(
                f"{YELLOW}[STT]    Injecting compatibility stub — "
                f"Silero VAD bypassed, WebRTC VAD active.{RESET}"
            )
            print(
                f"{YELLOW}[STT]    To fix permanently, run inside (plia):{RESET}"
            )
            print(
                f"{YELLOW}[STT]      pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 "
                f"--index-url https://download.pytorch.org/whl/cu124{RESET}"
            )
            _inject_torchaudio_stub()
            return False
        # Any other OSError (e.g. missing DLL not related to WinError 127)
        print(
            f"{YELLOW}[STT] ⚠  torchaudio OSError ({exc}).{RESET}"
        )
        _inject_torchaudio_stub()
        return False

    except ImportError:
        # torchaudio simply not installed
        print(
            f"{YELLOW}[STT] ⚠  torchaudio not installed. "
            f"Silero VAD will be skipped; WebRTC VAD active.{RESET}"
        )
        _inject_torchaudio_stub()
        return False

    except KeyError as exc:
        # KeyError('torch') — torch's module import failed in a parallel
        # thread and the broken entry was removed from sys.modules, leaving
        # torchaudio unable to resolve its torch dependency.
        # Root cause is fixed in router.py; this clause is a belt-and-
        # braces safety net.
        print(
            f"{YELLOW}[STT] ⚠  torchaudio raised KeyError({exc}) during import.{RESET}"
        )
        print(
            f"{YELLOW}[STT]    This usually means torch's circular import failed "
            f"in a parallel thread.{RESET}"
        )
        print(
            f"{YELLOW}[STT]    Injecting compatibility stub — WebRTC VAD active.{RESET}"
        )
        _inject_torchaudio_stub()
        return False

    except Exception as exc:
        # Catch-all: any other unexpected error during torchaudio import
        print(
            f"{YELLOW}[STT] ⚠  torchaudio import failed "
            f"({type(exc).__name__}: {exc}).{RESET}"
        )
        print(
            f"{YELLOW}[STT]    Injecting compatibility stub — WebRTC VAD active.{RESET}"
        )
        _inject_torchaudio_stub()
        return False


def _inject_torchaudio_stub() -> None:
    """
    Install a no-op torchaudio stub into sys.modules.

    Submodule stubs are required because silero_vad's hubconf.py does:
        from silero_vad.utils_vad import (init_jit_model, ...)
    and utils_vad.py starts with:
        import torchaudio
    If the parent is stubbed but sub-packages are absent, a second
    import of a sub-module would raise ImportError.
    """
    _STUB_SUBMODULES = [
        "torchaudio._extension",
        "torchaudio._extension.utils",
        "torchaudio._internal",
        "torchaudio._internal.fb",
        "torchaudio.backend",
        "torchaudio.backend.common",
        "torchaudio.transforms",
        "torchaudio.functional",
        "torchaudio.io",
    ]
    # Only inject if not already stubbed
    if sys.modules.get("torchaudio") is not None:
        existing = sys.modules["torchaudio"]
        if getattr(existing, "__version__", None) == "0.0.0+stub":
            return   # Already stubbed

    stub_root = types.ModuleType("torchaudio")
    stub_root.__version__ = "0.0.0+stub"
    stub_root.__path__ = []  # mark as package
    sys.modules["torchaudio"] = stub_root

    for name in _STUB_SUBMODULES:
        sub = types.ModuleType(name)
        sys.modules[name] = sub
        # Attach as attribute on the parent (e.g. torchaudio._extension)
        parts = name.split(".")
        parent = sys.modules.get(".".join(parts[:-1]))
        if parent is not None:
            setattr(parent, parts[-1], sub)


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

    Startup sequence
    ----------------
    1. _patch_torchaudio_if_broken() is called first.
       • If torchaudio is healthy  → normal Silero + WebRTC VAD.
       • If WinError 127 detected  → stub injected, WebRTC VAD only
         (silero_sensitivity=0.0, silero_deactivity_detection=False).
       • If KeyError('torch')      → stub injected, WebRTC VAD only.
       • Any other Exception       → stub injected, WebRTC VAD only.
       All paths produce a working recorder.
    2. AudioToTextRecorder is created with Porcupine as the wake-word
       backend.  Silero VAD is bypassed when the stub is active.
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
            # ── Step 1: torchaudio pre-flight ─────────────────────────────
            # Must run BEFORE `from RealtimeSTT import AudioToTextRecorder`
            # because RealtimeSTT imports torch.hub which triggers the Silero
            # import chain (which imports torchaudio) during recorder init.
            torchaudio_ok = _patch_torchaudio_if_broken()

            # ── Step 2: import RealtimeSTT & torch ────────────────────────
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

            # ── Step 3: choose VAD mode ────────────────────────────────────
            if torchaudio_ok:
                silero_sens   = self._sensitivity * 0.6
                silero_deact  = False
                print(f"{CYAN}[STT] VAD mode: Silero + WebRTC (torchaudio healthy){RESET}")
            else:
                silero_sens   = 0.0
                silero_deact  = False
                print(f"{YELLOW}[STT] VAD mode: WebRTC only (Silero bypassed — see fix above){RESET}")

            # ── Step 4: create the recorder ───────────────────────────────
            self.recorder = AudioToTextRecorder(
                model=REALTIMESTT_MODEL,
                language="en",
                device=device,
                spinner=False,
                wakeword_backend="pvporcupine",
                wake_words=self._wake_word,
                wake_words_sensitivity=self._sensitivity,
                on_wakeword_detected=self._on_wakeword_detected,
                silero_sensitivity=silero_sens,
                silero_deactivity_detection=silero_deact,
                webrtc_sensitivity=3,
                no_log_file=True,       # Prevents library writing realtimesst.log to
                                        # the project root; Plia's _setup_stt_logging()
                                        # already owns the 'realtimestt' FileHandler
                                        # pointing to log/realtimesst.log.
            )

            self.initialized = True
            vad_note = "" if torchaudio_ok else " (WebRTC VAD only)"
            print(f"{CYAN}[STT] ✓ Ready{vad_note} — say '{self._wake_word}' to activate{RESET}")
            return True

        except ImportError as exc:
            print(f"{GRAY}[STT] ✗ Missing dependency: {exc}. Run: pip install realtimestt{RESET}")
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

        # Apply torchaudio patch before attempting RealtimeSTT import
        _patch_torchaudio_if_broken()

        try:
            from RealtimeSTT import AudioToTextRecorder
            energy = int(s.get("stt_energy_threshold", 300))
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
                no_log_file=True,       # Prevents library writing realtimesst.log to
                                        # the project root; Plia's _setup_stt_logging()
                                        # already owns the 'realtimestt' FileHandler
                                        # pointing to log/realtimesst.log.
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
