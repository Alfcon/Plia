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
APP_VERSION = "1.2.0"

USER_HOME       = Path(os.path.expanduser("~"))

# Plia may be installed in several locations depending on how the user set it
# up.  All candidate paths are checked and any that exist will be removed.
PLIA_ROOT_CANDIDATES: list[Path] = [
    Path(r"C:\Plia"),                          # original default
    USER_HOME / "AI projects" / "Plia",        # common user arrangement
    USER_HOME / "AI Projects" / "Plia",        # capitalisation variant
    USER_HOME / "Documents"   / "Plia",
    USER_HOME / "Desktop"     / "Plia",
    USER_HOME / "Plia",
]

# User-data folder name also differs between installs.
PLIA_USER_DATA_CANDIDATES: list[Path] = [
    USER_HOME / ".plia_ai",   # documented default
    USER_HOME / ".plia",      # used in some installs
]

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
    """Remove the Plia program folder from every known candidate location."""
    removed, skipped, failed = [], [], []
    for p in PLIA_ROOT_CANDIDATES:
        if not p.exists():
            skipped.append(str(p))
            continue
        ok, msg = safe_rmtree(p)
        (removed if ok else failed).append(str(p))
    if removed:
        return True, "Removed Plia folder(s): " + "; ".join(removed)
    if failed:
        return False, "Could not fully remove: " + "; ".join(failed)
    return True, "Plia folder not found at any known location (skipped)"


def task_remove_plia_user_data() -> tuple[bool, str]:
    """Remove Plia user-data from every known candidate location."""
    removed, failed = [], []
    for p in PLIA_USER_DATA_CANDIDATES:
        if not p.exists():
            continue
        ok, _ = safe_rmtree(p)
        (removed if ok else failed).append(str(p))
    if removed:
        return True, "Removed Plia user data: " + "; ".join(removed)
    if failed:
        return False, "Could not fully remove user data: " + "; ".join(failed)
    return True, (
        "Plia user data not found at any known location "
        f"({', '.join(str(p) for p in PLIA_USER_DATA_CANDIDATES)}) — skipped"
    )


def _clean_conda_env_registry(env_name: str) -> str:
    """
    Remove a stale 'plia' entry from ~/.conda/environments.txt.

    Conda stores environment paths in this plain-text registry file.  When an
    environment directory was never fully created (e.g. after an aborted Plia
    install), conda still holds the stale reference and raises
    EnvironmentLocationNotFound on every subsequent removal attempt.
    Scrubbing the entry here resolves the warning permanently.

    Returns a short status string for logging.
    """
    envs_txt = USER_HOME / ".conda" / "environments.txt"
    if not envs_txt.exists():
        return "~/.conda/environments.txt not found (nothing to clean)"
    try:
        original = envs_txt.read_text(encoding="utf-8", errors="replace")
        needle   = f"\\envs\\{env_name.lower()}"
        needle2  = f"/envs/{env_name.lower()}"
        lines    = original.splitlines(keepends=True)
        kept     = [
            ln for ln in lines
            if needle not in ln.lower() and needle2 not in ln.lower()
        ]
        if len(kept) == len(lines):
            return f"No '{env_name}' entry found in environments.txt"
        envs_txt.write_text("".join(kept), encoding="utf-8")
        return (
            f"Removed {len(lines) - len(kept)} stale '{env_name}' "
            f"entry from ~/.conda/environments.txt"
        )
    except Exception as exc:
        return f"Could not clean environments.txt: {exc}"


