"""
TTS (Text-to-Speech) module — Piper TTS.

Primary:  Python `piper-tts` library (PiperVoice) + sounddevice.
          Install: pip install piper-tts>=1.4.0 sounddevice>=0.5.0 numpy>=2.0.0
          Voice models live in ~/.plia_ai/tts_models/ (auto-download on first run).
          Download extra voices from https://huggingface.co/rhasspy/piper-voices

Fallback: Pre-built Piper executable (Windows only, downloaded automatically).
          Used only when the Python library is not installed.

The module exposes a `tts` singleton and a `SentenceBuffer` helper.
API is unchanged from the previous version so the rest of the codebase
(voice_assistant.py, handlers.py, gui/) works without modification.
"""

import io
import os
import re
import queue
import threading
import wave
from pathlib import Path

# ── Optional: requests for model auto-download ────────────────────────────
try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Primary: piper Python library ─────────────────────────────────────────
try:
    from piper import PiperVoice
    import sounddevice as sd
    import numpy as np
    HAS_PIPER_LIB = True
except ImportError:
    HAS_PIPER_LIB = False

# ── Detect which piper-tts API generation is installed ────────────────────
# New API (piper-tts >= 1.4 / OHF-Voice fork, April 2026+):
#   PiperVoice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig(...))
#   PiperVoice.synthesize(text)  → iterator of AudioChunk
# Old API (rhasspy/piper, archived Oct 2025):
#   PiperVoice.synthesize(text, wav_file)  — no extra kwargs accepted
try:
    from piper import SynthesisConfig as _SynthesisConfig
    HAS_SYNTHESIS_CONFIG = True
except ImportError:
    _SynthesisConfig     = None
    HAS_SYNTHESIS_CONFIG = False

# ── Fallback: piper executable (Windows) ──────────────────────────────────
if not HAS_PIPER_LIB:
    try:
        import subprocess
        import zipfile
        import numpy as np
        import sounddevice as sd
        HAS_PIPER_EXE_DEPS = True
    except ImportError:
        HAS_PIPER_EXE_DEPS = False
else:
    HAS_PIPER_EXE_DEPS = False   # Not needed — library is available

# ── ANSI colours for console output ───────────────────────────────────────
GRAY   = "\033[90m"
CYAN   = "\033[36m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RESET  = "\033[0m"

# ── Paths ──────────────────────────────────────────────────────────────────
PLIA_DIR        = Path.home() / ".plia_ai"
PIPER_MODEL_DIR = PLIA_DIR / "tts_models"
PLIA_DIR.mkdir(parents=True, exist_ok=True)
PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Fallback executable directory (Windows executable approach)
_EXE_DIR = Path.home() / ".local" / "share" / "piper"

# ── Default voice model ────────────────────────────────────────────────────
DEFAULT_VOICE = "en_US-lessac-medium"

# HuggingFace URLs for the default English voice (Python library approach)
_DEFAULT_MODEL_URL  = (
    "https://huggingface.co/rhasspy/piper-voices/resolve"
    "/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
)
_DEFAULT_CONFIG_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve"
    "/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
)

# Piper Windows executable (fallback)
_PIPER_VERSION     = "2023.11.14-2"
_PIPER_RELEASE_URL = (
    f"https://github.com/rhasspy/piper/releases/download"
    f"/{_PIPER_VERSION}/piper_windows_amd64.zip"
)


# ══════════════════════════════════════════════════════════════════════════
#  SentenceBuffer  — unchanged, used by voice_assistant.py for streaming
# ══════════════════════════════════════════════════════════════════════════
class SentenceBuffer:
    """Buffers streaming text and extracts complete sentences."""

    SENTENCE_ENDINGS = re.compile(r'([.!?])\s+|([.!?])$')

    def __init__(self):
        self.buffer = ""

    def add(self, text: str) -> list[str]:
        """Add a text chunk; return any newly complete sentences."""
        self.buffer += text
        sentences = []
        while True:
            m = self.SENTENCE_ENDINGS.search(self.buffer)
            if m:
                end_pos  = m.end()
                sentence = self.buffer[:end_pos].strip()
                if sentence:
                    sentences.append(sentence)
                self.buffer = self.buffer[end_pos:]
            else:
                break
        return sentences

    def flush(self) -> str | None:
        """Return any remaining buffered text as a final sentence."""
        remaining   = self.buffer.strip()
        self.buffer = ""
        return remaining if remaining else None


