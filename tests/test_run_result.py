from core.executors.run_result import RunResult


def test_run_result_to_dict_round_trip():
    r = RunResult(success=True, summary="ok", details="full text",
                  items_found=3, items=[{"title": "x"}], error=None)
    d = r.to_dict()
    assert d == {
        "success": True, "summary": "ok", "details": "full text",
        "items_found": 3, "items": [{"title": "x"}], "error": None,
    }


def test_run_result_defaults():
    r = RunResult(success=False, summary="bad", details="")
    assert r.items_found == 0
    assert r.items == []
    assert r.error is None


def test_from_runner_output_passes_through_run_result():
    r = RunResult(success=True, summary="ok", details="d")
    assert RunResult.from_runner_output(r) is r


def test_from_runner_output_wraps_dict():
    out = {"success": False, "response": "boom"}
    r = RunResult.from_runner_output(out)
    assert r.success is False
    assert "boom" in r.details
    assert r.error == "runner_returned_dict"


def test_from_runner_output_wraps_unexpected_type():
    r = RunResult.from_runner_output(None)
    assert r.success is False
    assert r.error == "runner_returned_dict"
