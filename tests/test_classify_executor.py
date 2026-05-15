import core.agent_creator as ac


class _Resp:
    def __init__(self, content):
        self._content = content
    def raise_for_status(self):
        pass
    def json(self):
        return {"message": {"content": self._content}}


def test_classify_returns_script(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("script"))
    assert ac.classify_executor("download files to a folder",
                                "http://x/api", "m") == "script"


def test_classify_returns_tool_loop(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("tool_loop"))
    assert ac.classify_executor("research and compare LLM repos",
                                "http://x/api", "m") == "tool_loop"


def test_classify_tolerates_extra_text(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("I think this is: script."))
    assert ac.classify_executor("x", "http://x/api", "m") == "script"


def test_classify_defaults_to_tool_loop_on_unparseable(monkeypatch):
    monkeypatch.setattr(ac.requests, "post",
                        lambda *a, **k: _Resp("no idea"))
    assert ac.classify_executor("x", "http://x/api", "m") == "tool_loop"


def test_classify_defaults_to_tool_loop_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(ac.requests, "post", boom)
    assert ac.classify_executor("x", "http://x/api", "m") == "tool_loop"
