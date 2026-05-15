"""Tests for the github_readme tool."""

from core.function_executor import executor


class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


def test_github_readme_accepts_owner_slash_repo(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _Resp(200, "# JARVIS\n\nReal README markdown.")

    monkeypatch.setattr("requests.get", fake_get)
    out = executor.execute("github_readme", {"repo": "Microsoft/JARVIS"})
    assert out["success"] is True
    assert out["data"]["repo"] == "Microsoft/JARVIS"
    assert out["data"]["readme"].startswith("# JARVIS")
    assert captured["url"] == "https://api.github.com/repos/Microsoft/JARVIS/readme"
    # Asks for raw markdown via Accept header (not HTML page)
    assert captured["headers"]["Accept"] == "application/vnd.github.raw"


def test_github_readme_parses_full_url(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kw: _Resp(200, "# from url"),
    )
    out = executor.execute(
        "github_readme",
        {"url": "https://github.com/dipeshpal/Jarvis_AI/tree/main/docs"},
    )
    assert out["success"] is True
    assert out["data"]["repo"] == "dipeshpal/Jarvis_AI"


def test_github_readme_rejects_unparseable(monkeypatch):
    out = executor.execute("github_readme", {"repo": "not-a-real-thing"})
    assert out["success"] is False
    assert "parse" in out["message"].lower() or "github" in out["message"].lower()


def test_github_readme_handles_rate_limit(monkeypatch):
    monkeypatch.setattr(
        "requests.get",
        lambda url, **kw: _Resp(403, "rate limited"),
    )
    out = executor.execute("github_readme", {"repo": "x/y"})
    assert out["success"] is False
    assert "rate" in out["message"].lower() or "403" in out["message"]


def test_github_readme_strips_git_suffix(monkeypatch):
    captured = {}
    def fake_get(url, **kw):
        captured["url"] = url
        return _Resp(200, "ok")
    monkeypatch.setattr("requests.get", fake_get)
    out = executor.execute("github_readme",
                           {"url": "https://github.com/owner/repo.git"})
    # The trailing .git should be stripped in the API URL.
    assert "/repo.git/" not in captured["url"]
    assert captured["url"].endswith("/repo/readme")
    assert out["success"] is True
