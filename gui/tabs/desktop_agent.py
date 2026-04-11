"""
Desktop Agent - Controls Windows applications and the desktop environment
using the windows-use library (https://github.com/CursorTouch/Windows-Use).

Accepts natural language tasks and executes them via the Windows UI
Automation accessibility tree — no pixel-hunting or screenshots required.

Requirements:
    pip install windows-use

Setup:
    No extra configuration needed beyond having Ollama running with the
    web_agent model (qwen3-vl:4b by default). The agent uses the
    accessibility tree, so vision is off by default (faster, more reliable).
"""

from typing import Optional
from core.settings_store import settings as app_settings


class DesktopAgent:
    """
    Wraps the windows-use Agent for natural language desktop control.

    Lazy-initialises on first use so it does not slow down Plia startup.
    The underlying Agent instance is reused across calls to avoid the
    overhead of re-creating the LLM connection each time.
    """

    def __init__(self):
        self._agent = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_agent(self):
        """Construct and return a configured windows-use Agent."""
        try:
            from windows_use import Agent
            from windows_use.providers.ollama import ChatOllama
        except ImportError:
            raise RuntimeError(
                "windows-use is not installed. "
                "Run:  pip install windows-use"
            )

        model    = app_settings.get("models.web_agent", "qwen3-vl:4b")
        base_url = app_settings.get("ollama_url",       "http://localhost:11434")

        llm = ChatOllama(model=model, base_url=base_url)

        return Agent(
            llm=llm,
            use_vision=False,        # Use accessibility tree — faster and more stable
            use_accessibility=True,  # Read UI element tree for precise targeting
            max_steps=25,            # Cap steps so runaway tasks self-terminate
            log_to_console=True,     # Print step-by-step progress to terminal
        )

    def _get_agent(self):
        """Return cached Agent, constructing it on first call."""
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_task(self, task: str) -> dict:
        """
        Execute a natural language desktop task.

        Args:
            task: Plain English instruction, e.g. "Open Discord and navigate
                  to the #general channel."

        Returns:
            Standard Plia result dict:
            {
                "success": bool,
                "message": str,   # Human-readable outcome
                "data":    Any    # Raw agent result content
            }
        """
        try:
            print(f"[DesktopAgent] Running task: {task}")
            agent  = self._get_agent()
            result = agent.invoke(task=task)

            # windows-use returns an object with a .content attribute
            content = str(result.content).strip() if result and result.content else "Task completed."

            return {
                "success": True,
                "message": content,
                "data":    {"task": task, "result": content}
            }

        except RuntimeError as e:
            # Import / setup errors — surface clearly
            return {"success": False, "message": str(e), "data": None}

        except Exception as e:
            print(f"[DesktopAgent] Error: {e}")
            # Reset cached agent so the next call gets a fresh instance
            self._agent = None
            return {
                "success": False,
                "message": f"Desktop agent error: {e}",
                "data":    None
            }

    def reset(self):
        """Discard the cached Agent (useful after errors or config changes)."""
        self._agent = None


# ---------------------------------------------------------------------------
# Module-level singleton — imported by FunctionExecutor
# ---------------------------------------------------------------------------
desktop_agent = DesktopAgent()
