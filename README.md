# 🤖 Plia — Pocket Local Intelligent Assistant

<p align="center">
  <img src="gui/assets/logo.png" alt="Plia Logo" width="120" height="120">
</p>

**Plia** (Pocket Local Intelligent Assistant) is a **fully local, privacy-focused AI desktop assistant** for Windows. It combines a modern Fluent Design GUI with voice control, smart home integration, a daily briefing, autonomous AI agents, and a desktop automation agent — all running on your machine with no cloud dependency and no subscription required for core features.

> 🔒 **Your data stays on your machine.** No API keys required for core functionality. No subscriptions. No data collection.

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🎤 **Voice Control** | Wake word detection ("Jarvis") with natural language commands |
| 💬 **AI Chat** | Streaming chat with local LLMs via Ollama |
| 🤖 **Active Agents** | Build and run autonomous AI agents from chat or GUI |
| 🖥️ **Desktop Agent** | Control Windows applications with natural language |
| 🏠 **Smart Home** | Control TP-Link Kasa smart lights and plugs |
| 📅 **Planner** | Calendar events, alarms, and timers with Google/Outlook sync (optional) |
| 📰 **Daily Briefing** | AI-curated news from Technology, Science, and Top Stories |
| 🌤️ **Weather** | Current weather and hourly forecast with floating overlay |
| 🔍 **Web Search** | Voice or chat-triggered DuckDuckGo search with results browser |
| 🧠 **Model Browser** | Download and manage Ollama models directly from the app |
| 🖥️ **System Monitor** | Real-time CPU, RAM, Disk, and GPU VRAM in the title bar |
| ❓ **Help System** | Voice or button-triggered help panel covering all commands |

---

## 📸 Screenshots

*The application features a Windows 11 Fluent Design aesthetic with full dark mode support.*

---

## 📋 Prerequisites

### Required Software

