from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QTextEdit, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Slot, Signal
from PySide6.QtGui import QPixmap, QImage

from qfluentwidgets import (
    PrimaryPushButton, LineEdit, StrongBodyLabel, CaptionLabel,
    ScrollArea, CardWidget
)

from gui.components.thinking_expander import ThinkingExpander
from core.agent import BrowserAgent

class BrowserTab(QWidget):
    """
    Tab for controlling the AI Browser Agent.
    """
    # Signal to bridge GUI -> Worker thread
    run_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrowserTab")
        
        # Agent Threading
        self.agent_thread = QThread()
        self.agent = None # Will instantiate when needed
        
        self._setup_ui()
        self._setup_agent()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Left Column: Browser Viewport
        viewport_container = CardWidget(self)
        viewport_layout = QVBoxLayout(viewport_container)
        
        viewport_label = StrongBodyLabel("Live Browser View", self)
        viewport_layout.addWidget(viewport_label)
        
        self.image_label = QLabel("Browser not started")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: #202020; border-radius: 8px;")
        self.image_label.setMinimumSize(640, 360)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        viewport_layout.addWidget(self.image_label)
        
        layout.addWidget(viewport_container, stretch=3)

        # Right Column: Controls & Logs
        controls_container = QWidget()
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        # Status
        self.status_label = CaptionLabel("Status: Idle", self)
        controls_layout.addWidget(self.status_label)

        # Thinking Stream
        self.thinking_expander = ThinkingExpander(self)
        controls_layout.addWidget(self.thinking_expander)

        # Action Log
        log_label = StrongBodyLabel("Action Log", self)
        controls_layout.addWidget(log_label)
        
        self.action_log = QTextEdit()
        self.action_log.setReadOnly(True)
        self.action_log.setStyleSheet("font-family: Consolas; font-size: 11px;")
        controls_layout.addWidget(self.action_log)

        # Input Area
        input_layout = QHBoxLayout()
        self.url_input = LineEdit()
        self.url_input.setPlaceholderText("Enter instruction (e.g. 'Go to google.com and search...')")
        input_layout.addWidget(self.url_input)
        
        self.go_btn = PrimaryPushButton("Execute")
        self.go_btn.clicked.connect(self._on_execute)
        input_layout.addWidget(self.go_btn)
        
        controls_layout.addLayout(input_layout)
        
        layout.addWidget(controls_container, stretch=2)

    def _setup_agent(self):
        # Instantiate agent - model comes from settings now
        from core.settings_store import settings
        model_name = settings.get("models.web_agent", "qwen2.5vl:7b")
        self.agent = BrowserAgent(model_name=model_name) 
        self.agent.moveToThread(self.agent_thread)
        
        # Connect signals
        self.agent.screenshot_updated.connect(self._update_screenshot)
        self.agent.thinking_update.connect(self._update_thinking)
        self.agent.action_updated.connect(self._log_action)
        self.agent.finished.connect(self._on_finished)
        self.agent.error_occurred.connect(self._on_error)
        
        # Connect start signal (queued across threads automatically)
        self.run_signal.connect(self.agent.start_task)
        
        # Start thread
        self.agent_thread.start()

    def _on_execute(self):
        instruction = self.url_input.text()
        if not instruction.strip():
            return
            
        self.status_label.setText("Status: Running...")
        self.go_btn.setEnabled(False)
        self.action_log.clear()
        
        self.run_signal.emit(instruction)

    def closeEvent(self, event):
        if self.agent:
            self.agent.stop()
            self.agent.cleanup()
        self.agent_thread.quit()
        self.agent_thread.wait()
        super().closeEvent(event)

    # ------------------------------------------------------------------ Slots

    @Slot(QImage)
    def _update_screenshot(self, image: QImage):
        """
        Display a screenshot received from the browser agent worker thread.

        Guard against a zero-size label (can happen before the widget has
        been fully laid out) to avoid producing a null pixmap that would
        silently replace the live view with nothing.
        """
        if image.isNull():
            return

        pixmap = QPixmap.fromImage(image)

        # Clear the placeholder text the first time a real frame arrives
        if self.image_label.text():
            self.image_label.setText("")

        label_size = self.image_label.size()
        if label_size.width() > 0 and label_size.height() > 0:
            # Scale to fit the label while keeping the aspect ratio
            scaled = pixmap.scaled(
                label_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        else:
            # Label not yet laid out — display at native resolution
            scaled = pixmap

        self.image_label.setPixmap(scaled)

    @Slot(str)
    def _update_thinking(self, text):
        self.thinking_expander.add_text(text)

    @Slot(str)
    def _log_action(self, text):
        self.action_log.append(text)

    @Slot()
    def _on_finished(self):
        self.status_label.setText("Status: Finished")
        self.go_btn.setEnabled(True)
        self.thinking_expander.complete()

    @Slot(str)
    def _on_error(self, err):
        self.status_label.setText(f"Status: Error - {err}")
        self.action_log.append(f"ERROR: {err}")
        self.go_btn.setEnabled(True)
