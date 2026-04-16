"""
Reading Files Tab — Plia GUI

Allows users to load files from disk, view a numbered list of loaded
files, and read any file by clicking it or typing "read option N".

Supported read strategies:
  • .txt / .md / .log / code → plain text (up to 8 KB preview)
  • .pdf                      → pdfplumber text extraction
  • .docx                     → python-docx paragraph extraction
  • .xlsx / .csv              → pandas tabular preview
  • .json / .jsonl            → pretty-print first 40 lines
  • everything else           → hex / magic-byte info only
"""

from __future__ import annotations

import os
import json
import re
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QListWidgetItem, QSizePolicy, QFileDialog, QSplitter,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QFont, QColor

from qfluentwidgets import (
    PrimaryPushButton, PushButton, TransparentToolButton,
    ListWidget, ScrollArea, TextEdit,
    FluentIcon as FIF, CardWidget, SubtitleLabel, BodyLabel,
    CaptionLabel, StrongBodyLabel,
)


# ─────────────────────────────────────────────────────────────────────────────
# Signals bridge (worker → main thread)
# ─────────────────────────────────────────────────────────────────────────────

class _WorkerSignals(QObject):
    content_ready = Signal(str, str)   # (file_key, extracted_text)
    error         = Signal(str, str)   # (file_key, error_msg)


# ─────────────────────────────────────────────────────────────────────────────
# File-reading helpers
# ─────────────────────────────────────────────────────────────────────────────

PREVIEW_CHARS = 6_000  # chars shown in the UI text panel