def task_remove_plia_conda_env() -> tuple[bool, str]:
    """
    Remove the 'plia' conda environment.

    Strategy (in order):
      1. Use the conda binary already on PATH.
      2. Search common Miniconda *and* Anaconda install locations for conda.exe
         (fixes the case where Anaconda is installed but not on PATH).
      3. If every conda CLI attempt fails with EnvironmentLocationNotFound
         (the env folder exists but is corrupt / partially installed), fall back
         to deleting the directory directly via safe_rmtree.
    """
    # -- Step 1: system PATH conda -------------------------------------------
    rc, _, err = run_cmd("conda env remove -n plia -y", timeout=180)
    if rc == 0:
        return True, "Removed conda environment 'plia'"
    last_err = err  # preserve; overwritten only on subsequent attempts

    # -- Step 2: locate conda.exe in well-known install directories ----------
    # Covers both Miniconda and full Anaconda Distribution (case-insensitive
    # directory names as seen in the wild on Windows).
    candidates = [
        # Anaconda (user-level)
        USER_HOME / "anaconda3"  / "Scripts" / "conda.exe",
        USER_HOME / "Anaconda3"  / "Scripts" / "conda.exe",
        # Miniconda (user-level)
        USER_HOME / "miniconda3" / "Scripts" / "conda.exe",
        USER_HOME / "Miniconda3" / "Scripts" / "conda.exe",
        # Anaconda / Miniconda (system-wide)
        Path(r"C:\ProgramData\anaconda3\Scripts\conda.exe"),
        Path(r"C:\ProgramData\Anaconda3\Scripts\conda.exe"),
        Path(r"C:\ProgramData\miniconda3\Scripts\conda.exe"),
        Path(r"C:\ProgramData\Miniconda3\Scripts\conda.exe"),
    ]
    for c in candidates:
        if c.exists():
            rc, _, err = run_cmd(f'"{c}" env remove -n plia -y', timeout=180)
            if rc == 0:
                return True, f"Removed conda environment 'plia' (via {c})"
            last_err = err or last_err

    # -- Step 3: direct directory removal ------------------------------------
    # Handles "EnvironmentLocationNotFound: Not a conda environment: <path>"
    # which occurs when the env directory exists but conda cannot parse it
    # (e.g. after a failed/partial Plia install).  In this case the safest
    # recovery is simply deleting the folder.
    env_dirs = [
        USER_HOME / "anaconda3"  / "envs" / "plia",
        USER_HOME / "Anaconda3"  / "envs" / "plia",
        USER_HOME / "miniconda3" / "envs" / "plia",
        USER_HOME / "Miniconda3" / "envs" / "plia",
        Path(r"C:\ProgramData\anaconda3\envs\plia"),
        Path(r"C:\ProgramData\Anaconda3\envs\plia"),
        Path(r"C:\ProgramData\miniconda3\envs\plia"),
        Path(r"C:\ProgramData\Miniconda3\envs\plia"),
    ]
    for env_dir in env_dirs:
        if env_dir.exists():
            ok, msg = safe_rmtree(env_dir)
            if ok:
                return True, (
                    f"Removed conda env directory directly "
                    f"(conda CLI could not parse it): {env_dir}"
                )
            return False, f"Partial removal of conda env directory {env_dir}: {msg}"

    # -- Step 4: scrub the stale conda registry entry ----------------------
    # If we reach here the env directory never existed on disk (partial/aborted
    # install). Clean ~/.conda/environments.txt so conda stops complaining.
    reg_msg = _clean_conda_env_registry("plia")
    return False, (
        f"Could not remove 'plia' conda env "
        f"(conda not found or env missing): {last_err or '-'}. "
        f"Registry cleanup: {reg_msg}"
    )


def task_remove_playwright_browsers() -> tuple[bool, str]:
    """
    Remove Playwright's downloaded browser binaries.

    Two-step strategy:
      1. Try `playwright uninstall --all` — the clean vendor-documented route
         that walks Playwright's registry and removes browser directories.
         Also tries `python -m playwright uninstall --all` as a fallback if
         the playwright.exe shim is not on PATH.
      2. Directly remove %LOCALAPPDATA%\\ms-playwright\\ to catch any leftovers
         (especially important if the CLI is no longer available because
         the plia conda env has already been removed).

    This task is ordered to run BEFORE task_remove_plia_conda_env so the
    playwright CLI is still reachable when step 1 runs.
    """
    pw_path = _LOCALAPPDATA / "ms-playwright"
    cli_msg = ""

    # --- Step 1: CLI route (best effort) ---
    rc, _, _ = run_cmd("playwright uninstall --all", timeout=180)
    if rc == 0:
        cli_msg = "playwright CLI uninstalled browsers"
    else:
        rc2, _, _ = run_cmd("python -m playwright uninstall --all",
                            timeout=180)
        if rc2 == 0:
            cli_msg = "python -m playwright uninstalled browsers"

    # --- Step 2: Remove the browser root directory unconditionally ---
    if not pw_path.exists():
        if cli_msg:
            return True, f"{cli_msg}; {pw_path} already gone"
        return True, f"Playwright browsers not found at {pw_path} (skipped)"

    ok, _ = safe_rmtree(pw_path)
    if ok:
        detail = f"{cli_msg}; directory removed" if cli_msg else \
                 "directory removed (CLI unavailable, used folder delete)"
        return True, f"Removed Playwright browsers: {detail}"
    return False, f"Partial removal of {pw_path}"


