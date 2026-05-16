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
        self._migrate_legacy_custom_agents()
        self._seed_builtins()
        self.scheduler.load_and_arm()
        self._started = True

    def _migrate_legacy_custom_agents(self) -> None:
        """One-time import of legacy custom_agents.json entries into the live
        agent store. Marked complete via a settings flag so we don't run again
        even if the user deletes the migrated agents."""
        try:
            from core.settings_store import settings as app_settings
            if app_settings.get("agents.legacy_migrated", False):
                return
        except Exception:
            app_settings = None

        from pathlib import Path
        import json

        legacy_path = Path.home() / ".plia_ai" / "custom_agents.json"
        if not legacy_path.exists():
            if app_settings is not None:
                app_settings.set("agents.legacy_migrated", True)
            return

        try:
            raw = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[agent_runtime] could not read legacy custom_agents.json: {exc}")
            return
        if not isinstance(raw, list) or not raw:
            if app_settings is not None:
                app_settings.set("agents.legacy_migrated", True)
            return

        from core.agent_creator import write_role_yaml, _slugify
        from core.agent_state import AgentState, now_iso

        migrated = 0
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            display_name = (entry.get("display_name") or entry.get("name") or "").strip()
            if not display_name:
                continue
            task = (entry.get("description") or entry.get("prompt") or display_name).strip()
            # Pick a slug that isn't already taken in the live store.
            base_slug = _slugify(display_name)
            slug = base_slug
            i = 2
            while self.store.get(slug) is not None:
                slug = f"{base_slug}_{i}"
                i += 1
            file_path = entry.get("file_path") or ""
            try:
                write_role_yaml(
                    roles_dir=_ROLES_DIR,
                    slug=slug,
                    display_name=display_name,
                    task=task,
                    tools=["web_search"] if not file_path else [],
                )
                multi_agent_system.reload_roles()
                instance = self._make_instance(slug, display_name)
                state = AgentState(
                    role_id=slug,
                    instance_id=getattr(instance, "id", slug),
                    display_name=display_name,
                    icon=entry.get("icon") or "🤖",
                    executor="script" if file_path else "tool_loop",
                    trigger="on_demand",
                    persistence="persistent",
                    notify="chat",
                    status="active",
                    created_at=now_iso(),
                    script_path=file_path or None,
                    cadence=None,
                    quota=None,
                )
                self.store.upsert(state)
                migrated += 1
            except Exception as exc:
                print(f"[agent_runtime] migration of {display_name!r} failed: {exc}")

        if app_settings is not None:
            app_settings.set("agents.legacy_migrated", True)
        if migrated:
            # Rename the legacy file so agent_registry stops surfacing them
            # under "Custom Agents" — keep it as a *.bak in case the user
            # wants to inspect the originals.
            try:
                legacy_path.rename(legacy_path.with_suffix(".json.migrated.bak"))
            except Exception as exc:
                print(f"[agent_runtime] could not rename legacy file: {exc}")
            # Force agent_registry to drop its in-memory cache so the
            # Custom Agents section becomes empty immediately.
            try:
                from core.agent_registry import agent_registry
                agent_registry._load()
                agent_registry.agents_changed.emit()
            except Exception:
                pass
            print(f"[agent_runtime] ✓ Migrated {migrated} legacy Custom Agent(s) "
                  "to Live Agents (backup kept at custom_agents.json.migrated.bak)")

    def _seed_builtins(self) -> None:
        """Create built-in agents we always ship with, if they're missing.

        Currently just the Web Search agent — wraps the web_search tool so
        users can invoke it directly from Agent List / Run-with-prompt and
        see results in the Web Searches tab. Deletable; comes back next
        start if the user removes it.
        """
        from core.agent_creator import write_role_yaml
        from core.agent_state import AgentState, now_iso

        if self.store.get("web_search") is not None:
            return
        try:
            slug = "web_search"
            display_name = "Web Search"
            task = (
                "Search the web for the query given in the task and return "
                "relevant results. Each item must include a real title and url."
            )
            # Write the role YAML with a deterministic role_id (not a slugified
            # task title) so future starts can find this agent by id.
            role_path = write_role_yaml(
                roles_dir=_ROLES_DIR,
                slug=slug,
                display_name=display_name,
                task=task,
                tools=["web_search"],
            )
            if role_path.stem != slug:
                # write_role_yaml dedupes if the file already existed; in our
                # case role wasn't there so this shouldn't happen, but bail
                # cleanly if it does to avoid an orphaned YAML.
                print(f"[agent_runtime] web_search seed got slug {role_path.stem}; aborting")
                return
            multi_agent_system.reload_roles()
            instance = self._make_instance(slug, display_name)
            state = AgentState(
                role_id=slug,
                instance_id=getattr(instance, "id", slug),
                display_name=display_name,
                icon="🔎",
                executor="tool_loop",
                trigger="on_demand",
                persistence="persistent",
                notify="web_searches",
                status="active",
                created_at=now_iso(),
                script_path=None,
                cadence=None,
                quota=None,
            )
            self.store.upsert(state)
            print("[agent_runtime] ✓ Seeded built-in Web Search agent")
        except Exception as exc:
            print(f"[agent_runtime] could not seed Web Search agent: {exc}")

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
