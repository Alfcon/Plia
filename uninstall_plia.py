#!/usr/bin/env python3
"""
Plia Uninstaller
================
Safely removes Plia (Pocket Local Intelligent Assistant) and optionally its
prerequisite software (Python 3.11+, Miniconda, Ollama, Git) on Windows.

Design notes
------------
* The GUI is tkinter-only so it has zero external dependencies and survives
  the uninstallation of Plia's Python environment.
* Plia, user data, caches and the 'plia' conda environment are removed
  in-process by this script.
* Prerequisite software (Python / Miniconda / Ollama / Git) is removed by a
  *deferred* batch file that this script writes to %TEMP% and launches
  detached. The deferred batch runs AFTER this Python process exits, which
  avoids the "Python cannot uninstall itself while running" problem.
* Every action is logged to ~/plia_uninstall_<timestamp>.log.

Author: Alf     Version: 1.0.0     Platform: Windows only
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------- Guards
if sys.platform != "win32":
    sys.stderr.write("Plia Uninstaller is Windows-only.\n")
    sys.exit(1)

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
except ImportError:
    sys.stderr.write(
        "tkinter is required for the GUI but is not installed.\n"
        "Reinstall Python with the 'tcl/tk and IDLE' optional feature enabled.\n"
    )
    sys.exit(1)

import winreg  # noqa: E402 — safe after the win32 guard


# ------------------------------------------------------------------ Paths
APP_TITLE   = "Plia Uninstaller"
APP_VERSION = "1.0.0"

USER_HOME       = Path(os.path.expanduser("~"))
PLIA_ROOT       = Path(r"C:\Plia")
PLIA_USER_DATA  = USER_HOME / ".plia_ai"
OLLAMA_DOTDIR   = USER_HOME / ".ollama"
HF_CACHE        = USER_HOME / ".cache" / "huggingface"

_LOCALAPPDATA   = Path(
    os.environ.get("LOCALAPPDATA", str(USER_HOME / "AppData" / "Local"))
)
OLLAMA_LOGS     = _LOCALAPPDATA / "Ollama"
OLLAMA_PROGRAMS = _LOCALAPPDATA / "Programs" / "Ollama"

LOG_FILE = USER_HOME / f"plia_uninstall_{datetime.now():%Y%m%d_%H%M%S}.log"


# ------------------------------------------------------------------ Helpers
def is_admin() -> bool:
    """Return True if the current process has administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """Relaunch this script with administrator privileges via UAC."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    sys.exit(0)


def run_cmd(cmd: str, timeout: int = 300) -> tuple[int, str, str]:
    """Run a shell command; return (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return (
            res.returncode,
            (res.stdout or "").strip(),
            (res.stderr or "").strip(),
        )
    except subprocess.TimeoutExpired:
        return -1, "", f"Timeout after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def kill_process(name: str) -> None:
    """Best-effort terminate a named process, silent on failure."""
    run_cmd(f'taskkill /F /IM "{name}" /T', timeout=15)


def safe_rmtree(path: Path) -> tuple[bool, str]:
    """
    Remove a directory tree tolerating read-only / permission errors.
    Returns (ok, message).
    """
    if not path.exists():
        return True, f"{path} does not exist (skipped)"

    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, 0o777)
            func(p)
        except Exception:
            pass

    try:
        shutil.rmtree(path, onerror=_onerror)
    except Exception as e:
        return (not path.exists()), f"Partial removal of {path}: {e}"
    return (not path.exists()), f"Removed {path}"


def find_registry_uninstallers(name_substring: str) -> list[tuple[str, str]]:
    """Find apps in the Windows uninstall registry by DisplayName substring."""
    matches: list[tuple[str, str]] = []
    hives = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    needle = name_substring.lower()
    for hive, path in hives:
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                    i += 1
                except OSError:
                    break
                try:
                    k = winreg.OpenKey(root, sub)
                    try:
                        name, _ = winreg.QueryValueEx(k, "DisplayName")
                    except OSError:
                        winreg.CloseKey(k)
                        continue
                    if needle in str(name).lower():
                        unin = None
                        for value_name in ("QuietUninstallString",
                                           "UninstallString"):
                            try:
                                unin, _ = winreg.QueryValueEx(k, value_name)
                                break
                            except OSError:
                                pass
                        if unin:
                            matches.append((str(name), str(unin)))
                    winreg.CloseKey(k)
                except OSError:
                    continue
        finally:
            winreg.CloseKey(root)
    seen = set()
    deduped: list[tuple[str, str]] = []
    for n, u in matches:
        if u not in seen:
            seen.add(u)
            deduped.append((n, u))
    return deduped


