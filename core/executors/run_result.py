"""
run_result.py — Shared result type for all agent executors.

Every executor (script or tool-loop) returns a RunResult. The scheduler's
completion callback normalises whatever AgentTaskManager hands back (which
may be a RunResult, or a plain dict if AgentTaskManager caught an exception)
into a RunResult via `from_runner_output`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RunResult:
    success: bool
    summary: str
    details: str
    items_found: int = 0
    items: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_runner_output(cls, output: Any) -> "RunResult":
        """Normalise a runner's return value into a RunResult.

        AgentTaskManager stores whatever the runner returns; on an exception
        it stores {"success": False, "response": str(exc)}. Anything that is
        not already a RunResult is treated as a failure dict.
        """
        if isinstance(output, RunResult):
            return output
        details = ""
        if isinstance(output, dict):
            details = str(output.get("response", output))
        else:
            details = str(output)
        return cls(
            success=False,
            summary="Run did not return a structured result.",
            details=details,
            error="runner_returned_dict",
        )
