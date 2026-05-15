import yaml

from core.agent_creator import write_role_yaml, commit
from core.agent_state import AgentState, AgentStateStore


def test_write_role_yaml_creates_valid_file(tmp_path):
    path = write_role_yaml(
        roles_dir=tmp_path,
        slug="github_watcher",
        display_name="GitHub Watcher",
        task="watches GitHub for related projects",
        tools=["web_search", "http_get"],
    )
    assert path.exists()
    raw = yaml.safe_load(path.read_text())
    assert raw["id"] == "github_watcher"
    assert raw["name"] == "GitHub Watcher"
    assert raw["tools"] == ["web_search", "http_get"]
    assert raw["authority_level"] == 1
    assert "watches GitHub" in raw["heartbeat_instructions"]


def test_write_role_yaml_dedupes_slug(tmp_path):
    write_role_yaml(roles_dir=tmp_path, slug="dup", display_name="Dup",
                    task="does a thing here", tools=["web_search"])
    path2 = write_role_yaml(roles_dir=tmp_path, slug="dup", display_name="Dup",
                            task="does a thing here", tools=["web_search"])
    assert path2.stem == "dup_2"


def test_commit_writes_state_and_arms_scheduler(tmp_path):
    store = AgentStateStore(path=tmp_path / "state.json")
    armed = []

    class FakeScheduler:
        def arm(self, state):
            armed.append(state.role_id)

    class FakeInstance:
        id = "inst-1"

    class FakeMAS:
        def __init__(self):
            self.reloaded = False
        def reload_roles(self):
            self.reloaded = True
        def _add(self):
            pass

    answers = {
        "task": "watches GitHub for related projects",
        "trigger": "scheduled",
        "cadence": {"interval_sec": 21600, "anchor_iso": None},
        "quota": None,
        "persistence": "persistent",
        "notify": "comm_log",
        "executor": "tool_loop",
        "tools": ["web_search", "http_get"],
    }
    mas = FakeMAS()
    state = commit(
        answers,
        roles_dir=tmp_path,
        state_store=store,
        scheduler=FakeScheduler(),
        multi_agent_system=mas,
        instance_factory=lambda role_id, display_name: FakeInstance(),
        script_path=None,
    )
    assert isinstance(state, AgentState)
    assert state.trigger == "scheduled"
    assert state.executor == "tool_loop"
    assert state.persistence == "persistent"
    assert store.get(state.role_id) is not None
    assert armed == [state.role_id]
    assert mas.reloaded is True
    # role yaml was written
    assert (tmp_path / f"{state.role_id}.yml").exists()
