from core.agent_state import AgentState


def _sample_state(**overrides):
    base = dict(
        role_id="github_watcher",
        instance_id="uuid-123",
        display_name="GitHub Watcher",
        icon="🔍",
        executor="tool_loop",
        script_path=None,
        trigger="scheduled",
        cadence={"interval_sec": 3600, "anchor_iso": "2026-05-14T15:00:00"},
        quota=None,
        persistence="persistent",
        notify="comm_log",
        status="active",
        next_fire_at="2026-05-14T16:00:00",
        last_fire_at=None,
        runs=0,
        history=[],
        created_at="2026-05-14T15:00:00",
    )
    base.update(overrides)
    return AgentState(**base)


def test_agent_state_round_trips_through_dict():
    state = _sample_state()
    restored = AgentState.from_dict(state.to_dict())
    assert restored == state


def test_agent_state_from_dict_tolerates_missing_optional_fields():
    minimal = {
        "role_id": "r1",
        "instance_id": "i1",
        "display_name": "R1",
        "icon": "🤖",
        "executor": "script",
        "trigger": "on_demand",
        "persistence": "session",
        "notify": "tts",
        "status": "active",
        "created_at": "2026-05-14T15:00:00",
    }
    state = AgentState.from_dict(minimal)
    assert state.script_path is None
    assert state.cadence is None
    assert state.quota is None
    assert state.next_fire_at is None
    assert state.last_fire_at is None
    assert state.runs == 0
    assert state.history == []


from core.agent_state import AgentStateStore


def test_store_save_and_load_round_trip(tmp_path):
    path = tmp_path / "agent_state.json"
    store = AgentStateStore(path=path)
    store.upsert(_sample_state(role_id="a"))
    store.upsert(_sample_state(role_id="b"))

    fresh = AgentStateStore(path=path)
    fresh.load()
    ids = sorted(s.role_id for s in fresh.all())
    assert ids == ["a", "b"]


def test_store_get_returns_none_for_unknown(tmp_path):
    store = AgentStateStore(path=tmp_path / "s.json")
    assert store.get("nope") is None


def test_store_drops_session_entries_on_load(tmp_path):
    path = tmp_path / "agent_state.json"
    store = AgentStateStore(path=path)
    store.upsert(_sample_state(role_id="keep", persistence="persistent"))
    store.upsert(_sample_state(role_id="drop", persistence="session"))

    fresh = AgentStateStore(path=path)
    fresh.load()
    ids = [s.role_id for s in fresh.all()]
    assert ids == ["keep"]


def test_store_keeps_persistent_entries_on_load(tmp_path):
    path = tmp_path / "agent_state.json"
    store = AgentStateStore(path=path)
    store.upsert(_sample_state(role_id="p1", persistence="persistent"))
    store.upsert(_sample_state(role_id="p2", persistence="persistent"))

    fresh = AgentStateStore(path=path)
    fresh.load()
    assert len(fresh.all()) == 2


def test_changed_signal_fires_on_upsert_and_remove(tmp_path):
    store = AgentStateStore(path=tmp_path / "s.json")
    hits = []
    store.changed.connect(lambda: hits.append(1))

    store.upsert(_sample_state(role_id="x"))
    assert len(hits) == 1

    store.remove("x")
    assert len(hits) == 2
