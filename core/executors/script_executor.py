"""
script_executor.py — Runs a generated agent .py file as an isolated subprocess.

make_script_runner(script_path, timeout_sec) returns a callable matching the
AgentTaskManager runner signature: runner(*, agent, task, context) -> RunResult.

The subprocess is invoked as:
    python <script_path> --task "<task>" --context "<context>" --json
and is expected to print a JSON object as its final stdout line, matching:
    {"success", "summary", "details", "items_found", "items"}
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from core.executors.run_result import RunResult


def make_script_runner(script_path: str, timeout_sec: int = 300) -> Callable[..., RunResult]:
    def _runner(*, agent, task: str, context: str) -> RunResult:
        if not Path(script_path).exists():
            return RunResult(
                success=False,
                summary="Agent script missing.",
                details=f"Script not found at: {script_path}",
                error="script_not_found",
            )
        try:
            proc = subprocess.run(
                [sys.executable, script_path,
                 "--task", task or "",
                 "--context", context or "",
                 "--json"],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                success=False,
                summary="Agent timed out.",
                details=f"Subprocess exceeded {timeout_sec}s.",
                error="timeout",
            )
        except Exception as exc:
            return RunResult(
                success=False,
                summary="Agent failed to start.",
                details=str(exc),
                error="executor_internal",
            )

        if proc.returncode != 0:
            return RunResult(
                success=False,
                summary="Agent script exited with an error.",
                details=(proc.stderr or proc.stdout or "")[-2000:],
                error=f"exit_{proc.returncode}",
            )

        last_json = None
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    last_json = json.loads(line)
                except json.JSONDecodeError:
                    continue
        if last_json is None:
            return RunResult(
                success=False,
                summary="Agent produced no result.",
                details="No JSON result line found in script output.",
                error="no_json",
            )

        return RunResult(
            success=bool(last_json.get("success", True)),
            summary=str(last_json.get("summary", "Done.")),
            details=str(last_json.get("details", "")),
            items_found=int(last_json.get("items_found", 0) or 0),
            items=list(last_json.get("items", []) or []),
            error=last_json.get("error"),
        )

    return _runner
