"""
Plia - Main Entry Point
"""

# ── Logging must be configured FIRST — before any other imports ───────────
# This prevents RealtimeSTT (and other libraries) from creating stray log
# files in the project root.  The root logger gets a NullHandler so that
# logging.basicConfig() calls inside third-party libraries become no-ops.
# The specific 'realtimestt' logger is also pre-configured here as a
# belt-and-braces measure (stt.py does the same at module level, but
# configuring it early in main.py ensures it is in place before any
# background thread imports the library).
import logging
import os as _os

def _configure_logging() -> None:
    """
    Set up Plia's logging before any library imports.

    - Creates  Plia/log/  if it does not exist.
    - Adds a NullHandler to the root logger so that third-party
      logging.basicConfig() calls are suppressed (they are no-ops when
      the root logger already has at least one handler).
    - Redirects the 'realtimestt' logger to  Plia/log/realtimesst.log
      so RealtimeSTT no longer creates a stray file in the project root.
    - Creates  Plia/log/plia.log  for general WARNING+ application messages.
    """
    _proj_root = _os.path.dirname(_os.path.abspath(__file__))
    _log_dir   = _os.path.join(_proj_root, "log")
    _os.makedirs(_log_dir, exist_ok=True)

    # ── Remove any stray log file left in the project root ────────────────
    # RealtimeSTT (or a previous version of this logging setup) occasionally
    # creates realtimesst.log in the project root instead of log/.
    # This one-time cleanup deletes it on every startup so only the correct
    # log/realtimesst.log remains.
    _stray_log = _os.path.join(_proj_root, "realtimesst.log")
    if _os.path.isfile(_stray_log):
        try:
            _os.remove(_stray_log)
        except OSError:
            pass   # If deletion fails (e.g. locked), silently ignore

    # ── Root logger: NullHandler to suppress spurious basicConfig calls ──
    _root = logging.getLogger()
    if not _root.handlers:
        _root.addHandler(logging.NullHandler())
        _root.setLevel(logging.WARNING)

    _fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── realtimestt → log/realtimesst.log ────────────────────────────────
    _rtstt = logging.getLogger("realtimestt")
    if not any(isinstance(h, logging.FileHandler) for h in _rtstt.handlers):
        _rtstt_fh = logging.FileHandler(
            _os.path.join(_log_dir, "realtimesst.log"),
            mode="a",
            encoding="utf-8",
        )
        _rtstt_fh.setLevel(logging.DEBUG)
        _rtstt_fh.setFormatter(_fmt)
        _rtstt.addHandler(_rtstt_fh)
        _rtstt.setLevel(logging.DEBUG)
        _rtstt.propagate = False   # Stop propagation to root (no console spam)

    # ── plia app logger → log/plia.log ────────────────────────────────────
    _plia = logging.getLogger("plia")
    if not any(isinstance(h, logging.FileHandler) for h in _plia.handlers):
        _plia_fh = logging.FileHandler(
            _os.path.join(_log_dir, "plia.log"),
            mode="a",
            encoding="utf-8",
        )
        _plia_fh.setLevel(logging.WARNING)
        _plia_fh.setFormatter(_fmt)
        _plia.addHandler(_plia_fh)
        _plia.setLevel(logging.WARNING)
        _plia.propagate = False


_configure_logging()   # Must run before any other imports

# ── Standard library + app imports (after logging is configured) ───────────
import os   # public alias — _os above was used only during logging setup
import warnings
import sys
import time
import subprocess
import multiprocessing
import requests

# On Windows the default multiprocessing start method is 'spawn', which means
# each worker process re-imports this module.  freeze_support() must be called
# before any Qt or multiprocessing objects are created so that spawned workers
# (e.g. RealtimeSTT's audio subprocess) exit immediately instead of re-running
# the full application.  Safe to call on all platforms — it's a no-op on Linux/macOS.
multiprocessing.freeze_support()

# Suppress ALL warnings globally before any other imports
warnings.simplefilter("ignore")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon
from gui.app import MainWindow
from qfluentwidgets import qconfig, Theme, SplashScreen


# Resolve Ollama daemon URL + models dir from environment. Doing this up-front
# means a spawned `ollama serve` inherits a deterministic OLLAMA_MODELS rather
# than whatever happens to be in the Plia subprocess env — which is the root
# cause of "I pulled in Plia but `ollama list` doesn't show it".
from core.ollama_paths import (
    resolve_ollama_host,
    resolve_ollama_models_dir,
    diagnose_alignment,
)


