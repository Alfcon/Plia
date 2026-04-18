## 🗑️ Uninstallation

Plia ships with a GUI uninstaller (`uninstall_plia.bat` + `uninstall_plia.py`) that lets you tick exactly what you want removed. Prerequisite software (Python, Miniconda, Ollama, Git) is **unchecked by default** because other applications on your machine may depend on it.

### How to run it

1. Place both files in the same folder. `C:\Plia\` is the natural home:
   ```
   C:\Plia\
   ├── uninstall_plia.bat   ← double-click this
   └── uninstall_plia.py
   ```
2. Double-click `uninstall_plia.bat` (or right-click → **Run as administrator**).
3. Accept the UAC prompt. The launcher stages itself to `%TEMP%\plia_uninstall\` and re-launches from there — this lets it delete `C:\Plia\` even when the uninstaller is inside that folder.
4. In the GUI, tick the items you want removed and click **Uninstall**.

### What the GUI offers

| Section | Item | Default |
|---|---|---|
| **Plia application** | Plia program folder (`C:\Plia`) | ✅ checked |
| | Plia user data (`~/.plia_ai`) | ✅ checked |
| | Plia conda environment (`plia`) | ✅ checked |
| **Related caches & models** | Ollama downloaded models (`~/.ollama`) | ⬜ unchecked |
| | HuggingFace cache (`~/.cache/huggingface`) | ⬜ unchecked |
| **Prerequisite software** ⚠ | Ollama application | ⬜ unchecked |
| | Miniconda | ⬜ unchecked |
| | Python 3.11 / 3.12 / 3.13 / 3.14 | ⬜ unchecked |
| | Git for Windows | ⬜ unchecked |

> ⚠ The prerequisite uninstallers are deferred to a separate console window that runs **after** the GUI closes — this avoids the "Python cannot uninstall the Python it is running under" problem. If you tick Python or Miniconda, expect a brief console window to pop up a few seconds after you close the GUI.

### How removal is performed

- **In-process (Python)** — folder deletion (`shutil.rmtree` with a permission-tolerant error handler), process termination (`taskkill /F`), and conda env removal (`conda env remove -n plia -y`).
- **Deferred (batch)** — silent vendor uninstallers with flags verified against each vendor's documentation:
  - **Ollama** — `winget uninstall --id Ollama.Ollama --silent` with fallback to `%LOCALAPPDATA%\Programs\Ollama\unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
  - **Miniconda** — `Uninstall-Miniconda3.exe /S /RemoveCaches=1 /RemoveConfigFiles=user /RemoveUserData=1` (official Anaconda silent-uninstall syntax)
  - **Python** — `winget uninstall --id Python.Python.3.11 … 3.14 --silent` and `Python.Launcher`
  - **Git** — `winget uninstall --id Git.Git --silent` with fallback to `"%ProgramFiles%\Git\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`

### Log file

Every action is timestamped and written to:

```
C:\Users\<YourName>\plia_uninstall_<YYYYMMDD_HHMMSS>.log
```

If anything fails, attach this log when asking for help.

### Requirements

- Windows 10 or 11 (the uninstaller refuses to run on other platforms).
- Python 3.11+ on PATH, with `tkinter` available (standard when installed from python.org with the "tcl/tk and IDLE" option ticked, or via Miniconda/Anaconda).
- Administrator rights (the launcher requests elevation automatically).

### Troubleshooting

| Symptom | Fix |
|---|---|
| "Python 3.11+ is required but was not found on your PATH." | Install Python from [python.org](https://www.python.org/downloads/) with **Add Python to PATH** ticked, or run the `.bat` from an **Anaconda Prompt**. |
| "This Python does not include tkinter." | Reinstall Python with the **tcl/tk and IDLE** optional feature enabled. |
| UAC prompt does not appear and nothing happens | Right-click `uninstall_plia.bat` → **Run as administrator** manually. |
| `C:\Plia` remains after uninstall | A file is in use. Close any Plia-related process (check Task Manager for `python.exe`, `ollama.exe`, `piper.exe`) and re-run the uninstaller. |
| Ollama models folder was not removed | If you changed `OLLAMA_MODELS` to a custom path, delete that directory manually — the uninstaller only cleans the default `~/.ollama` location. |
| Deferred batch window closed before Python finished uninstalling | Re-run the uninstaller — the silent flags are idempotent and safe to run twice. |

### Reinstalling after uninstall

If you remove the prerequisites and later want Plia back, follow the **🚀 Quick Start Guide** above from Step 1 (Miniconda) onward.
