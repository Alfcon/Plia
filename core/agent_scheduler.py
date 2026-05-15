"""
agent_scheduler.py — Cron-like scheduler for Plia live agents.

Two pure functions:
  parse_cadence(text)     -> {"interval_sec": int, "anchor_iso": str | None} | None
  compute_next_fire(cad)  -> datetime

Plus AgentScheduler (added in a later task), which holds one timer per agent
and fires AgentTaskManager.launch on each tick.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, Optional

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _next_weekday(from_dt: datetime, weekday: int, hour: int) -> datetime:
    days_ahead = (weekday - from_dt.weekday()) % 7
    candidate = from_dt.replace(hour=hour, minute=0, second=0, microsecond=0) \
        + timedelta(days=days_ahead)
    if candidate <= from_dt:
        candidate += timedelta(days=7)
    return candidate


def parse_cadence(text: str, now: Optional[datetime] = None) -> Optional[Dict]:
    """Parse a natural cadence phrase into {interval_sec, anchor_iso}.

    Returns None if the phrase is not understood.
    """
    if not text:
        return None
    now = now or datetime.now()
    t = text.strip().lower()

    # weekly — "every monday", "every monday morning"
    for name, wd in _WEEKDAYS.items():
        if name in t:
            anchor = _next_weekday(now, wd, hour=8)
            return {"interval_sec": 604800, "anchor_iso": anchor.isoformat(timespec="seconds")}

    # "every N minutes" / "every N mins"
    m = re.search(r"every\s+(\d+)\s*min", t)
    if m:
        return {"interval_sec": int(m.group(1)) * 60, "anchor_iso": None}

    # "every N hours"
    m = re.search(r"every\s+(\d+)\s*hour", t)
    if m:
        return {"interval_sec": int(m.group(1)) * 3600, "anchor_iso": None}

    # "every hour" / "hourly"
    if "hourly" in t or re.search(r"every\s+hour", t):
        return {"interval_sec": 3600, "anchor_iso": None}

    # "twice a day"
    if "twice a day" in t or "twice daily" in t:
        return {"interval_sec": 43200, "anchor_iso": None}

    # daily with a time — "every day at 8am", "daily at 8 am"
    m = re.search(r"at\s+(\d{1,2})\s*(am|pm)?", t)
    if ("daily" in t or "every day" in t) and m:
        hour = int(m.group(1))
        if m.group(2) == "pm" and hour < 12:
            hour += 12
        if m.group(2) == "am" and hour == 12:
            hour = 0
        anchor = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if anchor <= now:
            anchor += timedelta(days=1)
        return {"interval_sec": 86400, "anchor_iso": anchor.isoformat(timespec="seconds")}

    # plain daily
    if "daily" in t or "every day" in t:
        return {"interval_sec": 86400, "anchor_iso": None}

    return None


def compute_next_fire(cadence: Dict, from_dt: datetime) -> datetime:
    """Given a cadence dict and a reference time, return the next fire time.

    - No anchor: from_dt + interval.
    - Future anchor: the anchor itself.
    - Past anchor: advance by whole intervals until strictly after from_dt.
    """
    interval = int(cadence["interval_sec"])
    anchor_iso = cadence.get("anchor_iso")
    if not anchor_iso:
        return from_dt + timedelta(seconds=interval)

    anchor = datetime.fromisoformat(anchor_iso)
    if anchor > from_dt:
        return anchor

    elapsed = (from_dt - anchor).total_seconds()
    steps = int(elapsed // interval) + 1
    return anchor + timedelta(seconds=steps * interval)
