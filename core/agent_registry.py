"""
agent_registry.py — Dynamic Custom Agent Registry for Plia
============================================================
Persists user-created agents to ~/.plia_ai/custom_agents.json
Each agent has:
  - name:        short identifier (e.g. "email_summariser")
  - display_name: human label shown in Agents tab
  - description: one-line description
  - prompt:      the system prompt / task instruction the agent runs
  - created_at:  ISO timestamp
  - runs:        total execution count
  - last_run:    ISO timestamp of last execution (or None)
  - icon:        emoji icon chosen at creation
"""

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

# ── Storage path ──────────────────────────────────────────────────────────
PLIA_DIR = Path.home() / ".plia_ai"
PLIA_DIR.mkdir(parents=True, exist_ok=True)
AGENTS_FILE = PLIA_DIR / "custom_agents.json"

# ── Emojis pool for auto-assignment ──────────────────────────────────────
_ICON_POOL = ["🤖", "🧠", "🔧", "🌐", "📊", "📝", "🎯", "⚡", "🔬", "🗂️",
              "📡", "🛠️", "💡", "🔍", "📈", "🧩", "🚀", "🎙️", "🗒️", "🏷️"]


def _next_icon(existing: list[dict]) -> str:
    used = {a.get("icon") for a in existing}
    for icon in _ICON_POOL:
        if icon not in used:
            return icon
    return "🤖"


def _slugify(text: str) -> str:
    """Convert free text to a safe agent name slug."""
    slug = re.sub(r"[^\w\s]", "", text.lower())
    slug = re.sub(r"\s+", "_", slug.strip())
    return slug[:40] or "agent"


