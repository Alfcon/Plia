import subprocess

from core.executors.script_executor import make_script_runner
from core.executors.run_result import RunResult


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run(monkeypatch, *, returncode=0, stdout="", stderr="", raises=None,
         script_exists=True):
    monkeypatch.setattr(
        "core.executors.script_executor.Path.exists", lambda self: script_exists
    )

    def fake_run(cmd, capture_output=None, text=None, timeout=None):
        if raises is not None:
            raise raises
        return _FakeCompleted(returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = make_script_runner("/fake/agent.py", timeout_sec=30)
    return runner(agent=object(), task="do thing", context="")


def test_script_runner_parses_last_json_line(monkeypatch):
    stdout = (
        "starting up\n"
        '{"success": true, "summary": "found 2", "details": "d", '
        '"items_found": 2, "items": [{"title": "a"}]}\n'
    )
    result = _run(monkeypatch, stdout=stdout)
    assert isinstance(result, RunResult)
    assert result.success is True
    assert result.summary == "found 2"
    assert result.items_found == 2


def test_script_runner_missing_script(monkeypatch):
    result = _run(monkeypatch, script_exists=False)
    assert result.success is False
    assert result.error == "script_not_found"


def test_script_runner_nonzero_exit(monkeypatch):
    result = _run(monkeypatch, returncode=1, stderr="traceback here")
    assert result.success is False
    assert result.error == "exit_1"
    assert "traceback here" in result.details


def test_script_runner_no_json_output(monkeypatch):
    result = _run(monkeypatch, stdout="just some text, no json\n")
    assert result.success is False
    assert result.error == "no_json"


def test_script_runner_timeout(monkeypatch):
    exc = subprocess.TimeoutExpired(cmd="x", timeout=30)
    result = _run(monkeypatch, raises=exc)
    assert result.success is False
    assert result.error == "timeout"
