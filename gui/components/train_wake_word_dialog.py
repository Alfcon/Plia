"""Modal that runs core.wake_trainer.train_wake_word in a QThread."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSlider,
    QPushButton, QProgressBar, QListWidget, QListWidgetItem,
)

from core.wake_trainer import (
    DEFAULT_VOICES, train_wake_word, TrainCancelled, WakeTrainerError,
)


class _Worker(QObject):
    progress = Signal(float, str)
    finished = Signal(object)   # Path on success, None on cancel
    error = Signal(str)

    def __init__(self, word: str, variants: int, voices: list[str]):
        super().__init__()
        self._word = word
        self._variants = variants
        self._voices = voices
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    @Slot()
    def run(self) -> None:
        try:
            path = train_wake_word(
                self._word,
                variants=self._variants,
                voices=self._voices,
                on_progress=lambda pct, msg: self.progress.emit(pct, msg),
                should_cancel=lambda: self._cancel,
            )
            self.finished.emit(path)
        except TrainCancelled:
            self.finished.emit(None)
        except WakeTrainerError as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"unexpected: {exc}")


class TrainWakeWordDialog(QDialog):
    """Modal: type a word, click Train, watch progress, get an .onnx."""

    trained = Signal(object)   # Path of the new model; emitted on success

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Train new wake word")
        self.setMinimumWidth(520)

        outer = QVBoxLayout(self)

        outer.addWidget(QLabel("Word:", self))
        self.word_input = QLineEdit(self)
        self.word_input.setPlaceholderText("e.g. plia")
        outer.addWidget(self.word_input)

        row = QHBoxLayout()
        row.addWidget(QLabel("Variants:", self))
        self.variants_slider = QSlider(Qt.Horizontal, self)
        self.variants_slider.setRange(500, 20000)
        self.variants_slider.setValue(5000)
        self.variants_label = QLabel("5000", self)
        self.variants_slider.valueChanged.connect(
            lambda v: self.variants_label.setText(str(v))
        )
        row.addWidget(self.variants_slider, 1)
        row.addWidget(self.variants_label)
        outer.addLayout(row)

        outer.addWidget(QLabel("Voices:", self))
        self.voice_list = QListWidget(self)
        for v in DEFAULT_VOICES:
            item = QListWidgetItem(v)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.voice_list.addItem(item)
        self.voice_list.setMaximumHeight(120)
        outer.addWidget(self.voice_list)

        self.stage_label = QLabel("", self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        outer.addWidget(self.stage_label)
        outer.addWidget(self.progress_bar)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #ef5350;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel", self)
        self.train_btn = QPushButton("Train", self)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.train_btn)
        outer.addLayout(btn_row)

        self.train_btn.clicked.connect(self._on_train)
        self.cancel_btn.clicked.connect(self._on_cancel)

        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None

    def _selected_voices(self) -> list[str]:
        out: list[str] = []
        for i in range(self.voice_list.count()):
            item = self.voice_list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.text())
        return out

    def _on_train(self) -> None:
        word = self.word_input.text().strip()
        if not word:
            self.error_label.setText("Word is required.")
            return
        voices = self._selected_voices()
        if not voices:
            self.error_label.setText("Select at least one voice.")
            return
        self.error_label.setText("")
        self.train_btn.setEnabled(False)
        self._start_worker()

    def _start_worker(self) -> None:
        word = self.word_input.text().strip()
        variants = self.variants_slider.value()
        voices = self._selected_voices()

        self._thread = QThread(self)
        self._worker = _Worker(word, variants, voices)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()

    def _on_progress(self, pct: float, msg: str) -> None:
        self.progress_bar.setValue(int(pct))
        self.stage_label.setText(msg)

    def _on_finished(self, path) -> None:
        self._thread.quit()
        self._thread.wait()
        if path is None:
            self.reject()
        else:
            self.trained.emit(path)
            self.accept()

    def _on_error(self, msg: str) -> None:
        self._thread.quit()
        self._thread.wait()
        self.error_label.setText(msg)
        self.train_btn.setEnabled(True)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
        else:
            self.reject()