# ================================================================== Tasks
# In-process task functions. Each returns (ok: bool, message: str).

def task_stop_processes() -> tuple[bool, str]:
    for proc in (
        "plia.exe", "pliaw.exe",
        "ollama app.exe", "ollama.exe", "ollama_llama_server.exe",
        "piper.exe",
    ):
        kill_process(proc)
    time.sleep(1.0)
    return True, "Terminated Plia / Ollama / Piper processes"


def task_remove_plia_folder() -> tuple[bool, str]:
    return safe_rmtree(PLIA_ROOT)


def task_remove_plia_user_data() -> tuple[bool, str]:
    return safe_rmtree(PLIA_USER_DATA)


def task_remove_plia_conda_env() -> tuple[bool, str]:
    rc, _, err = run_cmd("conda env remove -n plia -y", timeout=180)
    if rc == 0:
        return True, "Removed conda environment 'plia'"
    candidates = [
        USER_HOME / "miniconda3" / "Scripts" / "conda.exe",
        USER_HOME / "Miniconda3" / "Scripts" / "conda.exe",
        Path(r"C:\ProgramData\miniconda3\Scripts\conda.exe"),
        Path(r"C:\ProgramData\Miniconda3\Scripts\conda.exe"),
    ]
    for c in candidates:
        if c.exists():
            rc, _, err = run_cmd(f'"{c}" env remove -n plia -y', timeout=180)
            if rc == 0:
                return True, f"Removed conda environment 'plia' (via {c})"
    return False, (
        f"Could not remove 'plia' conda env "
        f"(conda not found or env missing): {err or '-'}"
    )


def task_remove_ollama_models() -> tuple[bool, str]:
    return safe_rmtree(OLLAMA_DOTDIR)


def task_remove_hf_cache() -> tuple[bool, str]:
    return safe_rmtree(HF_CACHE)


