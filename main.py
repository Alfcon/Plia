"""
Plia - Main Entry Point
"""

import warnings
import sys
import os
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


def is_ollama_running() -> bool:
    """Check if Ollama is already running on localhost:11434."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def start_ollama():
    """
    Launch Ollama as a background process if it is not already running.
    Works on Windows (ollama.exe) and other platforms.
    """
    if is_ollama_running():
        print("[Plia] Ollama is already running.")
        return True

    print("[Plia] Ollama not detected — starting Ollama server...")
    try:
        if sys.platform == "win32":
            # Launch without a console window
            subprocess.Popen(
                ["ollama", "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Wait up to 15 seconds for Ollama to become ready
        for i in range(15):
            time.sleep(1)
            if is_ollama_running():
                print(f"[Plia] ✓ Ollama started successfully ({i+1}s)")
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

    # Show window and finish splash
    window.show()
    splash.finish()

    sys.exit(app.exec())
