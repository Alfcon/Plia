from core.agent_creator import WizardController, WizardStep


def make_wizard(task="watches GitHub for related projects"):
    # classify_fn is injected so no Ollama call happens in tests
    return WizardController(task, classify_fn=lambda t: "tool_loop")


def test_wizard_first_question_is_trigger():
    w = make_wizard()
    step = w.current_question()
    assert isinstance(step, WizardStep)
    assert "schedul" in step.question.lower()
    assert step.done is False


def test_wizard_scheduled_path_collects_cadence():
    w = make_wizard()
    w.answer("scheduled")
    step = w.current_question()
    assert "how often" in step.question.lower()
    w.answer("every 6 hours")          # cadence
    w.answer("persistent")             # persistence
    w.answer("communication log")      # notify
    step = w.answer("yes")             # confirm
    assert step.done is True
    answers = step.answers
    assert answers["trigger"] == "scheduled"
    assert answers["cadence"]["interval_sec"] == 21600
    assert answers["persistence"] == "persistent"
    assert answers["notify"] == "comm_log"
    assert answers["executor"] == "tool_loop"
    assert answers["tools"] == ["web_search", "http_get"]


def test_wizard_quota_path_collects_quota():
    w = make_wizard()
    w.answer("quota")
    step = w.current_question()
    assert "how many" in step.question.lower()
    w.answer("top 10")
    w.answer("session only")
    w.answer("speak")
    step = w.answer("yes")
    assert step.done is True
    assert step.answers["trigger"] == "quota"
    assert step.answers["quota"] == {"limit": 10, "criterion": "top_rated"}
    assert step.answers["persistence"] == "session"
    assert step.answers["notify"] == "tts"


def test_wizard_on_demand_skips_cadence_and_quota():
    w = make_wizard()
    w.answer("on demand")
    step = w.current_question()
    assert "survive restarts" in step.question.lower() \
        or "persist" in step.question.lower()
    w.answer("persistent")
    w.answer("toast")
    step = w.answer("yes")
    assert step.done is True
    assert step.answers["trigger"] == "on_demand"
    assert step.answers["cadence"] is None
    assert step.answers["quota"] is None


def test_wizard_reasks_on_unparseable_answer():
    w = make_wizard()
    step = w.answer("banana")
    assert step.done is False
    assert "schedul" in step.question.lower()  # still on trigger question


def test_wizard_cancel():
    w = make_wizard()
    step = w.answer("cancel")
    assert step.cancelled is True
    assert step.done is True


def test_wizard_confirm_no_restarts_at_trigger():
    w = make_wizard()
    w.answer("on demand")
    w.answer("persistent")
    w.answer("toast")
    step = w.answer("no")
    assert step.done is False
    assert "schedul" in step.question.lower()