# ================================================================= Deferred
def build_deferred_batch(selected: dict) -> str:
    """
    Build the text of a .bat file that uninstalls prerequisite software
    AFTER this Python process exits. Verified silent flags:

      Ollama  : winget --silent  |  Inno Setup unins000.exe /VERYSILENT
      Git     : winget --silent  |  "%ProgramFiles%\\Git\\unins000.exe" /VERYSILENT
      Miniconda: Uninstall-Miniconda3.exe /S
      Python  : python-X.Y.exe /uninstall /quiet  (via winget by default)
    """
    L: list[str] = [
        "@echo off",
        "REM === Plia Uninstaller - deferred prerequisite removal ===",
        "setlocal enableextensions",
        f'set "LOGFILE={LOG_FILE}"',
        'echo. >> "%LOGFILE%"',
        'echo [%date% %time%] Deferred uninstall batch started. >> "%LOGFILE%"',
        "",
        "REM Let the Python GUI exit cleanly before touching anything.",
        "timeout /t 3 /nobreak >nul",
        "",
    ]

    if selected.get("ollama"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Ollama === >> "%LOGFILE%"',
            'echo Uninstalling Ollama...',
            'taskkill /F /IM ollama.exe /T >nul 2>&1',
            'taskkill /F /IM "ollama app.exe" /T >nul 2>&1',
            'taskkill /F /IM ollama_llama_server.exe /T >nul 2>&1',
            'winget uninstall --id Ollama.Ollama --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            f'if exist "{OLLAMA_PROGRAMS / "unins000.exe"}" '
            f'start /wait "" "{OLLAMA_PROGRAMS / "unins000.exe"}" '
            '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
            f'if exist "{OLLAMA_PROGRAMS}" rmdir /S /Q "{OLLAMA_PROGRAMS}"',
            f'if exist "{OLLAMA_LOGS}" rmdir /S /Q "{OLLAMA_LOGS}"',
            "",
        ]

    if selected.get("git"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Git for Windows === >> "%LOGFILE%"',
            'echo Uninstalling Git for Windows...',
            'winget uninstall --id Git.Git --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            'if exist "%ProgramFiles%\\Git\\unins000.exe" '
            'start /wait "" "%ProgramFiles%\\Git\\unins000.exe" '
            '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
            'if exist "%ProgramFiles(x86)%\\Git\\unins000.exe" '
            'start /wait "" "%ProgramFiles(x86)%\\Git\\unins000.exe" '
            '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
            "",
        ]

    if selected.get("miniconda"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Miniconda === >> "%LOGFILE%"',
            'echo Uninstalling Miniconda...',
            f'if exist "{USER_HOME / "miniconda3" / "Uninstall-Miniconda3.exe"}" '
            f'start /wait "" '
            f'"{USER_HOME / "miniconda3" / "Uninstall-Miniconda3.exe"}" '
            '/S /RemoveCaches=1 /RemoveConfigFiles=user /RemoveUserData=1',
            f'if exist "{USER_HOME / "Miniconda3" / "Uninstall-Miniconda3.exe"}" '
            f'start /wait "" '
            f'"{USER_HOME / "Miniconda3" / "Uninstall-Miniconda3.exe"}" '
            '/S /RemoveCaches=1 /RemoveConfigFiles=user /RemoveUserData=1',
            'if exist "C:\\ProgramData\\miniconda3\\Uninstall-Miniconda3.exe" '
            'start /wait "" '
            '"C:\\ProgramData\\miniconda3\\Uninstall-Miniconda3.exe" /S',
            'if exist "C:\\ProgramData\\Miniconda3\\Uninstall-Miniconda3.exe" '
            'start /wait "" '
            '"C:\\ProgramData\\Miniconda3\\Uninstall-Miniconda3.exe" /S',
            'winget uninstall --id Anaconda.Miniconda3 --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            "",
        ]

    if selected.get("python"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Python 3.11 / 3.12 / 3.13 / 3.14 '
            '=== >> "%LOGFILE%"',
            'echo Uninstalling Python...',
            'for %%V in (3.11 3.12 3.13 3.14) do '
            'winget uninstall --id Python.Python.%%V --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            'winget uninstall --id Python.Launcher --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            "",
        ]

    L += [
        "",
        'echo. >> "%LOGFILE%"',
        'echo [%date% %time%] Deferred uninstall batch finished. '
        '>> "%LOGFILE%"',
        "",
        'echo.',
        'echo ============================================',
        'echo   Plia uninstall complete.',
        'echo ============================================',
        'echo.',
        'echo Log file: %LOGFILE%',
        'echo.',
        'pause',
        "",
        "REM Self-delete this batch on exit.",
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(L) + "\r\n"


# =================================================================== GUI
class UninstallerApp(tk.Tk):
    """
    CHOICES layout: list of tuples
        (key, label, default_checked, description, runner)
      runner == callable  -> in-process task (ok, msg)
      runner is None      -> deferred batch handles it
    """
    CHOICES = [
        ("plia_files",     "Plia program folder  (C:\\Plia)",
         True,
         "Deletes the main Plia installation directory.",
         task_remove_plia_folder),
        ("plia_user_data", "Plia user data  (.plia_ai in your user profile)",
         True,
         "Deletes memory.json, notes.json, reminders.json, settings.json, "
         "agents, TTS models, etc.",
         task_remove_plia_user_data),
        ("plia_conda_env", "Plia conda environment  ('plia')",
         True,
         "Removes the 'plia' conda env if one exists.",
         task_remove_plia_conda_env),
        ("ollama_models",  "Ollama downloaded models  (~/.ollama)",
         False,
         "Deletes all LLM weights pulled via Ollama. Can be many GB.",
         task_remove_ollama_models),
        ("hf_cache",       "HuggingFace cache  (~/.cache/huggingface)",
         False,
         "Deletes Whisper / Piper / transformer models pulled via "
         "huggingface_hub.",
         task_remove_hf_cache),
        ("ollama",         "Ollama application",
         False,
         "Uninstalls the Ollama desktop app via its own uninstaller.",
         None),
        ("miniconda",      "Miniconda (conda)",
         False,
         "Uninstalls Miniconda. WARNING: removes every conda env you have.",
         None),
        ("python",         "Python 3.11 / 3.12 / 3.13 / 3.14",
         False,
         "Uninstalls all matching Python versions installed from python.org.",
         None),
        ("git",            "Git for Windows",
         False,
         "Uninstalls Git for Windows.",
         None),
    ]

    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}   v{APP_VERSION}")
        self.geometry("780x720")
        self.minsize(680, 600)
        try:
            ttk.Style(self).theme_use("vista")
        except tk.TclError:
            pass

        self._vars: dict[str, tk.BooleanVar] = {}
        self._running = False
        self._lookup = {c[0]: c for c in self.CHOICES}
        self._build_ui()

    # ----------------------------------------------------------- layout
    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        header = ttk.Frame(self)
        header.pack(fill="x", **pad)
        ttk.Label(
            header,
            text="Plia Uninstaller",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Tick what you want to remove and click Uninstall. "
                "Prerequisites are UNCHECKED by default because other "
                "applications may depend on them."
            ),
            wraplength=740,
            foreground="#555",
        ).pack(anchor="w", pady=(4, 0))

        plia_frame = ttk.LabelFrame(self, text="  Plia application  ",
                                    padding=10)
        plia_frame.pack(fill="x", **pad)
        self._add_choices(
            plia_frame, ("plia_files", "plia_user_data", "plia_conda_env")
        )

        cache_frame = ttk.LabelFrame(self, text="  Related caches & models  ",
                                     padding=10)
        cache_frame.pack(fill="x", **pad)
        self._add_choices(cache_frame, ("ollama_models", "hf_cache"))

        prereq_frame = ttk.LabelFrame(
            self, text="  Prerequisite software (optional)  ", padding=10
        )
        prereq_frame.pack(fill="x", **pad)
        ttk.Label(
            prereq_frame,
            text="⚠  These may be used by other applications. "
                 "Uninstall only if you are sure.",
            foreground="#b45309",
            wraplength=720,
        ).pack(anchor="w", pady=(0, 6))
        self._add_choices(
            prereq_frame, ("ollama", "miniconda", "python", "git")
        )

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="Select all",
                   command=self._select_all).pack(side="left")
        ttk.Button(btns, text="Deselect all",
                   command=self._deselect_all).pack(side="left", padx=(6, 0))
        self._uninstall_btn = ttk.Button(
            btns, text="Uninstall", command=self._on_uninstall_click
        )
        self._uninstall_btn.pack(side="right")
        ttk.Button(btns, text="Close",
                   command=self.destroy).pack(side="right", padx=(0, 6))

        log_frame = ttk.LabelFrame(self, text="  Progress log  ", padding=6)
        log_frame.pack(fill="both", expand=True, **pad)
        self._log = scrolledtext.ScrolledText(
            log_frame, height=12, font=("Consolas", 9),
            bg="#1e1e1e", fg="#dcdcdc", insertbackground="#dcdcdc",
            state="disabled",
        )
        self._log.pack(fill="both", expand=True)

    def _add_choices(self, parent, keys):
        for key in keys:
            _, label, default, desc, _ = self._lookup[key]
            var = tk.BooleanVar(value=default)
            self._vars[key] = var
            row = ttk.Frame(parent)
            row.pack(fill="x", anchor="w", pady=2)
            ttk.Checkbutton(row, text=label, variable=var).pack(
                side="left", anchor="w"
            )
            ttk.Label(
                row, text=f"  —  {desc}",
                foreground="#777", font=("Segoe UI", 8),
            ).pack(side="left", anchor="w")

    def _select_all(self):
        for v in self._vars.values():
            v.set(True)

    def _deselect_all(self):
        for v in self._vars.values():
            v.set(False)

    # ----------------------------------------------------------- logging
    def log(self, msg: str, level: str = "INFO") -> None:
        line = f"[{datetime.now():%H:%M:%S}] [{level}] {msg}"
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

        def _append():
            self._log.configure(state="normal")
            self._log.insert("end", line + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")

        try:
            self.after(0, _append)
        except Exception:
            pass

    # ----------------------------------------------------------- actions
    def _on_uninstall_click(self) -> None:
        if self._running:
            return
        selected = {k: v.get() for k, v in self._vars.items()}
        if not any(selected.values()):
            messagebox.showinfo(
                APP_TITLE,
                "Nothing selected — tick at least one item.",
            )
            return

        items = []
        for key, label, _, _, _ in self.CHOICES:
            if selected[key]:
                items.append(f"  • {label}")
        prereq = any(
            selected[k] for k in ("ollama", "miniconda", "python", "git")
        )
        msg = (
            "This will permanently remove:\n\n"
            + "\n".join(items)
            + "\n\nThis action cannot be undone."
        )
        if prereq:
            msg += (
                "\n\nPrerequisite uninstallers will run in a separate "
                "console window AFTER this window closes."
            )
        msg += "\n\nContinue?"

        if not messagebox.askyesno(APP_TITLE, msg, icon="warning"):
            return

        self._running = True
        self._uninstall_btn.configure(state="disabled")
        threading.Thread(
            target=self._run, args=(selected,), daemon=True
        ).start()

    def _run(self, selected: dict) -> None:
        self.log(f"Plia Uninstaller v{APP_VERSION} — session started")
        self.log(f"Log file : {LOG_FILE}")
        self.log(f"Admin    : {is_admin()}")
        self.log("-" * 50)

        self.log("Stopping Plia / Ollama processes...")
        ok, msg = task_stop_processes()
        self.log(msg, "OK" if ok else "WARN")

        for key, label, _, _, runner in self.CHOICES:
            if runner is None or not selected.get(key):
                continue
            self.log(f"-> {label}")
            try:
                ok, msg = runner()
                self.log(msg, "OK" if ok else "WARN")
            except Exception as e:
                self.log(f"{label}: {e}", "ERROR")

        if any(selected.get(k)
               for k in ("ollama", "miniconda", "python", "git")):
            self.log("-" * 50)
            self.log("Preparing deferred prerequisite uninstall...")
            batch_text = build_deferred_batch(selected)
            batch_path = (
                Path(os.environ.get("TEMP", str(USER_HOME)))
                / f"plia_uninstall_deferred_"
                  f"{datetime.now():%Y%m%d_%H%M%S}.bat"
            )
            try:
                batch_path.write_text(batch_text, encoding="utf-8")
                self.log(f"Wrote {batch_path}", "OK")
                DETACHED_PROCESS   = 0x00000008
                CREATE_NEW_CONSOLE = 0x00000010
                subprocess.Popen(
                    ["cmd", "/c", "start", "", str(batch_path)],
                    shell=False,
                    creationflags=DETACHED_PROCESS | CREATE_NEW_CONSOLE,
                    close_fds=True,
                )
                self.log(
                    "Deferred uninstaller launched — it will run in its own "
                    "console after this window closes.",
                    "OK",
                )
            except Exception as e:
                self.log(f"Could not launch deferred batch: {e}", "ERROR")

        self.log("-" * 50)
        self.log("In-process tasks complete.")
        self.log(f"Full log: {LOG_FILE}")

        def _finish():
            self._uninstall_btn.configure(
                state="normal", text="Close", command=self.destroy
            )
            messagebox.showinfo(
                APP_TITLE,
                "Uninstall tasks complete.\n\n"
                "If you selected prerequisite uninstalls (Python, Miniconda, "
                "Ollama, Git), a separate console window will run them "
                "momentarily.\n\n"
                f"Log: {LOG_FILE}",
            )

        self.after(0, _finish)
        self._running = False


# ================================================================== main
def main() -> None:
    if not is_admin():
        try:
            root = tk.Tk()
            root.withdraw()
            confirmed = messagebox.askyesno(
                APP_TITLE,
                "Administrator privileges are required to uninstall system "
                "software.\n\nElevate now?",
                icon="warning",
            )
            root.destroy()
        except Exception:
            confirmed = True
        if confirmed:
            relaunch_as_admin()
        else:
            sys.exit(0)
        return

    UninstallerApp().mainloop()


if __name__ == "__main__":
    main()
