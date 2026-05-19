"""TrainWakeWordDialog UI smoke tests."""

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_dialog_has_word_input_and_buttons(qapp):
    from gui.components.train_wake_word_dialog import TrainWakeWordDialog
    dlg = TrainWakeWordDialog()
    assert dlg.word_input is not None
    assert dlg.variants_slider is not None
    assert dlg.train_btn is not None
    assert dlg.cancel_btn is not None
    assert dlg.progress_bar is not None


def test_dialog_train_emits_started_signal(qapp, monkeypatch):
    """Clicking Train with a valid word kicks off the worker thread.
    We mock the worker so the test doesn't actually train."""
    from gui.components.train_wake_word_dialog import TrainWakeWordDialog
    dlg = TrainWakeWordDialog()
    dlg.word_input.setText("plia")

    started = {"n": 0}
    monkeypatch.setattr(
        dlg, "_start_worker", lambda: started.__setitem__("n", started["n"] + 1)
    )
    dlg.train_btn.click()
    assert started["n"] == 1


def test_dialog_rejects_empty_word(qapp):
    from gui.components.train_wake_word_dialog import TrainWakeWordDialog
    dlg = TrainWakeWordDialog()
    dlg.word_input.setText("")
    dlg.train_btn.click()
    qapp.processEvents()
    # Train button stays enabled; an inline error label is shown.
    assert dlg.error_label.text() != ""
    assert dlg.train_btn.isEnabled()
