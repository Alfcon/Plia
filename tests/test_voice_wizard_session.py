from core.agent_creator import VoiceWizardSession


def test_voice_session_speaks_first_question_on_start():
    spoken = []
    done = []
    cancelled = []
    sess = VoiceWizardSession(
        task="watches GitHub for related projects",
        classify_fn=lambda t: "tool_loop",
        speak=spoken.append,
        on_done=done.append,
        on_cancel=lambda: cancelled.append(True),
    )
    sess.start()
    assert len(spoken) == 1
    assert "schedul" in spoken[0].lower()


def test_voice_session_walks_to_completion():
    spoken = []
    done = []
    sess = VoiceWizardSession(
        task="watches GitHub for related projects",
        classify_fn=lambda t: "tool_loop",
        speak=spoken.append,
        on_done=done.append,
        on_cancel=lambda: None,
    )
    sess.start()
    sess.answer("on demand")
    sess.answer("persistent")
    sess.answer("communication log")
    sess.answer("yes")
    assert len(done) == 1
    assert done[0]["trigger"] == "on_demand"
    assert sess.finished is True


def test_voice_session_cancel():
    cancelled = []
    sess = VoiceWizardSession(
        task="watches GitHub for related projects",
        classify_fn=lambda t: "tool_loop",
        speak=lambda s: None,
        on_done=lambda a: None,
        on_cancel=lambda: cancelled.append(True),
    )
    sess.start()
    sess.answer("cancel")
    assert cancelled == [True]
    assert sess.finished is True
