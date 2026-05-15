import core.agent_runtime as ar


def test_get_runtime_is_singleton():
    ar._runtime = None  # reset
    r1 = ar.get_runtime()
    r2 = ar.get_runtime()
    assert r1 is r2


def test_runtime_exposes_store_scheduler_dispatcher():
    ar._runtime = None
    rt = ar.get_runtime()
    assert rt.store is not None
    assert rt.scheduler is not None
    assert rt.dispatcher is not None


def test_runtime_reporter_is_dispatcher_report():
    ar._runtime = None
    rt = ar.get_runtime()
    # the scheduler's reporter should be the dispatcher's report method
    assert rt.scheduler._reporter == rt.dispatcher.report
