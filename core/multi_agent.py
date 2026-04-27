"""
multi_agent.py — Jarvis-style multi-agent core for Plia

This module ports the core multi-agent concepts from Jarvis into Plia:
- agent lifecycle
- parent/child hierarchy
- role definitions loaded from YAML
- delegation
- background task manager
- sub-agent runner

It is intentionally self-contained so Plia can adopt the multi-agent
runtime without replacing the existing custom-agent registry.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

import yaml

AgentStatus = Literal["active", "idle", "terminated"]
AsyncTaskStatus = Literal["running", "completed", "failed"]


@dataclass
class CommunicationStyle:
    tone: str
    verbosity: str
    formality: str


@dataclass
class SubRoleTemplate:
    role_id: str
    name: str
    description: str
    spawned_by: str
    reports_to: str
    max_budget_per_task: int


@dataclass
class RoleDefinition:
    id: str
    name: str
    description: str
    responsibilities: List[str]
    autonomous_actions: List[str]
    approval_required: List[str]
    kpis: List[Dict[str, str]]
    communication_style: CommunicationStyle
    heartbeat_instructions: str
    sub_roles: List[SubRoleTemplate]
    tools: List[str]
    authority_level: int


@dataclass
class AuthorityBounds:
    max_authority_level: int
    allowed_tools: List[str]
    denied_tools: List[str]
    max_token_budget: int
    can_spawn_children: bool


@dataclass
class AgentRecord:
    id: str
    role: RoleDefinition
    parent_id: Optional[str]
    status: AgentStatus
    session_id: str
    current_task: Optional[str]
    authority: AuthorityBounds
    memory_scope: List[str] = field(default_factory=list)
    created_at: int = 0
    messages: List[Dict[str, str]] = field(default_factory=list)


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())


def _default_authority(role: RoleDefinition) -> AuthorityBounds:
    return AuthorityBounds(
        max_authority_level=role.authority_level,
        allowed_tools=list(role.tools),
        denied_tools=[],
        max_token_budget=100000,
        can_spawn_children=bool(role.sub_roles),
    )


def _merge_authority(default_auth: AuthorityBounds, custom: Optional[Dict[str, Any]] = None) -> AuthorityBounds:
    if not custom:
        return default_auth
    return AuthorityBounds(
        max_authority_level=custom.get("max_authority_level", default_auth.max_authority_level),
        allowed_tools=custom.get("allowed_tools", default_auth.allowed_tools),
        denied_tools=custom.get("denied_tools", default_auth.denied_tools),
        max_token_budget=custom.get("max_token_budget", default_auth.max_token_budget),
        can_spawn_children=custom.get("can_spawn_children", default_auth.can_spawn_children),
    )


class AgentInstance:
    def __init__(self, role: RoleDefinition, opts: Optional[Dict[str, Any]] = None):
        opts = opts or {}
        self.agent = AgentRecord(
            id=_uuid(),
            role=role,
            parent_id=opts.get("parent_id"),
            status="active",
            session_id=_uuid(),
            current_task=None,
            authority=_merge_authority(_default_authority(role), opts.get("authority")),
            memory_scope=list(opts.get("memory_scope", [])),
            created_at=_now_ms(),
        )

    @property
    def id(self) -> str:
        return self.agent.id

    @property
    def status(self) -> AgentStatus:
        return self.agent.status

    def set_task(self, task_description: str) -> None:
        self.agent.current_task = task_description

    def clear_task(self) -> None:
        self.agent.current_task = None

    def add_message(self, role: str, content: str) -> None:
        self.agent.messages.append({"role": role, "content": content})

    def get_messages(self) -> List[Dict[str, str]]:
        return list(self.agent.messages)

    def terminate(self) -> None:
        self.agent.status = "terminated"
        self.clear_task()

    def activate(self) -> None:
        if self.agent.status != "terminated":
            self.agent.status = "active"

    def idle(self) -> None:
        if self.agent.status != "terminated":
            self.agent.status = "idle"
            self.clear_task()

    def to_json(self) -> Dict[str, Any]:
        return {
            "id": self.agent.id,
            "role": self.agent.role.__dict__,
            "parent_id": self.agent.parent_id,
            "status": self.agent.status,
            "session_id": self.agent.session_id,
            "current_task": self.agent.current_task,
            "authority": self.agent.authority.__dict__,
            "memory_scope": list(self.agent.memory_scope),
            "created_at": self.agent.created_at,
        }


class AgentHierarchy:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentInstance] = {}
        self._children: Dict[str, set[str]] = {}

    def add_agent(self, agent: AgentInstance) -> None:
        self._agents[agent.id] = agent
        parent_id = agent.agent.parent_id
        if parent_id:
            self._children.setdefault(parent_id, set()).add(agent.id)

    def remove_agent(self, agent_id: str) -> None:
        agent = self._agents.get(agent_id)
        if not agent:
            return
        for child_id in list(self._children.get(agent_id, set())):
            self.remove_agent(child_id)
        self._children.pop(agent_id, None)
        parent_id = agent.agent.parent_id
        if parent_id and parent_id in self._children:
            self._children[parent_id].discard(agent_id)
        self._agents.pop(agent_id, None)

    def get_agent(self, agent_id: str) -> Optional[AgentInstance]:
        return self._agents.get(agent_id)

    def get_children(self, agent_id: str) -> List[AgentInstance]:
        return [self._agents[c] for c in self._children.get(agent_id, set()) if c in self._agents]

    def get_parent(self, agent_id: str) -> Optional[AgentInstance]:
        agent = self._agents.get(agent_id)
        if not agent or not agent.agent.parent_id:
            return None
        return self._agents.get(agent.agent.parent_id)

    def get_primary(self) -> Optional[AgentInstance]:
        for agent in self._agents.values():
            if agent.agent.parent_id is None:
                return agent
        return None

    def get_all_agents(self) -> List[AgentInstance]:
        return list(self._agents.values())

    def get_active_agents(self) -> List[AgentInstance]:
        return [a for a in self._agents.values() if a.status == "active"]


def build_system_prompt(role: RoleDefinition, context: Optional[Dict[str, Any]] = None) -> str:
    context = context or {}
    parts = [
        "# Identity",
        f"You are {role.name}. {role.description}",
        "",
        "# Responsibilities",
        *[f"- {item}" for item in role.responsibilities],
        "",
        "# Available Tools",
        *[f"- {tool}" for tool in role.tools],
        "",
        "# Authority Level",
        f"Your authority level is {context.get('effectiveAuthorityLevel', role.authority_level)}/10.",
        "",
        "# Heartbeat Instructions",
        role.heartbeat_instructions,
    ]
    return "\n".join(parts)


def discover_roles(dir_path: str) -> Dict[str, RoleDefinition]:
    roles: Dict[str, RoleDefinition] = {}
    path = Path(dir_path)
    if not path.exists():
        return roles

    for file_path in path.iterdir():
        if file_path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            if not isinstance(raw, dict):
                continue
            communication = raw.get("communication_style", {})
            role = RoleDefinition(
                id=str(raw["id"]),
                name=str(raw["name"]),
                description=str(raw["description"]),
                responsibilities=list(raw.get("responsibilities", [])),
                autonomous_actions=list(raw.get("autonomous_actions", [])),
                approval_required=list(raw.get("approval_required", [])),
                kpis=list(raw.get("kpis", [])),
                communication_style=CommunicationStyle(
                    tone=str(communication.get("tone", "")),
                    verbosity=str(communication.get("verbosity", "")),
                    formality=str(communication.get("formality", "")),
                ),
                heartbeat_instructions=str(raw.get("heartbeat_instructions", "")),
                sub_roles=[SubRoleTemplate(**item) for item in raw.get("sub_roles", [])],
                tools=list(raw.get("tools", [])),
                authority_level=int(raw.get("authority_level", 0)),
            )
            roles[role.id] = role
        except Exception as exc:
            print(f"[multi_agent] Failed to load role {file_path}: {exc}")
    return roles


def format_specialist_list(specialists: Dict[str, RoleDefinition]) -> str:
    if not specialists:
        return ""
    lines = ["## Available Specialists", ""]
    for role_id, role in specialists.items():
        desc = role.description.split("\n")[0].strip()
        lines.append(f"- **{role.name}** (`{role_id}`): {desc} [tools: {', '.join(role.tools)}]")
    return "\n".join(lines)


class AgentTaskManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def launch(self, *, agent: AgentInstance, task: str, context: str, runner: Callable[..., Dict[str, Any]]) -> str:
        task_id = _uuid()
        record = {
            "id": task_id,
            "agentId": agent.id,
            "agentName": agent.agent.role.name,
            "task": task,
            "context": context,
            "status": "running",
            "startedAt": _now_ms(),
            "completedAt": None,
            "result": None,
        }
        with self._lock:
            self._tasks[task_id] = record

        def _run():
            try:
                result = runner(agent=agent, task=task, context=context)
                with self._lock:
                    record["status"] = "completed"
                    record["completedAt"] = _now_ms()
                    record["result"] = result
            except Exception as exc:
                with self._lock:
                    record["status"] = "failed"
                    record["completedAt"] = _now_ms()
                    record["result"] = {"success": False, "response": str(exc)}

        threading.Thread(target=_run, daemon=True).start()
        return task_id

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = list(self._tasks.values())
        if status:
            return [task for task in tasks if task.get("status") == status]
        return tasks


class MessageStore:
    def __init__(self) -> None:
        self._messages: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: str,
        content: str,
        *,
        priority: str = "normal",
        requires_response: bool = False,
        deadline: Optional[int] = None,
    ) -> Dict[str, Any]:
        message = {
            "id": _uuid(),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "type": message_type,
            "content": content,
            "priority": priority,
            "requires_response": requires_response,
            "deadline": deadline,
            "created_at": _now_ms(),
        }
        with self._lock:
            self._messages.append(message)
        return message

    def get_messages(self, agent_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [m for m in self._messages if m["to_agent"] == agent_id]

    def get_pending_messages(self, agent_id: str) -> List[Dict[str, Any]]:
        return self.get_messages(agent_id)


class MultiAgentSystem:
    def __init__(self, roles_dir: str = "roles") -> None:
        self.roles_dir = roles_dir
        self.hierarchy = AgentHierarchy()
        self.roles = discover_roles(roles_dir)
        self.task_manager = AgentTaskManager()
        self.messages = MessageStore()

    def reload_roles(self) -> None:
        self.roles = discover_roles(self.roles_dir)

    def create_primary(self, role_id: str) -> AgentInstance:
        if self.hierarchy.get_primary():
            raise RuntimeError("Primary agent already exists")
        if role_id not in self.roles:
            raise KeyError(f"Role not found: {role_id}")
        role = self.roles[role_id]
        agent = AgentInstance(role)
        self.hierarchy.add_agent(agent)
        return agent

    def spawn_sub_agent(self, parent_id: str, role_id: str) -> AgentInstance:
        parent = self.hierarchy.get_agent(parent_id)
        if not parent:
            raise RuntimeError(f"Parent agent not found: {parent_id}")
        if not parent.agent.authority.can_spawn_children:
            raise RuntimeError("Parent cannot spawn children")
        if role_id not in self.roles:
            raise KeyError(f"Role not found: {role_id}")
        role = self.roles[role_id]
        child = AgentInstance(role, {"parent_id": parent_id})
        self.hierarchy.add_agent(child)
        return child

    def send_message(self, from_agent: str, to_agent: str, message_type: str, content: str, **opts: Any) -> Dict[str, Any]:
        return self.messages.send_message(
            from_agent,
            to_agent,
            message_type,
            content,
            priority=str(opts.get("priority", "normal")),
            requires_response=bool(opts.get("requires_response", False)),
            deadline=opts.get("deadline"),
        )

    def get_messages(self, agent_id: str) -> List[Dict[str, Any]]:
        return self.messages.get_messages(agent_id)

    def get_pending_messages(self, agent_id: str) -> List[Dict[str, Any]]:
        return self.messages.get_pending_messages(agent_id)

    def delegate_task(self, parent_id: str, child_id: str, task: str, context: str = "") -> Dict[str, Any]:
        parent = self.hierarchy.get_agent(parent_id)
        child = self.hierarchy.get_agent(child_id)
        if not parent or not child:
            return {"success": False, "message": "Agent not found"}
        if child.agent.parent_id != parent.id:
            return {"success": False, "message": "Agent is not a child of the parent agent"}
        if not parent.agent.authority.can_spawn_children:
            return {"success": False, "message": "Parent agent does not have authority to delegate tasks"}
        commitment = {"id": _uuid(), "task": task, "context": context, "assigned_to": child.id, "created_from": parent.id}
        self.send_message(parent.id, child.id, "task", task, priority="normal", requires_response=True)
        child.set_task(task)
        return {"success": True, "message": "Task delegated successfully", "child_id": child.id, "commitment_id": commitment["id"]}

    def report_completion(self, child_id: str, parent_id: str, summary: str, details: str = "") -> Dict[str, Any]:
        child = self.hierarchy.get_agent(child_id)
        parent = self.hierarchy.get_agent(parent_id)
        if not parent or not child:
            return {"success": False, "message": "Agent not found"}
        if child.agent.parent_id != parent.id:
            return {"success": False, "message": "Agent is not a child of the specified parent"}
        content = {"task": child.agent.current_task, "summary": summary, "details": details}
        self.send_message(child.id, parent.id, "report", str(content), priority="normal", requires_response=False)
        child.clear_task()
        child.idle()
        return {"success": True, "message": "Completion reported"}

    def terminate_agent(self, agent_id: str) -> None:
        agent = self.hierarchy.get_agent(agent_id)
        if agent:
            agent.terminate()
            self.hierarchy.remove_agent(agent_id)

    def snapshot(self) -> Dict[str, Any]:
        primary = self.hierarchy.get_primary()
        return {
            "primary": primary.to_json() if primary else None,
            "agents": [a.to_json() for a in self.hierarchy.get_all_agents()],
            "tasks": self.task_manager.list_tasks(),
            "roles": list(self.roles.keys()),
        }


multi_agent_system = MultiAgentSystem()
