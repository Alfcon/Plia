from core.function_executor import executor


class _FakeResponse:
    def __init__(self, status_code, text, url, ok=True):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.ok = ok


def test_http_get_rejects_missing_url():
    result = executor.execute("http_get", {})
    assert result["success"] is False
    assert "url" in result["message"].lower()


def test_http_get_rejects_non_http_scheme():
    result = executor.execute("http_get", {"url": "file:///etc/passwd"})
    assert result["success"] is False


def test_http_get_returns_body_and_status(monkeypatch):
    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        return _FakeResponse(200, "hello world", url, ok=True)

    monkeypatch.setattr("requests.get", fake_get)
    result = executor.execute("http_get", {"url": "https://example.com"})
    assert result["success"] is True
    assert result["data"]["status_code"] == 200
    assert result["data"]["body"] == "hello world"


def test_http_get_caps_body_size(monkeypatch):
    big = "x" * 500_000

    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        return _FakeResponse(200, big, url, ok=True)

    monkeypatch.setattr("requests.get", fake_get)
    result = executor.execute("http_get", {"url": "https://example.com"})
    assert len(result["data"]["body"]) == 100_000


def test_http_get_handles_request_exception(monkeypatch):
    def fake_get(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("requests.get", fake_get)
    result = executor.execute("http_get", {"url": "https://example.com"})
    assert result["success"] is False
    assert "connection refused" in result["message"]
