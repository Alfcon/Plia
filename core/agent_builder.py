"""
agent_builder.py — Plia Agent Builder
======================================================
When the user asks Plia to "create a programme / build an agent / write a
tool that does X", this module:

  1.  Detects the intent (create_programme / build / write / make a programme)
  2.  Uses Ollama (RESPONDER_MODEL) to research and write a real, runnable
      Python agent file from scratch
  3.  Saves the file to  ~/.plia_ai/agents/<slug>.py
  4.  Registers it in  ~/.plia_ai/custom_agents.json  via AgentRegistry
  5.  Returns the path and a human-readable confirmation

Each agent file is completely self-contained:
  - Imports, logic, CLI entry-point and docstring
  - Works standalone (python ~/.plia_ai/agents/<slug>.py)
  - Can also be imported and called programmatically via run()

Architecture
------------
  ChatWorker.process()
      → agent_builder.detect_build_intent(text)   → dict | None
      → agent_builder.build_agent(intent, …)       → BuildResult
          → _research_and_code(task, ollama_url, model)   → str (Python src)
          → _write_agent_file(slug, src)                  → Path
          → agent_registry.create_agent(…)                → dict
"""

from __future__ import annotations

import re
import json
import textwrap
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

# ── Paths ──────────────────────────────────────────────────────────────────
PLIA_DIR   = Path.home() / ".plia_ai"
AGENTS_DIR = PLIA_DIR / "agents"
AGENTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Intent patterns ────────────────────────────────────────────────────────
# Matches phrases like:
#   "create a programme that …"   "build me a tool to …"
#   "write a script that …"       "make an agent for …"
#   "build a program to …"        "create an app that …"
#   "search for X and download to PATH"
_BUILD_PATTERNS = [
    r"(?:create|make|build|write|generate|develop|code)\s+"
    r"(?:me\s+)?(?:a|an|the)?\s*"
    r"(?:programme|program|script|tool|agent|app|application|utility|module|function|plugin)\s+"
    r"(?:that|to|for|which|called|named|to\s+help|that\s+can|that\s+will)?\s*"
    r"(?:can\s+|will\s+)?(.+)",

    # "build something that …"
    r"(?:create|make|build|write|generate)\s+something\s+(?:that|to|for|which)\s+(.+)",

    # "search for X and download to PATH"  — NEW
    r"(?:do\s+an?\s+)?(?:internet\s+)?search\s+for\s+(.+?)(?:\s+and\s+download.*)?$",
]

_BUILD_RE = [re.compile(p, re.IGNORECASE) for p in _BUILD_PATTERNS]

