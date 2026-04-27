"""
agents.py — Jarvis-style compatibility exports for Plia

This module mirrors Jarvis's agents/index.ts pattern by exposing the
agent runtime surface from one place.
"""

from __future__ import annotations

from core.multi_agent import (
    AgentInstance,
    AgentHierarchy,
    AgentTaskManager,
    AuthorityBounds,
    CommunicationStyle,
    MessageStore,
    MultiAgentSystem,
    RoleDefinition,
    SubRoleTemplate,
    build_system_prompt,
    discover_roles,
    format_specialist_list,
    multi_agent_system,
)


def send_message(from_agent: str, to_agent: str, message_type: str, content: str, **opts):
    return multi_agent_system.send_message(from_agent, to_agent, message_type, content, **opts)


def get_messages(agent_id: str):
    return multi_agent_system.get_messages(agent_id)


def get_pending_messages(agent_id: str):
    return multi_agent_system.get_pending_messages(agent_id)


def delegate_task(parent_id: str, child_id: str, task: str, context: str = ""):
    return multi_agent_system.delegate_task(parent_id, child_id, task, context)


def report_completion(child_id: str, parent_id: str, summary: str, details: str = ""):
    return multi_agent_system.report_completion(child_id, parent_id, summary, details)


__all__ = [
    "AgentInstance",
    "AgentHierarchy",
    "AgentTaskManager",
    "AuthorityBounds",
    "CommunicationStyle",
    "MessageStore",
    "MultiAgentSystem",
    "RoleDefinition",
    "SubRoleTemplate",
    "build_system_prompt",
    "discover_roles",
    "format_specialist_list",
    "multi_agent_system",
    "send_message",
    "get_messages",
    "get_pending_messages",
    "delegate_task",
    "report_completion",
]
