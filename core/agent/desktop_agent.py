"""
Desktop Agent - AI-driven full-desktop control via VLM + screenshot loop.

Mirrors the BrowserAgent architecture exactly but operates on the full
Windows desktop instead of a Playwright browser window:

    Screenshot → Qwen VL decides action → pyautogui executes → repeat

This means the agent can open and use ANY application — Discord, Spotify,
File Explorer, Office apps, games — exactly as a person would, because it
sees the real screen and controls the real mouse and keyboard.

Usage (voice/chat path — synchronous):
    from core.agent.desktop_agent import desktop_agent_singleton
    result = desktop_agent_singleton.run_task_sync("Open Discord and summarise #general")

Usage (GUI path — Qt signals):
    agent = DesktopAgent()
    thread = QThread()
    agent.moveToThread(thread)
    thread.started.connect(lambda: agent.start_task("Open Notepad"))
    agent.screenshot_updated.connect(my_label.setImage)
    agent.finished.connect(thread.quit)
    thread.start()
"""

import base64
import json
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .desktop_controller import DesktopController
from .vlm_client import VLMClient
from core.model_manager import ensure_exclusive_qwen
from core.model_persistence import unload_qwen
from core.settings_store import settings as app_settings


class DesktopAgent(QObject):
    """
    VLM-driven desktop control agent.

    Signals (for GUI integration):
        screenshot_updated(QImage) — emitted after every screenshot
        thinking_update(str)       — streams VLM reasoning text
        action_updated(str)        — human-readable description of each action
        finished()                 — task complete (success or failure)
        error_occurred(str)        — unrecoverable error message
    """

    screenshot_updated = Signal(QImage)
    thinking_update    = Signal(str)
    action_updated     = Signal(str)
    finished           = Signal()
    error_occurred     = Signal(str)

    def __init__(self, model_name: str = None):
        super().__init__()
        model = model_name or app_settings.get("models.web_agent", "qwen3-vl:4b")
        self.controller = DesktopController()
        self.client = VLMClient(
            model_name=model,
            mode="desktop",
            model_params={
                "temperature": 1,
                "top_k":       20,
                "top_p":       0.95,
            },
        )
        self.running = False
        self.history: list = []

    # ------------------------------------------------------------------ #
    # Qt / threaded entry point                                            #
    # ------------------------------------------------------------------ #

    def start_task(self, instruction: str):
        """
        Run a desktop task.  Call this from a QThread (via moveToThread).
        Emits signals for live UI updates.
        """
        # Free VRAM from the chat LLM before loading the VLM
        unload_qwen("desktop_agent_using_vlm")
        ensure_exclusive_qwen(self.client.model_name)

        self.running = True
        self.history = []

        try:
            self.controller.start()
            self.history.append({
                "role":    "system",
                "content": self.client.construct_system_prompt(),
            })
            self.history.append({
                "role":    "user",
                "content": instruction,
            })
            self._run_loop()
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.controller.stop()
            self.running = False
            self.finished.emit()

    def stop(self):
        """Request the agent to stop after the current action."""
        self.running = False

    # ------------------------------------------------------------------ #
    # Synchronous entry point (voice / chat path)                         #
    # ------------------------------------------------------------------ #

    def run_task_sync(
        self,
        instruction: str,
        progress_callback=None,
        timeout_seconds: int = 300,
    ) -> dict:
        """
        Run a desktop task synchronously (blocks until done or timeout).

        Args:
            instruction:       Natural language task description.
            progress_callback: Optional callable(str) for live action logs.
            timeout_seconds:   Maximum run time before forced termination.

        Returns:
            {"success": bool, "message": str, "data": {"log": [str]}}
        """
        unload_qwen("desktop_agent_sync")
        ensure_exclusive_qwen(self.client.model_name)

        self.running = True
        self.history = []
        log: list[str] = []
        start_time = time.time()

        def _log(msg: str):
            log.append(msg)
            if progress_callback:
                progress_callback(msg)

        try:
            self.controller.start()
            self.history.append({
                "role":    "system",
                "content": self.client.construct_system_prompt(),
            })
            self.history.append({
                "role":    "user",
                "content": instruction,
            })

            _log(f"Starting: {instruction}")
            self._run_loop_sync(_log, start_time, timeout_seconds)

        except Exception as e:
            _log(f"Error: {e}")
            return {
                "success": False,
                "message": f"Desktop agent error: {e}",
                "data":    {"log": log},
            }
        finally:
            self.controller.stop()
            self.running = False

        summary = log[-1] if log else "Task completed."
        return {
            "success": True,
            "message": summary,
            "data":    {"log": log},
        }

    # ------------------------------------------------------------------ #
    # Core VLM loop — Qt-signal version                                   #
    # ------------------------------------------------------------------ #

    def _run_loop(self):
        """Screenshot → VLM → action → repeat. Emits Qt signals."""
        while self.running:
            b64 = self.controller.get_screenshot()
            if not b64:
                time.sleep(1)
                continue

            self._emit_screenshot(b64)
            messages = self._build_messages(b64)

            action_data = None
            response_text = ""

            for chunk in self.client.generate_action(messages):
                if chunk["type"] == "thinking":
                    self.thinking_update.emit(chunk["content"])
                elif chunk["type"] == "text":
                    response_text += chunk["content"]
                elif chunk["type"] == "action":
                    action_data = chunk["content"]
                elif chunk["type"] == "error":
                    self.error_occurred.emit(chunk["content"])
                    return

            self._process_action(action_data, response_text)

    # ------------------------------------------------------------------ #
    # Core VLM loop — synchronous version                                 #
    # ------------------------------------------------------------------ #

    def _run_loop_sync(self, log_fn, start_time: float, timeout: int):
        """Screenshot → VLM → action → repeat. Uses a plain callback."""
        while self.running:
            if time.time() - start_time > timeout:
                log_fn("Timeout reached — stopping.")
                break

            b64 = self.controller.get_screenshot()
            if not b64:
                time.sleep(1)
                continue

            messages = self._build_messages(b64)
            action_data = None
            response_text = ""

            for chunk in self.client.generate_action(messages):
                if chunk["type"] == "thinking":
                    pass  # Discard thinking in sync mode (too verbose)
                elif chunk["type"] == "text":
                    response_text += chunk["content"]
                elif chunk["type"] == "action":
                    action_data = chunk["content"]
                elif chunk["type"] == "error":
                    log_fn(f"VLM error: {chunk['content']}")
                    self.running = False
                    return

            if action_data:
                action_name = action_data.get("action", "unknown")
                log_fn(f"Action: {action_name} {json.dumps(action_data)}")

                self.history.append({
                    "role":    "assistant",
                    "content": response_text + f"\n<tool_call>\n{json.dumps({'name': 'computer_use', 'arguments': action_data})}\n</tool_call>",
                })

                if action_name == "terminate":
                    status = action_data.get("status", "unknown")
                    log_fn(f"Task terminated: {status}")
                    self.running = False
                    return

                try:
                    self.controller.execute_action(action_name, action_data)
                except Exception as e:
                    log_fn(f"Execution error: {e}")

                self.history.append({
                    "role":    "user",
                    "content": "Action executed. Here is the current screen.",
                })
                time.sleep(1.0)

            else:
                if response_text.strip():
                    log_fn(f"VLM reasoned without action — reprompting…")
                    self.history.append({"role": "assistant", "content": response_text})
                    self.history.append({
                        "role":    "user",
                        "content": "You analysed the screen but did not output a <tool_call>. Please output the tool call now.",
                    })
                else:
                    log_fn("No action and no response — stopping.")
                    self.running = False

    # ------------------------------------------------------------------ #
    # Shared helpers                                                       #
    # ------------------------------------------------------------------ #

    def _build_messages(self, b64_img: str) -> list:
        """Attach the current screenshot to the latest user message."""
        ollama_messages = []
        for msg in self.history:
            m = msg.copy()
            if m["role"] == "user" and msg is self.history[-1]:
                m["images"] = [b64_img]
            ollama_messages.append(m)
        return ollama_messages

    def _process_action(self, action_data: dict | None, response_text: str):
        """Process a VLM action in the Qt-signal loop."""
        if action_data:
            action_name = action_data.get("action", "unknown")
            log_str = f"Action: {action_name} {json.dumps(action_data)}"
            self.action_updated.emit(log_str)

            self.history.append({
                "role":    "assistant",
                "content": response_text + f"\n<tool_call>\n{json.dumps({'name': 'computer_use', 'arguments': action_data})}\n</tool_call>",
            })

            if action_name == "terminate":
                self.action_updated.emit("Task terminated: " + action_data.get("status", "unknown"))
                self.running = False
                return

            try:
                self.controller.execute_action(action_name, action_data)
            except Exception as e:
                self.action_updated.emit(f"Execution error: {e}")

            self.history.append({
                "role":    "user",
                "content": "Action executed. Here is the current screen.",
            })
            time.sleep(1.0)

        else:
            if response_text.strip():
                self.action_updated.emit("Reprompting for tool call…")
                self.history.append({"role": "assistant", "content": response_text})
                self.history.append({
                    "role":    "user",
                    "content": "You analysed the screen but did not output a <tool_call>. Please output the tool call now.",
                })
            else:
                self.action_updated.emit("No action — stopping.")
                self.running = False

    def _emit_screenshot(self, b64_str: str):
        """Convert a base64 JPEG to QImage and emit the signal."""
        try:
            data  = base64.b64decode(b64_str)
            image = QImage.fromData(data)
            self.screenshot_updated.emit(image)
        except Exception as e:
            print(f"[DesktopAgent] Screenshot emit error: {e}")

    def cleanup(self):
        """Release controller resources."""
        self.controller.stop()
