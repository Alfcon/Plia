"""Backend dispatch for the web_search tool."""

from core.function_executor import executor


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_search_uses_brave_when_key_is_set(monkeypatch):
    """When settings.search.backend=brave and a key is present, hit Brave."""
    from core.settings_store import settings
    monkeypatch.setattr(settings, "get", lambda key, default=None: {
        "search.backend": "brave",
        "search.brave_api_key": "test-key",
    }.get(key, default))

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        return _Resp(200, {
            "web": {"results": [
                {"title": "Acme Repo", "url": "https://github.com/acme/repo",
                 "description": "A great repo"},
            ]}
        })

    monkeypatch.setattr("requests.get", fake_get)
    out = executor.execute("web_search", {"query": "JARVIS projects"})
    assert out["success"] is True
    assert out["data"]["backend"] == "brave"
    assert out["data"]["results"][0]["url"] == "https://github.com/acme/repo"
    # Brave-specific assertions: correct endpoint + auth header
    assert captured["url"].startswith("https://api.search.brave.com")
    assert captured["headers"]["X-Subscription-Token"] == "test-key"


def test_search_falls_back_to_ddg_when_brave_fails(monkeypatch):
    """Brave HTTP error → fall back to DuckDuckGo automatically."""
    from core.settings_store import settings
    monkeypatch.setattr(settings, "get", lambda key, default=None: {
        "search.backend": "brave",
        "search.brave_api_key": "bad-key",
    }.get(key, default))

    def brave_fail(url, params=None, headers=None, timeout=None):
        return _Resp(401, {"error": "unauthorized"})

    monkeypatch.setattr("requests.get", brave_fail)

    # Stub DDGS so we don't hit the network during tests.
    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, q, max_results=20):
            return [{"title": "from-ddg", "body": "x", "href": "https://example.com"}]

    import sys, types
    fake_mod = types.SimpleNamespace(DDGS=FakeDDGS)
    monkeypatch.setitem(sys.modules, "ddgs", fake_mod)

    out = executor.execute("web_search", {"query": "JARVIS projects"})
    assert out["success"] is True
    assert out["data"]["backend"] == "duckduckgo"
    assert out["data"]["results"][0]["title"] == "from-ddg"


def test_search_auto_picks_ddg_when_no_brave_key(monkeypatch):
    """backend=auto + empty key → DuckDuckGo (no Brave call attempted)."""
    from core.settings_store import settings
    monkeypatch.setattr(settings, "get", lambda key, default=None: {
        "search.backend": "auto",
        "search.brave_api_key": "",
    }.get(key, default))

    brave_called = {"hit": False}

    def fake_get(*a, **k):
        brave_called["hit"] = True
        return _Resp(200, {"web": {"results": []}})

    monkeypatch.setattr("requests.get", fake_get)

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def text(self, q, max_results=20):
            return [{"title": "ddg", "body": "x", "href": "u"}]

    import sys, types
    monkeypatch.setitem(sys.modules, "ddgs",
                        types.SimpleNamespace(DDGS=FakeDDGS))

    out = executor.execute("web_search", {"query": "x"})
    assert out["success"] is True
    assert out["data"]["backend"] == "duckduckgo"
    assert brave_called["hit"] is False