# ══════════════════════════════════════════════════════════════════════════
#  AgentRegistry
# ══════════════════════════════════════════════════════════════════════════
class AgentRegistry(QObject):
    """Thread-safe JSON-backed registry of custom agents with Qt signals."""

    # Emitted whenever the agent list changes so the Agents tab can refresh
    agents_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._agents: List[Dict[str, Any]] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load(self):
        if AGENTS_FILE.exists():
            try:
                with open(AGENTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._agents = data
                    return
            except Exception as e:
                print(f"[AgentRegistry] Load failed: {e}")
        self._agents = []

    def _save(self):
        try:
            with open(AGENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._agents, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[AgentRegistry] Save failed: {e}")

    # ── CRUD ──────────────────────────────────────────────────────────────

    def all_agents(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._agents)

    def get_agent(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for a in self._agents:
                if a["name"] == name:
                    return dict(a)
        return None

    def create_agent(
        self,
        display_name: str,
        description: str,
        prompt: str,
        icon: str = "",
        file_path: str = "",
        agent_type: str = "custom",
    ) -> Dict[str, Any]:
        """
        Create and persist a new custom agent.

        Returns the new agent dict so callers can immediately run it.
        If file_path is provided (set by AgentBuilder after writing the .py),
        it is stored so the Agents tab can run it as a subprocess.
        """
        with self._lock:
            # Build a unique slug
            base = _slugify(display_name)
            name = base
            existing_names = {a["name"] for a in self._agents}
            i = 2
            while name in existing_names:
                name = f"{base}_{i}"
                i += 1

            if not icon:
                icon = _next_icon(self._agents)

            agent = {
                "name":         name,
                "display_name": display_name,
                "description":  description,
                "prompt":       prompt,
                "icon":         icon,
                "created_at":   datetime.now().isoformat(),
                "runs":         0,
                "last_run":     None,
                "file_path":    file_path,    # path to .py script, "" if LLM-only
                "agent_type":   agent_type,   # "custom" | "internet_search"
            }
            self._agents.append(agent)
            self._save()

        self.agents_changed.emit()
        print(f"[AgentRegistry] Created agent '{name}': {display_name}"
              + (f" → {file_path}" if file_path else ""))
        return agent

    def delete_agent(self, name: str) -> bool:
        with self._lock:
            before = len(self._agents)
            self._agents = [a for a in self._agents if a["name"] != name]
            if len(self._agents) == before:
                return False
            self._save()
        self.agents_changed.emit()
        return True

    def record_run(self, name: str):
        """Bump run count and update last_run timestamp."""
        with self._lock:
            for a in self._agents:
                if a["name"] == name:
                    a["runs"] += 1
                    a["last_run"] = datetime.now().isoformat()
                    break
            self._save()

    # ── Execution ─────────────────────────────────────────────────────────

    def run_agent(
        self,
        name: str,
        user_input: str,
        ollama_url: str,
        model: str,
    ) -> Dict[str, Any]:
        """
        Execute a custom agent by calling Ollama with the agent's system prompt.

        Returns:
            {"success": bool, "message": str, "data": {"response": str}}
        """
        agent = self.get_agent(name)
        if not agent:
            return {"success": False, "message": f"Agent '{name}' not found.", "data": None}

        try:
            import requests

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": agent["prompt"]},
                    {"role": "user",   "content": user_input},
                ],
                "stream": False,
                "options": {"num_predict": 512},
            }

            base = ollama_url.rstrip("/api").rstrip("/")
            url  = f"{base}/api/chat"
            r = requests.post(url, json=payload, timeout=60)
            r.raise_for_status()
            resp_text = r.json().get("message", {}).get("content", "")

            self.record_run(name)
            return {
                "success": True,
                "message": resp_text.strip(),
                "data":    {"response": resp_text.strip(), "agent": name},
            }

        except Exception as e:
            return {"success": False, "message": f"Agent error: {e}", "data": None}

    def run_agent_file(self, name: str,
                        extra_args: list | None = None) -> Dict[str, Any]:
        """
        Run an agent's saved .py script as a subprocess (non-blocking).
        Used when the agent has a file_path (was built by AgentBuilder).

        extra_args: additional CLI arguments to pass to the script, e.g.
                    ["--search", "Python news", "--task", "Summarise top 5"].

        Returns immediately — the script runs in a new console window so
        the user can see live output.
        """
        import subprocess, sys
        agent = self.get_agent(name)
        if not agent:
            return {"success": False, "message": f"Agent '{name}' not found."}

        fp = agent.get("file_path", "")
        if not fp or not Path(fp).exists():
            return {"success": False, "message": f"Agent script not found at: {fp or '(no path)'}"}

        extra_args = extra_args or []

        try:
            # On Windows open a new console; on Linux/Mac run detached
            if sys.platform == "win32":
                subprocess.Popen(
                    ["cmd", "/c", "start", "cmd", "/k",
                     sys.executable, fp] + extra_args,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen([sys.executable, fp] + extra_args)
            self.record_run(name)
            return {"success": True, "message": f"Agent '{agent['display_name']}' launched in a new window."}
        except Exception as e:
            return {"success": False, "message": f"Launch error: {e}"}

    # ── NLP helper ────────────────────────────────────────────────────────

    @staticmethod
    def parse_create_intent(user_text: str) -> Optional[Dict[str, str]]:
        """
        Detect "create an agent that does X" patterns.

        Returns {"display_name": str, "description": str, "prompt": str} or None.
        Examples caught:
          "create an agent that summarises emails"
          "make an agent to monitor my GPU temperature"
          "build me an agent for writing Python code"
          "create a coding assistant agent"
        """
        patterns = [
            # "create/make/build (me/a/an) agent (that/to/for/which) <task>"
            r"(?:create|make|build|add|set up|setup)\s+(?:me\s+)?(?:an?|the)?\s*"
            r"(?:custom\s+)?agent\s+(?:that|to|for|which|called|named)?\s+(?:can\s+)?(.+)",
            # "create a <name> agent"
            r"(?:create|make|build|add)\s+(?:an?\s+)?(.+?)\s+agent\b",
        ]
        text = user_text.strip().lower()
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                task = m.group(1).strip().rstrip(".")
                if len(task) < 3:
                    continue
                # Capitalise nicely
                display_name = task.title()[:60]
                description  = f"Agent that {task}"
                system_prompt = (
                    f"You are a specialised AI assistant. Your job is to: {task}.\n"
                    f"Be concise, accurate, and helpful. Focus only on this task."
                )
                return {
                    "display_name": display_name,
                    "description":  description,
                    "prompt":       system_prompt,
                }
        return None


# ── Singleton ─────────────────────────────────────────────────────────────
agent_registry = AgentRegistry()