# ══════════════════════════════════════════════════════════════════════════
#  VoiceEngine  — primary TTS engine (Python piper-tts library)
#  Matches the interface previously provided by PiperTTS so the rest of
#  the codebase can call tts.queue_sentence() / tts.stop() unchanged.
# ══════════════════════════════════════════════════════════════════════════
class VoiceEngine:
    """
    Local neural TTS via the piper-tts Python library + sounddevice.

    Lifecycle:
        engine = VoiceEngine()
        engine.initialize()          # loads model (downloads if needed)
        engine.toggle(True)          # enable playback
        engine.queue_sentence("Hi")  # async enqueue
        engine.stop()                # interrupt
        engine.shutdown()            # clean up
    """

    def __init__(self, settings: dict | None = None):
        s = settings or {}
        self.enabled        = False          # set True after successful initialize()
        self._engine        = None           # PiperVoice instance
        self.muted          = bool(s.get("tts_muted", False))
        self.volume         = float(s.get("tts_volume", 0.9))
        self.length_scale   = float(s.get("tts_length_scale", 1.0))
        self._lock          = threading.Lock()   # synthesis lock (ONNX)
        self._play_lock     = threading.Lock()   # playback lock (sounddevice)
        self._speech_queue  = queue.Queue()
        self._worker_thread = None
        self._running       = False
        self.available      = HAS_PIPER_LIB  # False if library is missing

        # Fallback: executable path (only used when HAS_PIPER_LIB is False)
        self.piper_exe   = None
        self.model_path  = None
        self.VOICE_MODEL = s.get("tts_voice", DEFAULT_VOICE)
        self.current_process = None

        # Maximum characters per TTS call — ONNX Runtime can segfault on
        # extremely long strings; split defensively at this boundary.
        self._MAX_CHARS = 400

    # ── Model discovery / auto-download (Python library) ─────────────────

    def _find_or_download_model(self) -> str | None:
        """Return path to the first .onnx model found; download default if absent."""
        found = self._scan_model_dir()
        if found:
            return found
        if HAS_REQUESTS:
            print(f"{CYAN}[TTS] No local model found — attempting auto-download…{RESET}")
            return self._download_default_model()
        print(
            f"{YELLOW}[TTS] No model in {PIPER_MODEL_DIR} and 'requests' not installed.\n"
            f"  Manual download:\n"
            f"    mkdir -p {PIPER_MODEL_DIR}\n"
            f"    wget {_DEFAULT_MODEL_URL} -P {PIPER_MODEL_DIR}/\n"
            f"    wget {_DEFAULT_CONFIG_URL} -P {PIPER_MODEL_DIR}/{RESET}"
        )
        return None

    def _scan_model_dir(self) -> str | None:
        """Return the first .onnx file found in PIPER_MODEL_DIR."""
        for fn in sorted(PIPER_MODEL_DIR.iterdir()):
            if fn.suffix == ".onnx" and fn.is_file():
                return str(fn)
        return None

    def _download_default_model(self) -> str | None:
        """Download en_US-lessac-medium from HuggingFace (requires requests)."""
        model_name  = f"{DEFAULT_VOICE}.onnx"
        config_name = f"{DEFAULT_VOICE}.onnx.json"
        model_path  = PIPER_MODEL_DIR / model_name
        config_path = PIPER_MODEL_DIR / config_name
        try:
            for url, dest in [(_DEFAULT_MODEL_URL,  model_path),
                               (_DEFAULT_CONFIG_URL, config_path)]:
                print(f"{CYAN}[TTS] Downloading {dest.name} …{RESET}")
                r = _requests.get(url, stream=True, timeout=120)
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=32768):
                        fh.write(chunk)
            print(f"{GREEN}[TTS] ✓ Model download complete.{RESET}")
            return str(model_path)
        except Exception as exc:
            print(f"{YELLOW}[TTS] Auto-download failed: {exc}{RESET}")
            for p in (model_path, config_path):
                if p.exists():
                    p.unlink(missing_ok=True)
            return None

    # ── Voice URL helpers for arbitrary voice names ───────────────────────

    def _voice_url_from_name(self, voice_name: str) -> tuple[str, str]:
        """Build HuggingFace URLs from a voice name like en_US-lessac-medium."""
        base        = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
        parts       = voice_name.split("-")
        lang_region = parts[0]
        quality     = parts[-1]
        voice       = "-".join(parts[1:-1])
        lang        = lang_region.split("_")[0]
        path        = f"{base}/{lang}/{lang_region}/{voice}/{quality}/{voice_name}"
        return f"{path}.onnx", f"{path}.onnx.json"

    def change_voice(self, voice_name: str) -> bool:
        """Switch to a different Piper voice at runtime (downloads if needed)."""
        if not voice_name or voice_name == self.VOICE_MODEL:
            return True
        print(f"{CYAN}[TTS] Changing voice to: {voice_name}{RESET}")
        model_path  = PIPER_MODEL_DIR / f"{voice_name}.onnx"
        config_path = PIPER_MODEL_DIR / f"{voice_name}.onnx.json"
        if not model_path.exists() and HAS_REQUESTS:
            onnx_url, config_url = self._voice_url_from_name(voice_name)
            try:
                for url, dest in [(onnx_url, model_path), (config_url, config_path)]:
                    print(f"{CYAN}[TTS] Downloading {dest.name}…{RESET}")
                    r = _requests.get(url, stream=True, timeout=120)
                    r.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=32768):
                            fh.write(chunk)
            except Exception as exc:
                print(f"{YELLOW}[TTS] Voice download failed: {exc}{RESET}")
                return False
        if not model_path.exists():
            print(f"{YELLOW}[TTS] Model not found for '{voice_name}'.{RESET}")
            return False
        with self._lock:
            try:
                self._engine = PiperVoice.load(str(model_path))
                self.VOICE_MODEL = voice_name
                self.model_path  = str(model_path)
                print(f"{GREEN}[TTS] ✓ Voice changed to: {voice_name}{RESET}")
                return True
            except Exception as exc:
                print(f"{YELLOW}[TTS] Failed to load voice '{voice_name}': {exc}{RESET}")
                return False

    # ── Initialise ────────────────────────────────────────────────────────

    def initialize(self) -> bool:
        """Load the voice model and start the worker thread."""
        # Guard against double-initialisation (e.g. called from both the
        # model preloader thread and VoiceAssistant.initialize()).  A second
        # call would spawn a second worker thread; both threads then compete
        # to drive sounddevice concurrently, causing a PortAudio crash.
        if self._running and self._engine is not None:
            return True   # Already initialised — safe to call again.
        if HAS_PIPER_LIB:
            return self._initialize_lib()
        if HAS_PIPER_EXE_DEPS:
            return self._initialize_exe()
        print(
            f"{YELLOW}[TTS] Neither piper-tts library nor executable deps are available.\n"
            f"  Install: pip install piper-tts sounddevice numpy{RESET}"
        )
        return False

    def _initialize_lib(self) -> bool:
        """Initialise using the Python piper-tts library."""
        print(f"{CYAN}[TTS] Initializing Piper TTS (Python library)…{RESET}")
        try:
            # Try to read the voice from settings store if available
            try:
                from core.settings_store import settings as _s
                saved = _s.get("tts.voice", "")
                if saved:
                    self.VOICE_MODEL = saved
            except Exception:
                pass

            model_path = self._find_or_download_model()
            if not model_path:
                print(f"{YELLOW}[TTS] No .onnx model available — TTS disabled.{RESET}")
                self.available = False
                return False

            self._engine    = PiperVoice.load(model_path)
            self.model_path = model_path
            self._start_worker()
            print(f"{GREEN}[TTS] ✓ Piper TTS ready ({Path(model_path).name}){RESET}")
            return True
        except Exception as exc:
            print(f"{YELLOW}[TTS] Library initialization error: {exc}{RESET}")
            import traceback
            traceback.print_exc()
            return False

    def _initialize_exe(self) -> bool:
        """Fallback: initialise using the pre-built Piper executable (Windows)."""
        print(f"{CYAN}[TTS] Initializing Piper TTS (executable fallback)…{RESET}")
        try:
            self.piper_exe = self._download_piper_executable()
            if not self.piper_exe:
                print(f"{YELLOW}[TTS] Could not obtain Piper executable.{RESET}")
                return False
            self.model_path = self._download_model_exe()
            if not self.model_path:
                print(f"{YELLOW}[TTS] No voice model found for executable mode.{RESET}")
                return False
            self._start_worker()
            print(f"{GREEN}[TTS] ✓ Piper TTS ready (executable mode){RESET}")
            return True
        except Exception as exc:
            print(f"{YELLOW}[TTS] Executable init error: {exc}{RESET}")
            return False

    def _start_worker(self):
        # Prevent creating a second worker thread if one is already alive.
        # This is the critical guard that stops the double-init crash:
        # two concurrent calls to sd.play() on Windows cause a PortAudio
        # segfault that takes down the entire Python process.
        if self._running and self._worker_thread and self._worker_thread.is_alive():
            return
        self._running       = True
        self._worker_thread = threading.Thread(target=self._speech_worker, daemon=True, name="TTS-Worker")
        self._worker_thread.start()

    # ── Speech worker ─────────────────────────────────────────────────────

    def _speech_worker(self):
        """Background thread: plays sentences from the queue."""
        while self._running:
            try:
                text = self._speech_queue.get(timeout=0.5)
                if text is None:
                    break
                if not self.muted:
                    if HAS_PIPER_LIB and self._engine:
                        self._speak_lib(text)
                    elif self.piper_exe:
                        self._speak_exe(text)
                self._speech_queue.task_done()
            except queue.Empty:
                continue

    def _speak_lib(self, text: str):
        """Synthesise via Python library and play with sounddevice.

        Two-lock design:
          self._lock      — serialises ONNX inference (one synthesis at a time)
          self._play_lock — serialises sounddevice playback (one play at a time)

        Keeping these separate means the NEXT sentence can be synthesised
        while the CURRENT one is still playing, but two sd.play() calls can
        never overlap.  Concurrent sd.play() on Windows causes PortAudio to
        corrupt its internal state and segfault the Python process — which is
        what was crashing Plia when TTS started reading a story.

        Text chunking: ONNX Runtime can segfault on strings longer than
        ~400 characters.  Any long input is split at sentence boundaries
        (then hard-split at _MAX_CHARS if needed) before synthesis.
        """
        if not text.strip():
            return

        # ── Split long text into safe chunks ─────────────────────────────
        if len(text) <= self._MAX_CHARS:
            chunks = [text]
        else:
            raw_parts = re.split(r'(?<=[.!?])\s+', text.strip())
            chunks, current = [], ""
            for part in raw_parts:
                if len(current) + len(part) + 1 <= self._MAX_CHARS:
                    current = (current + " " + part).strip() if current else part
                else:
                    if current:
                        chunks.append(current)
                    while len(part) > self._MAX_CHARS:
                        chunks.append(part[:self._MAX_CHARS])
                        part = part[self._MAX_CHARS:]
                    current = part
            if current:
                chunks.append(current)

        for chunk in chunks:
            if chunk.strip():
                self._speak_chunk(chunk)

    def _speak_chunk(self, text: str):
        """Synthesise one safe-length chunk and play it serially."""
        try:
            # ── Synthesis (serialised by _lock) ──────────────────────────
            with self._lock:
                if not self._engine:
                    return
                if HAS_SYNTHESIS_CONFIG:
                    # NEW API: synthesize_wav() + SynthesisConfig
                    syn_config = _SynthesisConfig(
                        length_scale=max(0.5, min(2.0, self.length_scale)),
                        noise_scale=0.667,
                        noise_w_scale=0.8,
                    )
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as wf:
                        _sr = getattr(
                            getattr(self._engine, "config", None),
                            "sample_rate", 22050
                        )
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(_sr)
                        self._engine.synthesize_wav(text, wf, syn_config=syn_config)
                    buf.seek(0)
                    with wave.open(buf, "rb") as wf:
                        n_channels = wf.getnchannels()
                        samplerate = wf.getframerate()
                        raw_pcm    = wf.readframes(wf.getnframes())
                else:
                    # OLD API: synthesize(text, wav_file) — no kwargs
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as wf:
                        _sr = getattr(
                            getattr(self._engine, "config", None),
                            "sample_rate", 22050
                        )
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(_sr)
                        self._engine.synthesize(text, wf)
                    buf.seek(0)
                    with wave.open(buf, "rb") as wf:
                        n_channels = wf.getnchannels()
                        samplerate = wf.getframerate()
                        raw_pcm    = wf.readframes(wf.getnframes())

            # ── Convert int16 PCM → float32 ───────────────────────────────
            audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
            audio /= 32768.0
            audio = audio.reshape(-1, n_channels)   # always 2-D for sounddevice
            audio = np.clip(audio * self.volume, -1.0, 1.0)

            # ── Playback (serialised by _play_lock) ───────────────────────
            # This is the critical fix: only ONE sd.play()+sd.wait() pair
            # can run at a time across ALL threads.
            with self._play_lock:
                sd.play(audio, samplerate=samplerate)
                sd.wait()

        except Exception as exc:
            print(f"{YELLOW}[TTS] speak error: {exc}{RESET}")

    def _speak_exe(self, text: str):
        """Synthesise via Piper executable and play with sounddevice."""
        if not self.piper_exe or not self.model_path or not text.strip():
            return
        try:
            import subprocess
            cmd = [self.piper_exe, "--model", self.model_path, "--output-raw"]
            self.current_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            stdout, stderr = self.current_process.communicate(
                input=text.encode("utf-8"), timeout=30
            )
            self.current_process = None
            if stdout:
                audio = np.frombuffer(stdout, dtype=np.int16).astype(np.float32)
                audio /= 32768.0
                audio  = np.clip(audio * self.volume, -1.0, 1.0)
                sd.play(audio, samplerate=22050, blocking=True)
        except Exception as exc:
            print(f"{YELLOW}[TTS] exe speak error: {exc}{RESET}")
            self.current_process = None

    # ── Executable helpers (fallback only) ───────────────────────────────

    def _download_piper_executable(self) -> str | None:
        exe_dir = _EXE_DIR / "piper_windows"
        exe     = exe_dir / "piper.exe"
        if exe.exists():
            return str(exe)
        if not HAS_REQUESTS:
            return None
        print(f"{CYAN}[TTS] Downloading Piper executable…{RESET}")
        try:
            import zipfile
            import subprocess
            r = _requests.get(_PIPER_RELEASE_URL, stream=True, timeout=120)
            r.raise_for_status()
            zip_data = io.BytesIO(b"".join(r.iter_content(8192)))
            exe_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_data) as zf:
                for member in zf.namelist():
                    if member.startswith("piper/"):
                        target = exe_dir / member[6:]
                        if member.endswith("/"):
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(zf.read(member))
            print(f"{GREEN}[TTS] ✓ Piper executable ready{RESET}")
            return str(exe)
        except Exception as exc:
            print(f"{YELLOW}[TTS] Executable download failed: {exc}{RESET}")
            return None

    def _download_model_exe(self) -> str | None:
        """Download voice model for executable mode (separate folder)."""
        models_dir  = _EXE_DIR / "voices"
        model_path  = models_dir / f"{self.VOICE_MODEL}.onnx"
        config_path = models_dir / f"{self.VOICE_MODEL}.onnx.json"
        if model_path.exists():
            return str(model_path)
        if not HAS_REQUESTS:
            return None
        onnx_url, cfg_url = self._voice_url_from_name(self.VOICE_MODEL)
        models_dir.mkdir(parents=True, exist_ok=True)
        try:
            for url, dest in [(onnx_url, model_path), (cfg_url, config_path)]:
                print(f"{CYAN}[TTS] Downloading {dest.name}…{RESET}")
                r = _requests.get(url, stream=True, timeout=120)
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(32768):
                        fh.write(chunk)
            return str(model_path)
        except Exception as exc:
            print(f"{YELLOW}[TTS] Model download failed: {exc}{RESET}")
            return None

    # ── Public API (unchanged from previous PiperTTS) ────────────────────

    def queue_sentence(self, sentence: str):
        """Enqueue a sentence for async playback."""
        if self.enabled and sentence.strip():
            self._speech_queue.put(sentence)

    def stop(self):
        """Interrupt current speech and clear the queue."""
        with self._speech_queue.mutex:
            self._speech_queue.queue.clear()
        # sd.stop() is safe to call from any thread — it signals PortAudio
        # to stop the current stream, which causes sd.wait() to return in
        # the worker thread.  The _play_lock is NOT acquired here because
        # stop() must return immediately, not block.
        try:
            sd.stop()
        except Exception:
            pass
        if self.current_process:
            try:
                self.current_process.kill()
            except Exception:
                pass

    def wait_for_completion(self):
        """Block until all queued sentences have been spoken."""
        if self.enabled:
            self._speech_queue.join()

    def toggle(self, enable: bool) -> bool:
        """Enable or disable TTS. Initialises on first enable."""
        if enable and not self._running:
            if self.initialize():
                self.enabled = True
                return True
            return False
        self.enabled = enable
        return True

    def toggle_mute(self) -> bool:
        """Toggle mute state; returns the new muted value."""
        self.muted = not self.muted
        return self.muted

    def shutdown(self):
        """Clean up resources."""
        self._running = False
        self.stop()
        self._speech_queue.put(None)


# Backwards-compatible alias
PiperTTS = VoiceEngine

# ── Module-level singleton ────────────────────────────────────────────────
tts = VoiceEngine()