def is_ollama_running() -> bool:
    """Check if Ollama is reachable at the resolved OLLAMA_HOST."""
    try:
        r = requests.get(f"{resolve_ollama_host()}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _build_ollama_env() -> dict:
    """
    Return the env dict used when Plia spawns `ollama serve` itself.

    Starts from the current process env, then *explicitly* re-sets
    OLLAMA_MODELS and OLLAMA_HOST so the daemon sees the same values Plia
    resolved — even if the Plia process was launched from a GUI context
    (Windows Start menu, shortcut, etc.) where user env vars sometimes fail
    to propagate to child processes.
    """
    env = os.environ.copy()
    # Force an explicit, resolved OLLAMA_MODELS so `ollama list` in a shell
    # and Plia's `/api/pull` always write to / read from the same directory.
    env["OLLAMA_MODELS"] = str(resolve_ollama_models_dir())
    # Don't override OLLAMA_HOST if the user set it — only set a default.
    env.setdefault("OLLAMA_HOST", resolve_ollama_host().replace("http://", ""))
    return env


def start_ollama():
    """
    Launch Ollama as a background process if it is not already running.

    When Plia spawns the daemon itself, an explicit environment is passed so
    the daemon stores models in the directory Plia resolved for
    ``OLLAMA_MODELS`` — ensuring parity with what ``ollama list`` sees in a
    shell.
    """
    if is_ollama_running():
        print(f"[Plia] Ollama is already running at {resolve_ollama_host()}.")
        _log_alignment()
        return True

    print("[Plia] Ollama not detected — starting Ollama server...")
    print(f"[Plia]   OLLAMA_HOST   = {resolve_ollama_host()}")
    print(f"[Plia]   OLLAMA_MODELS = {resolve_ollama_models_dir()}")
    try:
        spawn_env = _build_ollama_env()
        if sys.platform == "win32":
            subprocess.Popen(
                ["ollama", "serve"],
                env=spawn_env,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                env=spawn_env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Wait up to 15 seconds for Ollama to become ready
        for i in range(15):
            time.sleep(1)
            if is_ollama_running():
                print(f"[Plia] ✓ Ollama started successfully ({i+1}s)")
                _log_alignment()
                return True
            print(f"[Plia] Waiting for Ollama... ({i+1}s)")

        print("[Plia] ⚠ Ollama did not respond in time — continuing anyway.")
        return False

    except FileNotFoundError:
        print("[Plia] ✗ Ollama not found. Make sure Ollama is installed and on your PATH.")
        print("[Plia]   Download from: https://ollama.com/download")
        return False
    except Exception as e:
        print(f"[Plia] ✗ Failed to start Ollama: {e}")
        return False


def _log_alignment() -> None:
    """
    Print the Plia ↔ Ollama storage alignment to the console so the user can
    immediately see whether models pulled from the Model Browser will round-
    trip into ``ollama list`` in a shell. A mismatch usually means the daemon
    was started with a different OLLAMA_MODELS than Plia resolved.
    """
    try:
        d = diagnose_alignment()
        print(f"[Plia]   daemon-reachable={d['daemon_reachable']} "
              f"api-models={d['api_model_count']} "
              f"disk-models={d['disk_model_count']}")
        if d["daemon_reachable"] and not d["matches"]:
            print("[Plia] ⚠ WARNING: daemon model count differs from on-disk "
                  "manifest count.")
            print("[Plia]   This normally means the running Ollama daemon was "
                  "started with a different OLLAMA_MODELS path than Plia "
                  "resolved. Restart Ollama (quit tray app on Windows, then "
                  "let Plia launch it) to realign.")
    except Exception as e:
        # Never let a diagnostic failure block startup.
        print(f"[Plia]   (alignment check skipped: {e})")


if __name__ == "__main__":
    # Start Ollama before anything else loads
    start_ollama()

    app = QApplication(sys.argv)

    # Configure theme
    qconfig.theme = Theme.DARK

    # Set default font
    app.setFont(QFont("Segoe UI", 10))

    # Set app icon to Plia logo
    logo_path = os.path.join(os.path.dirname(__file__), "gui", "assets", "logo.png")
    if os.path.exists(logo_path):
        app.setWindowIcon(QIcon(logo_path))

    # Create SplashScreen
    splash = SplashScreen(QIcon(logo_path) if os.path.exists(logo_path) else None, None)
    splash.setIconSize(QSize(100, 100))
    splash.show()

    # Create main window
    window = MainWindow()

    # Show window maximised (full-screen) then finish splash
    window.showMaximized()
    splash.finish()

    sys.exit(app.exec())
