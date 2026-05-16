"""
mcp_events.py — Qt signal hub for MCPClient lifecycle events.

Kept in its own module so the asyncio worker thread inside MCPClient can
emit signals without taking on Qt's full import cost lazily. The GUI tab
imports ``events.reloaded`` and refreshes its view when it fires.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _MCPEvents(QObject):
    # Fires after a hot reload finishes. Arg: number of tools discovered.
    reloaded = Signal(int)


events = _MCPEvents()
