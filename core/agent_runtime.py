"""
agent_runtime.py — Process-wide wiring for the live-agent system.

Constructs the single AgentStateStore + AgentScheduler + ResultDispatcher and
exposes them through get_runtime(). Voice, chat, and the app window all share
this one runtime so there is exactly one scheduler and one state store.

  get_runtime()                  -> the _Runtime singleton
  runtime.start()                -> load persisted agents + arm the scheduler
  runtime.commit_answers(answers) -> create a live agent from wizard answers
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.agent_state import AgentStateStore
from core.agent_scheduler import AgentScheduler, build_default_runner
from core.agent_reporting import ResultDispatcher
from core.agent_creator import commit
from core.multi_agent import multi_agent_system, AgentInstance
from config import OLLAMA_URL, RESPONDER_MODEL

_ROLES_DIR = Path.home() / ".plia_ai" / "roles"


class _Runtime:
    def __init__(self):
        self.store = AgentStateStore()
        self.dispatcher = ResultDispatcher()
        self.scheduler = AgentScheduler(
            state_store=self.store,
            task_manager=multi_agent_system.task_manager,
            runner_builder=self._build_runner,
            instance_provider=self._get_instance,
            reporter=self.dispatcher.report,
        )
        self._started = False

    # ── model helper ──────────────────────────────────────────────────────
    def _model(self) -> str:
        try:
            from core.settings_store import settings as app_settings
            return app_settings.get("models.chat", RESPONDER_MODEL)
        except Exception:
            return RESPONDER_MODEL

    # ── scheduler dependencies ────────────────────────────────────────────
    def _build_runner(self, state):
        role = multi_agent_system.roles.get(state.role_id)
        tools = list(role.tools) if role else []
        return build_default_runner(
            state, role_tools=tools, ollama_url=OLLAMA_URL, model=self._model())

    def _get_instance(self, role_id: str):
        for inst in multi_agent_system.hierarchy.get_all_agents():
            if inst.agent.role.id == role_id:
                return inst
        return None

    def _make_instance(self, role_id: str, display_name: str):
        multi_agent_system.reload_roles()
        role = multi_agent_system.roles.get(role_id)
        if role is None:
            print(f"[agent_runtime] role not found after reload: {role_id}")
            return None
        existing = self._get_instance(role_id)
        if existing is not None:
            return existing
        inst = AgentInstance(role)
        multi_agent_system.hierarchy.add_agent(inst)
        return inst

    # ── lifecycle ─────────────────────────────────────────────────────────
    def start(self) -> None:
        """Load persisted agents and arm the scheduler. Idempotent."""
        if self._started:
            return
        self.store.load()
        multi_agent_system.reload_roles()
        for state in self.store.all():
            if self._get_instance(state.role_id) is None:
                self._make_instance(state.role_id, state.display_name)
        self.scheduler.load_and_arm()
        self._started = True

    def commit_answers(self, answers: dict,
                       script_path: Optional[str] = None):
        """Create a live agent from wizard answers. Returns the AgentState."""
        return commit(
            answers,
            roles_dir=_ROLES_DIR,
            state_store=self.store,
            scheduler=self.scheduler,
            multi_agent_system=multi_agent_system,
            instance_factory=self._make_instance,
            script_path=script_path,
        )


_runtime: Optional[_Runtime] = None


def get_runtime() -> _Runtime:
    global _runtime
    if _runtime is None:
        _runtime = _Runtime()
    return _runtime