| Software | Purpose | Download |
|----------|---------|----------|
| **Python 3.11+** | Runtime (3.11 or 3.13 recommended) | [python.org](https://www.python.org/downloads/) or via Miniconda |
| **Miniconda** (recommended) | Python environment manager | [docs.anaconda.com/miniconda](https://docs.anaconda.com/miniconda/) |
| **Ollama** | Local AI model server | [ollama.com/download](https://ollama.com/download) |
| **Git** | Cloning the repository | [git-scm.com](https://git-scm.com/downloads) |

### Hardware Recommendations

| Tier | Specs | Experience |
|------|-------|------------|
| **Minimum** | 8 GB RAM, modern CPU | Functional, CPU inference |
| **Recommended** | 16 GB RAM, NVIDIA GPU 6 GB+ VRAM | Fast responses, GPU inference |
| **Storage** | ~5 GB free | Models + voice data |

> 💡 Plia works on CPU-only machines. A GPU simply makes inference faster.

---

## 🚀 Quick Start Guide

### Step 1 — Install Miniconda (or use your existing Python 3.11+)

1. Download from [docs.anaconda.com/miniconda](https://docs.anaconda.com/miniconda/)
2. Run the installer with default options
3. Open **Anaconda Prompt** (Windows Start menu)

### Step 2 — Install Ollama

1. Download and install from [ollama.com/download](https://ollama.com/download)
2. Ollama starts automatically as a background service after installation

> ✅ No need to start Ollama manually — Plia will detect it or launch it automatically on startup.

### Step 3 — Download an AI Model

Open a terminal and pull your preferred model:

**🔹 Option A: Qwen3 1.7B (Recommended — fast, balanced)**
```bash
ollama pull qwen3:1.7b
```

**🔹 Option B: DeepSeek R1 1.5B (Better reasoning)**
```bash
ollama pull deepseek-r1:1.5b
```

**🔹 Option C: Any other Ollama model**
```bash
ollama pull <model-name>
# Then set RESPONDER_MODEL = "<model-name>" in config.py
```

Verify your model is installed:
```bash
ollama list
```

### Step 4 — Clone & Set Up Plia

```bash
# Clone the repository
git clone https://github.com/Alfcon/Plia.git
cd Plia

# Create and activate a conda environment (recommended)
conda create -n plia python=3.11 -y
conda activate plia

# Install all Python dependencies
pip install -r requirements.txt
```

> ⏱️ First install may take 5–15 minutes — PyTorch and AI packages are large downloads.

### Step 5 — Install the OpenAI Python Library (Required for Agent Builder)

The Agent Builder uses the OpenAI API to power custom agents with internet search capability.
Install it separately:

```bash
pip install openai>=2.0.0
```

> ℹ️ An OpenAI API key is required for agents that use the GPT-4o model.
> Set your key in the Plia **Settings** tab under "OpenAI API Key".
> The core Plia assistant (chat, voice, weather, etc.) does **not** require an OpenAI key.

### Step 6 — Install the DuckDuckGo Search Library

Plia uses the `ddgs` package (the current maintained version of DuckDuckGo search):

```bash
pip install ddgs>=9.13.0
```

> ⚠️ The older `duckduckgo-search` package is deprecated and broken. Always use `ddgs`.

### Step 7 — NVIDIA GPU Setup (Optional but Recommended)

If you have an NVIDIA GPU, install PyTorch with CUDA for significantly faster inference:

```bash
# CUDA 12.4 (RTX 30/40/50 series, GTX 16 series with updated drivers)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

Verify it worked:
```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
```

> 💡 **CPU-only users**: Skip this step. The `requirements.txt` torch lines are commented out by default, so CPU PyTorch will be installed automatically via the `transformers` dependency.

### Step 8 — Install Playwright Browser Binaries

Playwright is used for the web search results browser panel. After pip install, run:

```bash
playwright install
```

> You only need to do this once. It downloads ~300 MB of browser binaries.

### Step 9 — Run Plia

```bash
python main.py
```

🎉 **That's it!** Plia will launch with a splash screen while models preload in the background.

---

## 📦 Complete Dependencies Reference

The full `requirements.txt` installs these packages. This table shows what each is for:

| Package | Purpose |
|---------|---------|
| `PySide6>=6.10.0` | Qt GUI framework |
| `PySide6-Fluent-Widgets>=1.10.0` | Windows 11 Fluent Design UI components |
| `transformers>=4.57.0` | Hugging Face — router model inference |
| `accelerate>=1.12.0` | Optimised model loading |
| `safetensors>=0.7.0` | Fast model weight loading |
| `piper-tts>=1.4.0` | Local text-to-speech (Piper) |
| `sounddevice>=0.5.0` | Audio playback |
| `soundfile>=0.13.0` | Audio file I/O |
| `numpy>=2.0.0` | Numerical computing / audio processing |
| `realtimestt>=0.3.0` | Real-time speech-to-text + wake word |
| `PyAudio>=0.2.14` | Microphone access |
| `playwright>=1.57.0` | Browser automation for web agent |
| `python-kasa>=0.10.0` | TP-Link Kasa smart device control |
| `requests>=2.32.0` | HTTP API calls |
| `feedparser>=6.0.0` | RSS news feed parsing |
| `ddgs>=9.13.0` | DuckDuckGo web search (current package) |
| `httpx>=0.28.0` | Async HTTP client |
| `psutil>=7.0.0` | System and process monitoring |
| `pynvml>=13.0.0` | NVIDIA GPU VRAM monitoring |
| `huggingface-hub>=0.36.0` | Download models from Hugging Face |
| `mss>=9.0.0` | Multi-monitor screenshot capture |
| `pyautogui>=0.9.54` | Mouse and keyboard automation |
| `Pillow>=10.0.0` | Image processing |
| `pywin32>=306` | Windows API (window focus) |
| `pyperclip>=1.8.0` | Clipboard access |
| `openai>=2.0.0` | **OpenAI API — used by Agent Builder** |
| `markdown>=3.4.0` | Markdown rendering in chat |
| `pygments>=2.15.0` | Syntax highlighting |
| `darkdetect>=0.8.0` | System dark/light mode detection |

### Optional (Calendar Sync)

Uncomment in `requirements.txt` and re-run `pip install -r requirements.txt`:

```text
google-auth>=2.29.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.130.0    # Google Calendar
msal>=1.28.0                         # Microsoft Outlook
```

---

## 🤖 Automatic Model Downloads

The following models are downloaded automatically on first run — no manual setup needed:

| Model | Purpose | Size | Source |
|-------|---------|------|--------|
| **FunctionGemma Router** | Intent classification | ~500 MB | [Hugging Face — nlouis/pocket-ai-router](https://huggingface.co/nlouis/pocket-ai-router) |
| **Piper TTS Voice** | Text-to-speech | ~50 MB | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) |
| **Whisper STT** | Speech-to-text | ~150 MB | OpenAI Whisper (via RealtimeSTT) |

> 📦 **First launch will take a few minutes** while these models download. All subsequent launches are instant.

Downloaded models are stored in `~/.plia_ai/` (i.e., `C:\Users\<YourName>\.plia_ai\` on Windows).

---

## 🎙️ Voice Assistant

Plia includes Alexa-style voice control with customisable wake word detection.

### How It Works

1. Say **"Jarvis"** to activate the assistant
2. Speak your command naturally
3. Plia classifies your intent, runs the action, and speaks the response

### Example Voice Commands

| Voice Command | What Happens |
|--------------|--------------| 
| *"Jarvis, turn on the office lights"* | Controls TP-Link Kasa smart lights |
| *"Jarvis, set a timer for 10 minutes"* | Creates a countdown timer in the Planner |
| *"Jarvis, what's the weather today?"* | Shows current weather from Open-Meteo |
| *"Jarvis, internet search on Python tutorials"* | Opens DuckDuckGo results in the browser panel |
| *"Jarvis, next search page"* | Paginates to the next results page |
| *"Jarvis, open search result 3"* | Opens result #3 in your default browser |
| *"Jarvis, close search"* | Closes the search results panel |
| *"Jarvis, add buy groceries to my to-do list"* | Creates a task in the Planner |
| *"Jarvis, what's on my schedule today?"* | Reads your calendar events |
| *"Jarvis, open Notepad"* | Desktop Agent launches the application |
| *"Jarvis, refresh active agents"* | Refreshes the Active Agents tab |
| *"Jarvis, help"* | Opens the full help guide on the Dashboard |
| *"Jarvis, what can you do?"* | Opens the full help guide on the Dashboard |

### Voice Configuration (`config.py`)

```python
# Wake word (lowercase). Default: "jarvis"
WAKE_WORD = "jarvis"

# Sensitivity 0.0–1.0. Lower = fewer false positives.
WAKE_WORD_SENSITIVITY = 0.4

# Enable/disable the voice assistant entirely
VOICE_ASSISTANT_ENABLED = True

# Whisper model size: "tiny", "base", "small", "medium", "large"
# Larger = more accurate but slower and more VRAM
REALTIMESTT_MODEL = "base"
```

---

## ❓ Help System

### Accessing Help

There are three ways to open the full help guide:

1. **Voice** — Say *"Jarvis, help"* or *"Jarvis, what can you do?"*
2. **Dashboard button** — Click the **🔍 Help** button in the left panel
3. **Dashboard input** — Type `help` in the input box and press SEND

The help panel opens in the Dashboard Communication Log and covers every feature and command in Plia.

---

## 🤖 Active Agents & Agent Builder

Plia can dynamically create, save, and run autonomous AI agents.

### Creating an Agent

Say or type any of:
- *"Create an agent that searches for Python tutorials"*
- *"Create an agent that monitors my email"*
- *"Create a programme that allows full control of Wi-Fi connected devices"*

Plia will:
1. Generate a complete Python script for the agent
2. Save it to `C:\Users\<YourName>\.plia_ai\agents\<agent_name>.py`
3. Register it in the Agents tab

### Running an Agent

- Open the **Active Agents** tab and click **Run** next to the agent name
- Or say *"Jarvis, run the <agent name> agent"*
- Standalone: `python "%USERPROFILE%\.plia_ai\agents\<agent_name>.py"`

### Agent Builder Requirements

Custom agents that perform internet search use:
- `openai>=2.0.0` — AI reasoning (set your API key in Settings)
- `ddgs>=9.13.0` — DuckDuckGo internet search
- `requests>=2.32.0` — File downloading (for download agents)

Install these if not already present:
```bash
pip install openai ddgs requests
```

---

## ⚙️ Configuration Reference (`config.py`)

### AI Models

```python
# Main chat and voice response model (Ollama)
RESPONDER_MODEL = "qwen3:1.7b"

# Ollama server URL — change only if Ollama is on another machine
OLLAMA_URL = "http://localhost:11434/api"

# How many messages to keep in conversation history
MAX_HISTORY = 20
```

**Supported Chat Models (via Ollama):**

| Model | Speed | Reasoning | Best For |
|-------|-------|-----------|----------|
| `qwen3:1.7b` | ⚡ Fast | Good | Daily use, quick responses |
| `qwen3:4b` | Moderate | Better | More nuanced answers |
| `deepseek-r1:1.5b` | Moderate | Excellent | Math, coding, step-by-step logic |
| `deepseek-r1:7b` | Slower | Outstanding | Complex reasoning tasks |

Any model available in `ollama list` can be set here.

### Text-to-Speech

```python
# Piper voice model (downloaded automatically)
TTS_VOICE_MODEL = "en_GB-northern_english_male-medium"
```

To use a different voice, download from [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) into `~/.plia_ai/tts_models/` and update `TTS_VOICE_MODEL` in `config.py`.

### Weather

Weather is provided by [Open-Meteo](https://open-meteo.com/) — free, no API key required.

To set your location: open Plia → **Settings** tab → enter your latitude and longitude.

---

## 🏗️ Project Architecture

```
Plia/
├── main.py                    # Entry point — launches Ollama, then the GUI
├── config.py                  # All configuration in one place
├── requirements.txt           # Python dependencies
├── pyproject.toml             # Project metadata
│
├── core/                      # Backend logic
│   ├── router.py              # FunctionGemma intent classifier
│   ├── function_executor.py   # Runs the action chosen by the router
│   ├── voice_assistant.py     # STT → Router → LLM → TTS pipeline
│   ├── stt.py                 # RealtimeSTT wrapper (Whisper + wake word)
│   ├── tts.py                 # Piper TTS (Python library + exe fallback)
│   ├── llm.py                 # Ollama streaming interface
│   ├── kasa_control.py        # TP-Link Kasa smart device control
│   ├── weather.py             # Open-Meteo weather API
│   ├── news.py                # DuckDuckGo news + AI curation
│   ├── tasks.py               # SQLite task management
│   ├── calendar_manager.py    # Local calendar/events (SQLite)
│   ├── calendar_sync.py       # Google / Outlook calendar sync (optional)
│   ├── history.py             # SQLite chat history
│   ├── model_manager.py       # Ollama model list management
│   ├── model_persistence.py   # Keep-alive / unload manager for Qwen
│   ├── agent_builder.py       # Dynamic AI agent creation (saves .py files)
│   ├── agent_registry.py      # Persistent agent store (custom_agents.json)
│   ├── settings_store.py      # JSON settings persistence
│   ├── discord_reader.py      # Discord channel reading (optional)
│   └── agent/
│       ├── desktop_agent.py   # Windows-Use natural language desktop control
│       └── desktop_controller.py  # Low-level desktop automation
│
├── gui/                       # PySide6 + QFluentWidgets frontend
│   ├── app.py                 # Main window, navigation, signal wiring
│   ├── handlers.py            # Chat message handling and streaming
│   ├── styles.py              # Global stylesheet (Aura theme)
│   ├── assets/                # Logo images
│   ├── components/            # Reusable widgets
│   │   ├── system_monitor.py  # CPU/RAM/GPU title bar widget
│   │   ├── alarm.py           # Alarm display widget
│   │   ├── timer.py           # Countdown timer widget
│   │   ├── toast.py           # Pop-up notification
│   │   ├── message_bubble.py  # Chat bubble renderer
│   │   ├── news_card.py       # News article card
│   │   ├── search_browser.py  # Floating web search results panel
│   │   ├── search_indicator.py
│   │   ├── thinking_expander.py  # Collapsible reasoning block
│   │   ├── schedule.py        # Schedule / calendar component
│   │   ├── toggle_switch.py
│   │   ├── weather_window.py  # Floating weather overlay
│   │   └── voice_indicator.py # Voice activity indicator widget
│   └── tabs/                  # Application screens
│       ├── dashboard.py       # Home: HUD display + quick commands + help
│       ├── chat.py            # AI chat interface
│       ├── planner.py         # Calendar, tasks, alarms, timers
│       ├── briefing.py        # AI-curated daily news
│       ├── home_automation.py # Smart device control
│       ├── agents.py          # Active agents manager
│       ├── desktop_agent.py   # Desktop agent control tab
│       ├── model_browser.py   # Ollama model browser & downloader
│       └── settings.py        # App settings screen
│
├── log/                       # Log files (auto-created)
│   ├── plia.log               # Application warnings and errors
│   └── realtimesst.log        # Speech-to-text engine log
│
└── merged_model/              # Router model (auto-downloaded, not in git)
    └── .gitkeep
```

### How the Pipeline Works

```
┌──────────────┐     ┌──────────────────┐     ┌────────────────┐
│  User Input  │────▶│  FunctionGemma   │────▶│   Function     │
│ (Voice/Text) │     │  Router (~50ms)  │     │   Executor     │
└──────────────┘     └──────────────────┘     └───────┬────────┘
                                                       │
          ┌────────────────────────────────────────────┼─────────────────┐
          │                         │                  │                 │
          ▼                         ▼                  ▼                 ▼
  ┌──────────────┐         ┌──────────────┐   ┌──────────────┐  ┌──────────────┐
  │  Kasa Lights │         │   Calendar   │   │  Web Search  │  │   Desktop    │
  └──────────────┘         └──────────────┘   └──────────────┘  │   Agent      │
                                                                 └──────────────┘
                                    │
                                    ▼
                           ┌──────────────┐
                           │  Qwen LLM    │
                           │ (via Ollama) │
                           └──────┬───────┘
                                  │
                                  ▼
                           ┌──────────────┐
                           │  Piper TTS   │
                           │  (Voice Out) │
                           └──────────────┘
```

1. The user speaks or types a command
2. **FunctionGemma Router** classifies intent in ~50ms (GPU) or ~200ms (CPU)
3. **Function Executor** runs the appropriate action (light control, timer, search, etc.)
4. **Qwen LLM** (via Ollama) generates a natural language response
5. **Piper TTS** speaks the response aloud (when voice is enabled)

---

## 🏠 Smart Home Integration

Plia supports **TP-Link Kasa** smart devices over your local network.

### Supported Devices

- ✅ Smart bulbs (on/off, brightness, colour temperature)
- ✅ Smart plugs (on/off)
- ✅ Smart light strips

### Setup

1. Ensure your Kasa devices are connected to the same WiFi as your computer
2. Open the **Home Automation** tab in Plia
3. Click **Refresh Devices** to discover them
4. Control via the GUI or voice commands

> ⚠️ If devices are not found, check your firewall is not blocking **UDP port 9999** (used for Kasa discovery).

---

## 📅 Calendar Sync (Optional)

Plia includes a local SQLite calendar that works out of the box. You can optionally sync with:

- **Google Calendar** — OAuth2 sign-in via the Settings tab
- **Microsoft Outlook** — MSAL authentication via the Settings tab

To enable calendar sync, uncomment the relevant lines in `requirements.txt` and re-run `pip install -r requirements.txt`:

```text
google-auth>=2.29.0
google-auth-oauthlib>=1.2.0
google-auth-httplib2>=0.2.0
google-api-python-client>=2.130.0    # Google Calendar
msal>=1.28.0                         # Microsoft Outlook
```

---

## 🔧 Troubleshooting

<details>
<summary><strong>❌ Ollama connection refused</strong></summary>

**Problem**: Plia can't connect to the Ollama model server.

**Solutions**:
1. Start Ollama manually: `ollama serve`
2. Verify a model is downloaded: `ollama list`
3. Check `OLLAMA_URL` in `config.py` (default: `http://localhost:11434/api`)

</details>

<details>
<summary><strong>❌ CUDA / GPU not detected</strong></summary>

**Problem**: PyTorch is running on CPU instead of GPU — router inference is slow.

**Solutions**:
1. Install CUDA-compatible PyTorch (CUDA 12.4):
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
   ```
2. Check your CUDA version first with `nvidia-smi`; use `cu121` if you have CUDA 12.1
3. Verify: `python -c "import torch; print(torch.cuda.is_available())"`

</details>

<details>
<summary><strong>❌ Responder model returns status 404</strong></summary>

**Problem**: `[System] Responder model load returned status 404` in the console.

**Solution**: The model named in `config.py` is not downloaded. Run:
```bash
ollama pull qwen3:1.7b
```
Then restart Plia. Replace `qwen3:1.7b` with whatever is set in `RESPONDER_MODEL`.

</details>

<details>
<summary><strong>❌ Voice assistant / wake word not working</strong></summary>

**Problem**: "Jarvis" is not being detected, or microphone is not responding.

**Solutions**:
1. Check microphone permissions: Windows Settings → Privacy → Microphone
2. Ensure `realtimestt` and `pyaudio` are installed:
   ```bash
   pip install realtimestt pyaudio
   ```
3. Lower the sensitivity in `config.py`:
   ```python
   WAKE_WORD_SENSITIVITY = 0.3  # try lower values
   ```
4. Check your default recording device in Windows Sound settings
5. Check `log/realtimesst.log` for detailed STT errors

</details>

<details>
<summary><strong>❌ TTS / voice output not working ("channels not specified")</strong></summary>

**Problem**: Piper TTS raises an audio error when speaking.

**Solution**: Ensure you have `piper-tts >= 1.4.0` and `sounddevice >= 0.5.0`:
```bash
pip install "piper-tts>=1.4.0" "sounddevice>=0.5.0" "numpy>=2.0.0"
```

The TTS module pre-configures the wave writer before synthesis — this requires piper-tts 1.4+.

</details>

<details>
<summary><strong>❌ TTS error: PiperVoice.synthesize() unexpected keyword argument 'length_scale'</strong></summary>

**Problem**: Old piper-tts API call mismatch.

**Solution**: Update piper-tts to 1.4+:
```bash
pip install "piper-tts>=1.4.0" --upgrade
```

The `core/tts.py` file uses the new `synthesize_wav()` API with `SynthesisConfig` — this requires piper-tts 1.4 or later.

</details>

<details>
<summary><strong>❌ Web search returns no results / DuckDuckGo error</strong></summary>

**Problem**: Search fails or throws a `RuntimeWarning`.

**Solution**: The old `duckduckgo-search` package is deprecated. Install the new one:
```bash
pip install ddgs>=9.13.0
```

The import in all agent scripts should be:
```python
from ddgs import DDGS   # correct
# NOT: from duckduckgo_search import DDGS   (broken)
```

</details>

<details>
<summary><strong>❌ Agent Builder requires OpenAI key</strong></summary>

**Problem**: Custom agents that use GPT-4o need an API key.

**Solution**:
1. Get an API key from [platform.openai.com](https://platform.openai.com)
2. Open Plia → **Settings** tab → paste your key under "OpenAI API Key"

Agents that only use local Ollama do not need an OpenAI key.

</details>

<details>
<summary><strong>❌ Smart home devices not found</strong></summary>

**Problem**: Kasa devices don't appear in the Home Automation tab.

**Solutions**:
1. Make sure devices and computer are on the same WiFi network
2. Verify devices work in the official Kasa mobile app
3. Check your Windows Firewall is not blocking **UDP port 9999**
4. Run as Administrator if network discovery is restricted

</details>

<details>
<summary><strong>❌ PyAudio install fails on Windows</strong></summary>

**Problem**: `pip install pyaudio` fails with a build error.

**Solution**: Install the pre-built wheel:
```bash
pip install pipwin
pipwin install pyaudio
```
Or download the `.whl` directly from [Christoph Gohlke's wheels](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio).

</details>

<details>
<summary><strong>❌ Router model download fails</strong></summary>

**Problem**: The FunctionGemma router model can't be downloaded from Hugging Face.

**Solutions**:
1. Ensure `huggingface-hub` is installed: `pip install huggingface-hub`
2. Check internet connectivity
3. Try manually downloading with:
   ```bash
   python -c "from huggingface_hub import snapshot_download; snapshot_download('nlouis/pocket-ai-router', local_dir='merged_model')"
   ```

</details>

<details>
<summary><strong>❌ Torch ImportError / torchaudio WinError 127</strong></summary>

**Problem**: `WinError 127` or `ImportError: cannot import name 'tqdm'` on startup.

**Cause**: PyTorch and torchaudio built for different CUDA versions are installed.

**Solution**: Reinstall both for the same CUDA version:
```bash
pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 --index-url https://download.pytorch.org/whl/cu124
```

Verify:
```bash
python -c "import torch; import torchaudio; print(torch.__version__, torchaudio.__version__)"
```

</details>

<details>
<summary><strong>❌ Log files not appearing in Plia/log/</strong></summary>

**Problem**: Log files are going to unexpected locations.

**Note**: All log files are written to `Plia/log/`:
- `Plia/log/plia.log` — application warnings and errors
- `Plia/log/realtimesst.log` — RealtimeSTT speech engine log

The `log/` directory is created automatically on first run.

</details>

---

## 🖥️ GPU Acceleration Summary

| Component | With GPU | Without GPU |
|-----------|----------|-------------|
| **Router (FunctionGemma)** | ~50 ms | ~200 ms |
| **Ollama LLM streaming** | Fast tokens | Slower, functional |
| **Whisper STT** | Near real-time | Slight delay |
| **Piper TTS** | CPU-only (no GPU needed) | Same |

**CUDA Requirements**: NVIDIA GPU with Compute Capability 5.0+ (GTX 900 series or newer), VRAM 4 GB minimum.

---

## 🗂️ User Data Files

All user data is stored in `C:\Users\<YourName>\.plia_ai\` and is never uploaded anywhere:

| File / Folder | Contents |
|---------------|---------|
| `memory.json` | Conversation memory |
| `notes.json` | Notes and reminders |
| `reminders.json` | Scheduled reminders |
| `settings.json` | App settings (wake word, location, API key, etc.) |
| `custom_agents.json` | Agent registry (names, descriptions, file paths) |
| `agents/` | Agent Python scripts (`<agent_name>.py`) |
| `tts_models/` | Downloaded Piper voice models |

---

## 🤝 Contributing

Contributions are welcome! To contribute:

1. Fork the repository on GitHub
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes and test them
4. Submit a pull request with a clear description of what changed

Please do not commit:
- `__pycache__/` directories
- `merged_model/` (auto-downloaded)
- `data/*.db` files (runtime data)
- `.plia_ai/` user data
- API keys or credentials of any kind

---

## 📜 License

This project is open source. See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Ollama](https://ollama.com/) — Local LLM inference engine
- [QFluentWidgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) — Windows 11 Fluent Design UI components
- [Piper TTS](https://github.com/rhasspy/piper) — Fast, lightweight local text-to-speech
- [python-kasa](https://github.com/python-kasa/python-kasa) — TP-Link Kasa device library
- [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT) — Real-time speech recognition with Whisper
- [Open-Meteo](https://open-meteo.com/) — Free, open-source weather API
- [ddgs](https://github.com/deedy5/duckduckgo_search) — DuckDuckGo search library (current maintained package)
- [OpenAI Python Library](https://github.com/openai/openai-python) — GPT-4o for the Agent Builder

---

<p align="center">
  Made with ❤️ for local AI enthusiasts
</p>