def _read_text_file(path: str) -> str:
    """Read plain text / code / markdown file."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _read_pdf(path: str) -> str:
    """Extract text from PDF using pdfplumber (preferred) or pypdf fallback."""
    try:
        import pdfplumber
        lines: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines.append(text)
        return "\n".join(lines) or "(No extractable text found in PDF)"
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n".join(pages) or "(No extractable text found in PDF)"
    except Exception as exc:
        return f"(PDF read error: {exc})"


def _read_docx(path: str) -> str:
    """Extract paragraphs from a .docx file."""
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        return f"(DOCX read error: {exc})"


def _read_spreadsheet(path: str) -> str:
    """Return a tabular text preview for .xlsx or .csv."""
    try:
        import pandas as pd
        ext = Path(path).suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(path, nrows=50)
        else:
            df = pd.read_excel(path, nrows=50)
        shape_info = f"Shape (preview): {df.shape[0]} rows × {df.shape[1]} cols\n\n"
        return shape_info + df.to_string(index=False, max_cols=20)
    except Exception as exc:
        return f"(Spreadsheet read error: {exc})"


def _read_json(path: str) -> str:
    """Pretty-print JSON / JSONL."""
    ext = Path(path).suffix.lower()
    try:
        if ext == ".jsonl":
            lines: list[str] = []
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i >= 40:
                        lines.append("… (truncated)")
                        break
                    try:
                        lines.append(json.dumps(json.loads(line), indent=2))
                    except json.JSONDecodeError:
                        lines.append(line.rstrip())
            return "\n".join(lines)
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read(12_000)
            data = json.loads(raw)
            return json.dumps(data, indent=2)[:12_000]
    except Exception as exc:
        return f"(JSON read error: {exc})"


def _read_generic(path: str) -> str:
    """Return file-type info + hex header for unrecognised binary files."""
    import subprocess
    info_lines = [f"File: {path}", f"Size: {os.path.getsize(path):,} bytes"]
    try:
        result = subprocess.run(["file", path], capture_output=True, text=True, timeout=5)
        info_lines.append(f"Type: {result.stdout.strip()}")
    except Exception:
        pass
    try:
        with open(path, "rb") as fh:
            raw = fh.read(64)
        hex_str = " ".join(f"{b:02x}" for b in raw)
        info_lines.append(f"\nHex header:\n{hex_str}")
    except Exception:
        pass
    return "\n".join(info_lines)


def extract_file_content(path: str) -> str:
    """Dispatch to the appropriate reader based on file extension."""
    ext = Path(path).suffix.lower()
    text_exts = {
        ".txt", ".md", ".markdown", ".log", ".py", ".js", ".ts",
        ".html", ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".sh", ".bat", ".rs", ".go", ".cpp", ".c", ".h", ".java",
        ".xml", ".sql", ".r", ".tex",
    }
    if ext in text_exts:
        return _read_text_file(path)
    if ext == ".pdf":
        return _read_pdf(path)
    if ext in {".docx", ".doc"}:
        return _read_docx(path)
    if ext in {".xlsx", ".xls", ".xlsm", ".csv"}:
        return _read_spreadsheet(path)
    if ext in {".json", ".jsonl"}:
        return _read_json(path)
    try:
        return _read_text_file(path)
    except UnicodeDecodeError:
        return _read_generic(path)


# ─────────────────────────────────────────────────────────────────────────────
# ReadingFilesTab
# ─────────────────────────────────────────────────────────────────────────────

class ReadingFilesTab(QWidget):
    """
    Tab that lets users load, list, and read files.

    Public interface used by MainWindow / voice handler:
        read_option(n: int)  — read the nth file in the list (1-indexed)
    """

    # Signal emitted when a file is fully loaded (path, content)
    file_read = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("readingFilesInterface")

        # {file_key: {"path": str, "content": str}}
        self._files: dict[str, dict] = {}
        self._selected_key: Optional[str] = None
        self._signals = _WorkerSignals()

        self._setup_ui()
        self._connect_signals()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Header bar ──────────────────────────────────────────────────────
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet("background: transparent;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(10)

        title = SubtitleLabel("Reading Files")
        title.setStyleSheet("color: #e8eaed; font-size: 18px; font-weight: 600;")
        h_layout.addWidget(title)
        h_layout.addStretch()

        self.load_btn = PrimaryPushButton(FIF.FOLDER, "Load Files")
        self.load_btn.setFixedHeight(36)
        h_layout.addWidget(self.load_btn)

        self.clear_btn = PushButton(FIF.DELETE, "Clear All")
        self.clear_btn.setFixedHeight(36)
        h_layout.addWidget(self.clear_btn)

        root.addWidget(header)

        # ── Hint label ──────────────────────────────────────────────────────
        hint = CaptionLabel(
            "Load files, then click an entry or type  \"read option 1\"  to read it."
        )
        hint.setStyleSheet("color: #4a5568; margin-bottom: 4px;")
        root.addWidget(hint)

        # ── Splitter: file list (left) | content panel (right) ──────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #1a2236; width: 2px; }"
        )

        # Left — file list
        list_frame = QFrame()
        list_frame.setMinimumWidth(260)
        list_frame.setMaximumWidth(380)
        list_frame.setStyleSheet(
            "background: #0f1524; border: 1px solid #1a2236; border-radius: 10px;"
        )
        lf_layout = QVBoxLayout(list_frame)
        lf_layout.setContentsMargins(8, 8, 8, 8)
        lf_layout.setSpacing(6)

        list_header = StrongBodyLabel("Loaded Files")
        list_header.setStyleSheet("color: #8b9bb4; font-size: 12px; padding: 2px 4px;")
        lf_layout.addWidget(list_header)

        self.file_list = ListWidget()
        self.file_list.setStyleSheet(
            "background: transparent; border: none; color: #e8eaed;"
        )
        self.file_list.setSpacing(2)
        lf_layout.addWidget(self.file_list)

        self._empty_label = BodyLabel("No files loaded yet.\nClick  Load Files  to begin.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #4a5568; font-size: 13px;")
        lf_layout.addWidget(self._empty_label)

        splitter.addWidget(list_frame)

        # Right — content panel
        right_frame = QFrame()
        right_frame.setStyleSheet(
            "background: #0f1524; border: 1px solid #1a2236; border-radius: 10px;"
        )
        rf_layout = QVBoxLayout(right_frame)
        rf_layout.setContentsMargins(12, 12, 12, 12)
        rf_layout.setSpacing(8)

        # File name label at top of content pane
        self._content_title = StrongBodyLabel("Select a file to read it")
        self._content_title.setStyleSheet(
            "color: #33b5e5; font-size: 14px; font-weight: 600;"
        )
        rf_layout.addWidget(self._content_title)

        # Raw content scroll area
        self._content_scroll = ScrollArea()
        self._content_scroll.setWidgetResizable(True)
        self._content_scroll.setStyleSheet("background: transparent; border: none;")
        self._content_scroll.viewport().setStyleSheet("background: transparent;")

        self._content_edit = TextEdit()
        self._content_edit.setReadOnly(True)
        self._content_edit.setStyleSheet(
            "TextEdit { background: transparent; border: none;"
            " color: #c0cce0; font-family: 'Consolas', monospace; font-size: 12px; }"
        )
        self._content_edit.setPlaceholderText(
            "File contents will appear here after you select a file."
        )
        self._content_scroll.setWidget(self._content_edit)
        rf_layout.addWidget(self._content_scroll, 1)

        splitter.addWidget(right_frame)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 700])

        root.addWidget(splitter, 1)

        # ── Status bar ───────────────────────────────────────────────────────
        self._status_label = CaptionLabel("Ready")
        self._status_label.setStyleSheet("color: #4a5568;")
        root.addWidget(self._status_label)

    # ── Signal wiring ────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self.load_btn.clicked.connect(self._on_load_clicked)
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        self.file_list.itemClicked.connect(self._on_item_clicked)
        self._signals.content_ready.connect(self._on_content_ready)
        self._signals.error.connect(self._on_worker_error)

    # ── Slots / event handlers ───────────────────────────────────────────────

    def _on_load_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Load Files",
            "",
            "All Files (*.*);;"
            "Text & Code (*.txt *.md *.py *.js *.ts *.html *.css *.yaml *.yml *.json *.log);;"
            "Documents (*.pdf *.docx *.doc);;"
            "Spreadsheets (*.xlsx *.xls *.csv);;"
            "Data (*.json *.jsonl *.xml)",
        )
        for path in paths:
            self._add_file(path)

    def _on_clear_clicked(self) -> None:
        self._files.clear()
        self._selected_key = None
        self.file_list.clear()
        self._content_title.setText("Select a file to read it")
        self._content_edit.clear()
        self._empty_label.setVisible(True)
        self._set_status("All files cleared.")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key:
            self._display_file(key)

    def _on_content_ready(self, key: str, content: str) -> None:
        if key in self._files:
            self._files[key]["content"] = content
        self._rebuild_list()
        if key == self._selected_key:
            self._show_content(key)

    def _on_worker_error(self, key: str, msg: str) -> None:
        self._set_status(f"⚠ {msg}")

    # ── Core methods ─────────────────────────────────────────────────────────

    def _add_file(self, path: str) -> None:
        """Add a file to the list (lazy — content extracted on selection)."""
        key = path
        if key in self._files:
            self._set_status(f"Already loaded: {Path(path).name}")
            return

        self._files[key] = {"path": path, "content": None}
        self._rebuild_list()
        self._empty_label.setVisible(False)
        self._set_status(f"Loaded: {Path(path).name}")

    def _rebuild_list(self) -> None:
        """Rebuild the QListWidget from _files dict preserving insertion order."""
        self.file_list.clear()
        for idx, (key, meta) in enumerate(self._files.items(), start=1):
            name = Path(meta["path"]).name
            ext  = Path(meta["path"]).suffix.lower()
            icon = self._icon_for_ext(ext)
            label = f"{idx}.  {name}"
            if meta["content"] is not None:
                label += "  ✓"
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(meta["path"])
            self.file_list.addItem(item)

    def _display_file(self, key: str) -> None:
        """Show content for the given key; extract first if not yet done."""
        self._selected_key = key
        meta = self._files[key]
        self._content_title.setText(Path(meta["path"]).name)

        if meta["content"] is None:
            self._set_status(f"Reading {Path(meta['path']).name}…")
            self._content_edit.setPlainText("Reading file…")

            def _worker():
                try:
                    content = extract_file_content(meta["path"])
                    self._signals.content_ready.emit(key, content)
                except Exception as exc:
                    self._signals.error.emit(key, str(exc))

            threading.Thread(target=_worker, daemon=True).start()
        else:
            self._show_content(key)

    def _show_content(self, key: str) -> None:
        """Render extracted content in the UI (main thread)."""
        meta = self._files[key]
        content = meta["content"] or ""
        preview = content[:PREVIEW_CHARS]
        if len(content) > PREVIEW_CHARS:
            preview += f"\n\n… (truncated — {len(content):,} chars total)"
        self._content_edit.setPlainText(preview)
        self._set_status(
            f"{Path(meta['path']).name}  |  {len(content):,} chars"
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def read_option(self, n: int) -> None:
        """
        Read the nth file (1-indexed).  Called by voice / chat handler when
        the user says or types "read option N".
        """
        keys = list(self._files.keys())
        if not keys:
            self._set_status("No files loaded. Use  Load Files  first.")
            return
        if n < 1 or n > len(keys):
            self._set_status(
                f"Option {n} out of range — {len(keys)} file(s) loaded."
            )
            return
        key = keys[n - 1]
        # Scroll list to that item and highlight it
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.file_list.setCurrentItem(item)
                break
        self._display_file(key)

    def read_option_with_callback(self, n: int, on_ready=None) -> None:
        """
        Like read_option() but also calls on_ready(filename, content) once
        extraction completes.  Safe to call from the main thread.

        - If content is already cached  → on_ready is called immediately.
        - If background extraction is running → a one-shot slot is wired to
          _signals.content_ready that fires on_ready when the worker finishes,
          then disconnects itself so it cannot fire again.
        - If on_ready is None            → behaves identically to read_option().
        """
        keys = list(self._files.keys())
        if not keys:
            self._set_status("No files loaded. Use  Load Files  first.")
            return
        if n < 1 or n > len(keys):
            self._set_status(
                f"Option {n} out of range — {len(keys)} file(s) loaded."
            )
            return

        key  = keys[n - 1]
        meta = self._files[key]
        filename = Path(meta["path"]).name

        # Trigger the normal UI display (scrolls list, starts worker if needed)
        self.read_option(n)

        if on_ready is None:
            return

        if meta["content"] is not None:
            # Content already extracted — deliver immediately
            on_ready(filename, meta["content"])
        else:
            # Content is being extracted in a background thread.
            # Wire a one-shot slot that fires once the worker signals back.
            def _slot(ready_key: str, content: str) -> None:
                if ready_key == key:
                    try:
                        self._signals.content_ready.disconnect(_slot)
                    except RuntimeError:
                        pass  # already disconnected — safe to ignore
                    on_ready(filename, content)

            self._signals.content_ready.connect(_slot)

    def parse_read_command(self, text: str) -> Optional[int]:
        """
        Parse a text command like "read option 1", "read file 2", "option 3".
        Returns the 1-based index or None if not matched.
        """
        text = text.lower().strip()
        patterns = [
            r"read\s+option\s+(\d+)",
            r"read\s+file\s+(\d+)",
            r"open\s+option\s+(\d+)",
            r"open\s+file\s+(\d+)",
            r"^option\s+(\d+)$",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return int(m.group(1))
        return None

    def handle_user_command(self, text: str) -> bool:
        """
        Intercept a user text command.  Returns True if handled.
        Meant to be called from the chat send handler before routing to LLM.
        """
        n = self.parse_read_command(text)
        if n is not None:
            self.read_option(n)
            return True
        return False

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _icon_for_ext(ext: str) -> "QIcon":
        """Map file extension to a FIF icon."""
        mapping = {
            ".pdf":  FIF.DOCUMENT,
            ".docx": FIF.DOCUMENT,
            ".doc":  FIF.DOCUMENT,
            ".xlsx": FIF.LAYOUT,
            ".xls":  FIF.LAYOUT,
            ".csv":  FIF.LAYOUT,
            ".json": FIF.CODE,
            ".jsonl": FIF.CODE,
            ".py":   FIF.CODE,
            ".js":   FIF.CODE,
            ".ts":   FIF.CODE,
            ".md":   FIF.DOCUMENT,
            ".txt":  FIF.DOCUMENT,
        }
        fif = mapping.get(ext, FIF.FOLDER)
        return fif.icon()

    def _set_status(self, msg: str) -> None:
        QTimer.singleShot(0, lambda: self._status_label.setText(msg))