def task_remove_ollama_models() -> tuple[bool, str]:
    return safe_rmtree(OLLAMA_DOTDIR)


def task_remove_hf_cache() -> tuple[bool, str]:
    return safe_rmtree(HF_CACHE)


# ================================================================= Deferred
def build_deferred_batch(selected: dict) -> str:
    """
    Build the text of a .bat file that uninstalls prerequisite software
    AFTER this Python process exits.

    For each component the strategy (most reliable → last resort) is:
      1. winget --exact --scope machine   (catches system-wide MSI/Inno installs)
      2. winget --exact                   (user-scope fallback)
      3. Registry-resolved uninstall path (queried NOW by find_registry_uninstallers
         so the concrete path is baked into the batch — no cmd.exe registry
         parsing needed at run time)
      4. Hardcoded Program Files paths    (final safety net)

    :label / goto blocks ensure the component is not uninstalled twice when
    an earlier method already succeeded.

    Verified silent flags:
      Ollama    : winget --silent  |  unins000.exe /VERYSILENT
      Git       : winget --silent  |  unins000.exe /VERYSILENT
      Miniconda : Uninstall-Miniconda3.exe /S
      Python    : winget --silent  (via winget by default)
    """

    # ------------------------------------------------------------------
    # Resolve registry uninstall strings NOW while Python / winreg is live.
    # These concrete paths will be embedded verbatim in the batch file.
    # ------------------------------------------------------------------
    git_entries    = find_registry_uninstallers("git")    if selected.get("git")    else []
    ollama_entries = find_registry_uninstallers("ollama") if selected.get("ollama") else []

    # ------------------------------------------------------------------
    # Helper: turn a list of (DisplayName, UninstallString) pairs into
    # batch lines that run the uninstaller silently and jump to done_label
    # on success.  Handles Inno Setup, NSIS and MSI uninstall strings.
    # ------------------------------------------------------------------
    def _reg_uninstall_lines(
        entries: list[tuple[str, str]],
        done_label: str,
    ) -> list[str]:
        lines: list[str] = []
        for display_name, unin in entries:
            us = unin.strip()
            if us.upper().startswith("MSIEXEC"):
                # MSI product  e.g.  MsiExec.exe /X{GUID}
                # Swap /I → /X and append quiet flags if missing.
                args = us.split(None, 1)[1] if " " in us else ""
                args = args.replace("/I{", "/X{").replace("/i{", "/X{")
                if "/quiet" not in args.lower():
                    args += " /quiet /norestart"
                lines.append(f"REM Registry: {display_name}")
                lines.append(
                    f'start /wait "" MsiExec.exe {args} >> "%LOGFILE%" 2>&1'
                )
                lines.append(f"if not errorlevel 1 goto :{done_label}")
            else:
                # Inno Setup / NSIS / custom EXE
                if us.startswith('"'):
                    exe_end = us.find('"', 1)
                    exe_path = us[1:exe_end]
                else:
                    exe_path = us.split()[0]

                # Skip if the file was already removed (e.g. partial prior run)
                if not Path(exe_path).exists():
                    lines.append(
                        f"REM Skipping (not found on disk at build time): {exe_path}"
                    )
                    continue

                # Inno Setup uninstallers: /VERYSILENT /SUPPRESSMSGBOXES
                # NSIS uninstallers: /S
                extra = (
                    "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
                    if "unins" in exe_path.lower()
                    else "/S"
                )
                lines.append(f"REM Registry: {display_name}")
                lines.append(
                    f'start /wait "" "{exe_path}" {extra} >> "%LOGFILE%" 2>&1'
                )
                lines.append(f"if not errorlevel 1 goto :{done_label}")
        return lines

    L: list[str] = [
        "@echo off",
        "REM === Plia Uninstaller v1.2.0 - deferred prerequisite removal ===",
        "setlocal enableextensions",
        f'set "LOGFILE={LOG_FILE}"',
        'echo. >> "%LOGFILE%"',
        'echo [%date% %time%] Deferred uninstall batch started. >> "%LOGFILE%"',
        "",
        "REM Let the Python GUI exit cleanly before touching anything.",
        "timeout /t 3 /nobreak >nul",
        "",
    ]

    # ------------------------------------------------------------------ Ollama
    if selected.get("ollama"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Ollama === >> "%LOGFILE%"',
            'echo Uninstalling Ollama...',
            'taskkill /F /IM ollama.exe /T >nul 2>&1',
            'taskkill /F /IM "ollama app.exe" /T >nul 2>&1',
            'taskkill /F /IM ollama_llama_server.exe /T >nul 2>&1',
            # 1) winget machine scope
            'winget uninstall --id Ollama.Ollama --exact --scope machine --silent '
            '--accept-source-agreements --disable-interactivity >> "%LOGFILE%" 2>&1',
            'if not errorlevel 1 goto :ollama_done',
            # 2) winget user scope
            'winget uninstall --id Ollama.Ollama --exact --silent '
            '--accept-source-agreements --disable-interactivity >> "%LOGFILE%" 2>&1',
            'if not errorlevel 1 goto :ollama_done',
        ]
        # 3) Registry-resolved path
        L += _reg_uninstall_lines(ollama_entries, "ollama_done")
        # 4) Hardcoded fallback
        L += [
            f'if exist "{OLLAMA_PROGRAMS / "unins000.exe"}" '
            f'start /wait "" "{OLLAMA_PROGRAMS / "unins000.exe"}" '
            '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
            ':ollama_done',
            f'if exist "{OLLAMA_PROGRAMS}" rmdir /S /Q "{OLLAMA_PROGRAMS}"',
            f'if exist "{OLLAMA_LOGS}" rmdir /S /Q "{OLLAMA_LOGS}"',
            '',
        ]

    # ------------------------------------------------------------------ Git
    if selected.get("git"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Git for Windows === >> "%LOGFILE%"',
            'echo Uninstalling Git for Windows...',
            # 1) winget machine scope  — Git is almost always a system-wide install
            'winget uninstall --id Git.Git --exact --scope machine --silent '
            '--accept-source-agreements --disable-interactivity >> "%LOGFILE%" 2>&1',
            'if not errorlevel 1 goto :git_done',
            # 2) winget user scope
            'winget uninstall --id Git.Git --exact --silent '
            '--accept-source-agreements --disable-interactivity >> "%LOGFILE%" 2>&1',
            'if not errorlevel 1 goto :git_done',
        ]
        # 3) Registry-resolved paths (concrete exe baked in at build time)
        L += _reg_uninstall_lines(git_entries, "git_done")
        # 4) Hardcoded fallbacks (Program Files 64-bit and 32-bit)
        L += [
            r'if exist "%ProgramFiles%\Git\unins000.exe" '
            r'start /wait "" "%ProgramFiles%\Git\unins000.exe" '
            '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
            r'if exist "%ProgramFiles(x86)%\Git\unins000.exe" '
            r'start /wait "" "%ProgramFiles(x86)%\Git\unins000.exe" '
            '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART',
            ':git_done',
            '',
        ]

    # ------------------------------------------------------------------ Miniconda / Anaconda
    if selected.get("miniconda"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Miniconda / Anaconda === >> "%LOGFILE%"',
            'echo Uninstalling Miniconda / Anaconda...',
            # ---- user-level Miniconda ----
            f'if exist "{USER_HOME / "miniconda3" / "Uninstall-Miniconda3.exe"}" '
            f'start /wait "" '
            f'"{USER_HOME / "miniconda3" / "Uninstall-Miniconda3.exe"}" '
            '/S /RemoveCaches=1 /RemoveConfigFiles=user /RemoveUserData=1',
            f'if exist "{USER_HOME / "Miniconda3" / "Uninstall-Miniconda3.exe"}" '
            f'start /wait "" '
            f'"{USER_HOME / "Miniconda3" / "Uninstall-Miniconda3.exe"}" '
            '/S /RemoveCaches=1 /RemoveConfigFiles=user /RemoveUserData=1',
            # ---- user-level Anaconda Distribution ----
            f'if exist "{USER_HOME / "anaconda3" / "Uninstall-Anaconda3.exe"}" '
            f'start /wait "" '
            f'"{USER_HOME / "anaconda3" / "Uninstall-Anaconda3.exe"}" /S',
            f'if exist "{USER_HOME / "Anaconda3" / "Uninstall-Anaconda3.exe"}" '
            f'start /wait "" '
            f'"{USER_HOME / "Anaconda3" / "Uninstall-Anaconda3.exe"}" /S',
            # ---- system-wide Miniconda ----
            'if exist "C:\\ProgramData\\miniconda3\\Uninstall-Miniconda3.exe" '
            'start /wait "" '
            '"C:\\ProgramData\\miniconda3\\Uninstall-Miniconda3.exe" /S',
            'if exist "C:\\ProgramData\\Miniconda3\\Uninstall-Miniconda3.exe" '
            'start /wait "" '
            '"C:\\ProgramData\\Miniconda3\\Uninstall-Miniconda3.exe" /S',
            # ---- system-wide Anaconda Distribution ----
            'if exist "C:\\ProgramData\\anaconda3\\Uninstall-Anaconda3.exe" '
            'start /wait "" '
            '"C:\\ProgramData\\anaconda3\\Uninstall-Anaconda3.exe" /S',
            'if exist "C:\\ProgramData\\Anaconda3\\Uninstall-Anaconda3.exe" '
            'start /wait "" '
            '"C:\\ProgramData\\Anaconda3\\Uninstall-Anaconda3.exe" /S',
            # ---- winget fallbacks (covers both Miniconda and Anaconda) ----
            'winget uninstall --id Anaconda.Miniconda3 --exact --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            'winget uninstall --id Anaconda.Anaconda3 --exact --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            "",
        ]

    # ------------------------------------------------------------------ Python
    if selected.get("python"):
        L += [
            'echo. >> "%LOGFILE%"',
            'echo === Uninstalling Python 3.11 / 3.12 / 3.13 / 3.14 '
            '=== >> "%LOGFILE%"',
            'echo Uninstalling Python...',
            'for %%V in (3.11 3.12 3.13 3.14) do '
            'winget uninstall --id Python.Python.%%V --exact --silent '
            '--accept-source-agreements --disable-interactivity '
            '>> "%LOGFILE%" 2>&1',
            'winget uninstall --id Python.Launcher --exact --silent '
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
        ("playwright_browsers",
         "Playwright browsers  (~\\AppData\\Local\\ms-playwright)",
         False,
         "Removes Chromium / Firefox / WebKit binaries pulled by "
         "'playwright install' (~400-600 MB). Tries 'playwright uninstall "
         "--all' first, then folder delete. Runs FIRST so the CLI is still "
         "available before the conda env / venv is removed.",
         task_remove_playwright_browsers),
        ("plia_files",
         "Plia program folder  (C:\\Plia, ~/AI projects/Plia, ...)",
         True,
         "Deletes the main Plia installation directory. Searches multiple "
         "known locations (C:\\Plia, ~/AI projects/Plia, ~/Documents/Plia, "
         "~/Desktop/Plia, ~/Plia) and removes all that exist.",
         task_remove_plia_folder),
        ("plia_user_data",
         "Plia user data  (.plia / .plia_ai in your user profile)",
         True,
         "Deletes memory.json, notes.json, reminders.json, settings.json, "
         "agents, TTS models, etc. Checks both ~/.plia and ~/.plia_ai.",
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
        self._add_choices(
            cache_frame,
            ("playwright_browsers", "ollama_models", "hf_cache"),
        )

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

                # Launch the batch completely detached in a new console.
                # NOTE: DETACHED_PROCESS and CREATE_NEW_CONSOLE are
                # mutually exclusive — combining them causes CreateProcess
                # to fail with WinError 87. We therefore try three routes
                # in order of robustness.
                launched = False
                last_err: Exception | None = None

                # Route 1 — os.startfile: the idiomatic Windows launcher,
                # no creationflags involved, fire-and-forget.
                try:
                    os.startfile(str(batch_path))  # type: ignore[attr-defined]
                    launched = True
                    self.log("Launched via os.startfile", "OK")
                except Exception as e:
                    last_err = e

                # Route 2 — Popen with CREATE_NEW_CONSOLE only.
                if not launched:
                    try:
                        subprocess.Popen(
                            [str(batch_path)],
                            shell=False,
                            creationflags=subprocess.CREATE_NEW_CONSOLE,
                            close_fds=True,
                        )
                        launched = True
                        self.log("Launched via Popen + CREATE_NEW_CONSOLE",
                                 "OK")
                    except Exception as e:
                        last_err = e

                # Route 3 — cmd /c start via shell=True.
                if not launched:
                    try:
                        subprocess.Popen(
                            f'start "" "{batch_path}"',
                            shell=True,
                            close_fds=True,
                        )
                        launched = True
                        self.log("Launched via cmd /c start (shell=True)",
                                 "OK")
                    except Exception as e:
                        last_err = e

                if launched:
                    self.log(
                        "Deferred uninstaller launched — it will run in "
                        "its own console after this window closes.",
                        "OK",
                    )
                else:
                    self.log(
                        f"All launch routes failed (last error: {last_err}). "
                        f"Run the batch manually: {batch_path}",
                        "ERROR",
                    )
            except Exception as e:
                self.log(f"Could not prepare deferred batch: {e}", "ERROR")

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