# Pattern to extract a download path from the user's text
_DOWNLOAD_PATH_RE = re.compile(
    r"download\s+(?:them|it|files?|results?)?\s*(?:to|into|in|at)\s+"
    r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+|~[^\s\"']*)",
    re.IGNORECASE,
)

# ── Hardcoded search-and-download template ─────────────────────────────────
# Used instead of asking the LLM when the intent is "search … and download to …"
_SEARCH_DOWNLOAD_TEMPLATE = '''\
"""
Agent: {slug}
Built by Plia AgentBuilder on {timestamp}
Task: Search the internet for "{topic}" and download results to {dest_dir}
Run standalone: python "{file_path}"
"""

import sys
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

# ── destination directory ─────────────────────────────────────────────
DEST_DIR = Path(r"{dest_dir}")
DEST_DIR.mkdir(parents=True, exist_ok=True)

SEARCH_QUERY  = "{topic}"
MAX_RESULTS   = 20          # number of search results to fetch
DOWNLOAD_EXTS = {{".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm"}}


def _safe_filename(url: str, idx: int) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    name = re.sub(r"[^\\w\\-\\.]+", "_", name)[:80]
    if not name or "." not in name:
        name = f"doc_{{idx:03d}}.html"
    return name


def search(query: str) -> list[dict]:
    """Return up to MAX_RESULTS results using duckduckgo-search."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        try:
            from ddgs import DDGS
        except ImportError:
            print("[ERROR] duckduckgo-search is not installed.")
            print("  Run:  pip install duckduckgo-search")
            sys.exit(1)

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=MAX_RESULTS):
            results.append({{
                "title": r.get("title", ""),
                "url":   r.get("href", ""),
                "body":  r.get("body", ""),
            }})
    return results


def download_result(result: dict, idx: int) -> str:
    """Download a single search result. Returns status string."""
    import requests

    url = result["url"]
    if not url:
        return f"  [SKIP] No URL for result {{idx}}"

    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()

    try:
        headers = {{"User-Agent": "Mozilla/5.0 (compatible; PliaBot/1.0)"}}
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()

        # Use content-type to decide filename when path has no useful extension
        if ext not in DOWNLOAD_EXTS:
            ct = resp.headers.get("content-type", "")
            if "pdf" in ct:
                ext = ".pdf"
            elif "html" in ct:
                ext = ".html"
            else:
                ext = ".html"

        fname = _safe_filename(url, idx)
        if not fname.endswith(ext):
            fname = Path(fname).stem + ext

        dest = DEST_DIR / fname
        # Avoid overwriting
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = DEST_DIR / f"{{stem}}_{{counter}}{{suffix}}"
            counter += 1

        dest.write_bytes(resp.content)
        kb = dest.stat().st_size // 1024
        return f"  [OK] {{fname}}  ({{kb}} KB)  ← {{url}}"
    except Exception as e:
        return f"  [FAIL] {{url}} — {{e}}"


def save_index(results: list[dict]):
    """Write a plain-text index of all results."""
    index_path = DEST_DIR / "_index.txt"
    lines = [f"Search: {{SEARCH_QUERY}}", f"Results: {{len(results)}}", ""]
    for i, r in enumerate(results, 1):
        lines.append(f"{{i:02d}}. {{r['title']}}")
        lines.append(f"    {{r['url']}}")
        lines.append(f"    {{r['body'][:200]}}")
        lines.append("")
    index_path.write_text("\\n".join(lines), encoding="utf-8")
    print(f"\\n[INDEX] Written to {{index_path}}")


def run(**kwargs) -> str:
    """Entry point for programmatic use by Plia."""
    query = kwargs.get("query", SEARCH_QUERY)
    dest  = Path(kwargs.get("dest_dir", str(DEST_DIR)))
    dest.mkdir(parents=True, exist_ok=True)
    results = search(query)
    if not results:
        return f"No results found for: {{query}}"
    lines = [f"Searched: {{query}}", f"Found {{len(results)}} results", ""]
    for i, r in enumerate(results, 1):
        status = download_result(r, i)
        lines.append(status)
    save_index(results)
    return "\\n".join(lines)


if __name__ == "__main__":
    SEP = "=" * 60
    print(f"\\n{{SEP}}")
    print(f"  Plia Agent: Search + Download")
    print(f"  Query :  {{SEARCH_QUERY}}")
    print(f"  Saving to: {{DEST_DIR}}")
    print(f"{{SEP}}\\n")

    print("[1/3] Searching the internet…")
    results = search(SEARCH_QUERY)
    if not results:
        print("[!] No results found. Exiting.")
        sys.exit(0)
    print(f"      Found {{len(results)}} results.\\n")

    print("[2/3] Downloading documents…")
    for i, r in enumerate(results, 1):
        print(f"  {{i:02d}}/{{len(results)}} {{r['title'][:60]}}")
        status = download_result(r, i)
        print(status)
        time.sleep(0.3)   # be polite to servers

    print("\\n[3/3] Saving index…")
    save_index(results)

    print(f"\\n✅ Done! Files saved to: {{DEST_DIR}}")
    input("\\nPress ENTER to close…")
'''


# ── Return type ────────────────────────────────────────────────────────────
@dataclass
class BuildResult:
    success:      bool
    agent_name:   str = ""
    display_name: str = ""
    file_path:    str = ""
    message:      str = ""
    error:        str = ""


# ══════════════════════════════════════════════════════════════════════════
#  Public helpers
# ══════════════════════════════════════════════════════════════════════════

def detect_build_intent(text: str) -> Optional[dict]:
    """
    Return  {"task": str, "display_name": str, "search_download": bool,
             "topic": str, "dest_dir": str}  if the text is a build
    request, otherwise None.

    search_download=True means we use the hardcoded template instead of the LLM.
    """
    stripped = text.strip()

    # ── Check for search-and-download intent first ─────────────────────
    sdm = re.search(
        r"(?:do\s+an?\s+)?(?:internet\s+)?search\s+(?:for\s+)?(.+?)(?:\s+(?:and\s+)?download.*|$)",
        stripped, re.IGNORECASE,
    )
    if sdm:
        topic = sdm.group(1).strip().rstrip(".!?,")
        # Extract destination path if present
        pm = _DOWNLOAD_PATH_RE.search(stripped)
        dest_dir = pm.group(1).strip() if pm else str(Path.home() / "Downloads")
        display_name = _title(f"search {topic}")
        return {
            "task":            f"search the internet for {topic} and download results to {dest_dir}",
            "display_name":    display_name,
            "search_download": True,
            "topic":           topic,
            "dest_dir":        dest_dir,
        }

    # ── General build intent ─────────────────────────────────────────────
    for rx in _BUILD_RE:
        m = rx.search(stripped)
        if m:
            task = m.group(1).strip().rstrip(".!?")
            if len(task) < 4:
                continue
            display_name = _title(task)
            return {
                "task":            task,
                "display_name":    display_name,
                "search_download": False,
                "topic":           task,
                "dest_dir":        "",
            }
    return None


def build_agent(
    intent:      dict,
    ollama_url:  str,
    model:       str,
    on_status:   Callable[[str], None] = lambda s: None,
) -> BuildResult:
    """
    Full pipeline: research → code → save → register.
    Runs synchronously (call from a background thread).

    For search-and-download tasks uses a hardcoded template (faster,
    more reliable than asking the LLM to guess file paths).
    """
    task         = intent["task"]
    display_name = intent.get("display_name", _title(task))
    slug         = _slugify(display_name)
    is_sd        = intent.get("search_download", False)

    if is_sd:
        # ── Search-and-download: use template, no LLM call needed ────────
        topic    = intent.get("topic", task)
        dest_dir = intent.get("dest_dir", str(Path.home() / "Downloads"))
        on_status(f"📥 Building search-and-download agent for: {topic}")

        agent_path_stub = AGENTS_DIR / f"{slug}.py"
        src = _SEARCH_DOWNLOAD_TEMPLATE.format(
            slug      = slug,
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            topic     = topic,
            dest_dir  = dest_dir,
            file_path = str(agent_path_stub),
        )
    else:
        # ── Generic: ask the LLM to write code ───────────────────────────
        on_status(f"🔬 Researching: {display_name}…")
        try:
            src = _research_and_code(task, ollama_url, model, on_status)
        except Exception as exc:
            return BuildResult(success=False, error=f"LLM error: {exc}")

        if not src or len(src) < 80:
            return BuildResult(success=False, error="LLM returned no usable code.")

    on_status("💾 Writing agent file…")

    # 2. Save the file
    try:
        agent_path = _write_agent_file(slug, src)
    except Exception as exc:
        return BuildResult(success=False, error=f"File write error: {exc}")

    on_status("📋 Registering agent…")

    # 3. Register in custom_agents.json (pass the file_path so the Run button works)
    try:
        from core.agent_registry import agent_registry
        description   = f"Auto-built agent: {task[:120]}"
        system_prompt = (
            f"You are a specialised assistant that {task}. "
            f"When the user asks, execute or explain the relevant action."
        )
        agent_registry.create_agent(
            display_name = display_name,
            description  = description,
            prompt       = system_prompt,
            icon         = _pick_icon(task),
            file_path    = str(agent_path),   # ← now stored in registry
        )
    except Exception as exc:
        # Registration failure is non-fatal — file still works
        print(f"[AgentBuilder] Registry warning: {exc}")

    return BuildResult(
        success      = True,
        agent_name   = slug,
        display_name = display_name,
        file_path    = str(agent_path),
        message      = (
            f"✅ Agent **{display_name}** built and saved.\n\n"
            f"📄 File: `{agent_path}`\n\n"
            f"▶ Run standalone:  `python \"{agent_path}\"`\n\n"
            "The agent is also listed in your Agents tab — click **Run** to launch it."
        ),
    )


# ══════════════════════════════════════════════════════════════════════════
#  Private helpers
# ══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert Python developer embedded inside Plia, a local AI assistant.

    Your task: write a complete, standalone, well-commented Python script that
    fulfils the user's request.

    Rules — follow every one of these exactly:
    1.  Output ONLY raw Python source code. No markdown fences, no explanation
        text before or after, no triple backticks.
    2.  The file must be immediately runnable with  `python <file>.py`  and must
        include a  `if __name__ == "__main__":` block.
    3.  Export a callable  `run(**kwargs) -> str`  at module level so Plia can
        call it programmatically. It must return a human-readable result string.
    4.  Use only Python standard library modules PLUS any packages already listed
        in Plia's requirements.txt:
          PySide6, requests, psutil, pynvml, python-kasa, playwright,
          duckduckgo-search, feedparser, Pillow, pyautogui, pyperclip,
          piper-tts, sounddevice, soundfile, numpy, realtimestt, PyAudio,
          transformers, accelerate, safetensors, huggingface-hub
    5.  Include a module-level docstring explaining what the agent does and how
        to run it.
    6.  Handle all exceptions gracefully — never crash without a clear error
        message.
    7.  For networking / device tasks use async where required (asyncio).
    8.  For GUI agents use PySide6 (NOT tkinter).
    9.  Be thorough — produce a genuinely useful, feature-complete script, not
        a skeleton.
    10. DO NOT include any text outside the Python source code.
""")


def _research_and_code(
    task: str,
    ollama_url: str,
    model: str,
    on_status: Callable[[str], None],
) -> str:
    """Call Ollama to generate the agent source code."""
    on_status(f"🤖 Generating code for: {task[:60]}…")

    base = ollama_url.rstrip("/api").rstrip("/")
    url  = f"{base}/api/chat"

    payload = {
        "model":  model,
        "stream": True,
        "options": {
            "num_predict":   4096,
            "temperature":   0.2,   # low temperature = more deterministic code
            "top_p":         0.9,
        },
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": (
                f"Write a complete Python agent that: {task}\n\n"
                "Remember: output raw Python only — no markdown, no explanation."
            )},
        ],
    }

    resp = requests.post(url, json=payload, stream=True, timeout=180)
    resp.raise_for_status()

    chunks = []
    for line in resp.iter_lines():
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = obj.get("message", {}).get("content", "")
        if content:
            chunks.append(content)
        if obj.get("done"):
            break

    raw = "".join(chunks).strip()

    # Strip any accidental markdown fences the model may have added
    raw = re.sub(r"^```(?:python)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*$",          "", raw, flags=re.MULTILINE)
    return raw.strip()


def _write_agent_file(slug: str, src: str) -> Path:
    """Write source to ~/.plia_ai/agents/<slug>.py and return the path."""
    # Ensure we don't clobber an existing file — append a counter
    base = AGENTS_DIR / f"{slug}.py"
    path = base
    i    = 2
    while path.exists():
        path = AGENTS_DIR / f"{slug}_{i}.py"
        i += 1

    header = (
        f"# Agent: {slug}\n"
        f"# Built by Plia AgentBuilder on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# Location: {path}\n"
        "# Run standalone: python \"" + str(path) + "\"\n\n"
    )
    path.write_text(header + src, encoding="utf-8")
    return path


def _patch_file_path(slug: str, file_path: str):
    """Add file_path field to the matching agent in custom_agents.json."""
    from core.agent_registry import AGENTS_FILE
    try:
        with open(AGENTS_FILE, "r", encoding="utf-8") as f:
            agents = json.load(f)
        for a in agents:
            if a.get("name") == slug or a.get("name", "").startswith(slug):
                a["file_path"] = file_path
                break
        with open(AGENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(agents, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[AgentBuilder] patch_file_path failed: {exc}")


# ── Utilities ──────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\s]", "", text.lower())
    s = re.sub(r"\s+",     "_", s.strip())
    return s[:40] or "agent"


def _title(text: str) -> str:
    """Convert a task description to a short title."""
    words = text.split()[:6]
    return " ".join(w.capitalize() for w in words)


_ICON_MAP = {
    "wifi":    "📡", "network": "📡", "device":   "📡", "smart":  "🏠",
    "light":   "💡", "kasa":    "💡", "bulb":     "💡",
    "web":     "🌐", "search":  "🔍", "browser":  "🌐",
    "file":    "📁", "folder":  "📂", "document": "📄",
    "camera":  "📷", "screen":  "🖥️", "desktop":  "🖥️",
    "weather": "⛅", "news":    "📰", "email":    "📧",
    "music":   "🎵", "audio":   "🔊", "voice":    "🎙️",
    "timer":   "⏱️", "alarm":   "⏰", "calendar": "📅",
    "system":  "⚙️", "monitor": "📊", "gpu":      "🎮",
    "discord": "💬", "chat":    "💬",
}

def _pick_icon(task: str) -> str:
    t = task.lower()
    for kw, icon in _ICON_MAP.items():
        if kw in t:
            return icon
    return "🤖"
