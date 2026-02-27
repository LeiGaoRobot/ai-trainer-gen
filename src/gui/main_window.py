"""
MainWindow — top-level application window for ai-trainer-gen GUI.

Uses a QStackedWidget to host four pages in a wizard-like flow:
  0  ProcessSelectPage  — pick the target game process
  1  FeatureConfigPage  — select trainer features
  2  GeneratePage       — watch generation progress
  3  ScriptManagerPage  — browse / export cached scripts

Navigation between pages is done programmatically via go_to(index).
"""

import logging
import os
import tempfile

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from src.gui.pages.process_select import ProcessSelectPage
from src.gui.pages.feature_config  import FeatureConfigPage
from src.gui.pages.generate        import GeneratePage
from src.gui.pages.script_manager  import ScriptManagerPage
from src.gui.worker import GenerateWorker
from src.store.db import ScriptStore

__all__ = ["MainWindow"]

logger = logging.getLogger(__name__)

# Page indices — keep in sync with the order they are added to the stack
PAGE_PROCESS_SELECT = 0
PAGE_FEATURE_CONFIG = 1
PAGE_GENERATE       = 2
PAGE_SCRIPT_MANAGER = 3


class MainWindow(QMainWindow):
    """Root window: hosts the QStackedWidget and wires page navigation."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Trainer Generator")
        self.resize(640, 480)

        # Persistent script store (redirectable in tests via tempfile patch)
        _db_path = os.path.join(tempfile.gettempdir(), "ai_trainer_gen.db")
        self._store = ScriptStore(_db_path)

        # Worker / thread references — kept to prevent premature GC
        self._thread: QThread | None = None
        self._worker: GenerateWorker | None = None

        self._build_ui()
        self._connect_navigation()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Instantiate pages and add to the stack (order matters)
        self._page_process  = ProcessSelectPage()
        self._page_features = FeatureConfigPage()
        self._page_generate = GeneratePage()
        self._page_scripts  = ScriptManagerPage()

        self._stack.addWidget(self._page_process)   # 0
        self._stack.addWidget(self._page_features)  # 1
        self._stack.addWidget(self._page_generate)  # 2
        self._stack.addWidget(self._page_scripts)   # 3

        self._stack.setCurrentIndex(PAGE_PROCESS_SELECT)

    # ── Navigation wiring ──────────────────────────────────────────────────

    def _connect_navigation(self) -> None:
        # ProcessSelectPage → FeatureConfigPage
        self._page_process._select_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

        # FeatureConfigPage → GeneratePage (via worker launch)
        self._page_features._generate_btn.clicked.connect(
            self._on_generate_clicked
        )

        # GeneratePage ← back to FeatureConfigPage
        self._page_generate._back_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

        # ScriptManagerPage ← back to FeatureConfigPage
        self._page_scripts._back_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

    # ── Generate pipeline ──────────────────────────────────────────────────

    def _on_generate_clicked(self) -> None:
        """Navigate to GeneratePage and launch the generation worker."""
        # Clean up any previous run
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)  # wait up to 3s

        proc = self._page_process._vm.selected
        exe_path = proc.exe_path if proc else ""

        features = list(self._page_features._vm.selected_features)
        custom = self._page_features._vm.custom_description.strip()
        if custom:
            features.append(custom)

        self.go_to(PAGE_GENERATE)
        self._page_generate.reset()
        self._page_generate._back_btn.setEnabled(False)

        self._worker = GenerateWorker(
            exe_path=exe_path,
            features=features,
            store=self._store,
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_emitted.connect(self._page_generate.append_log)
        self._worker.progress_updated.connect(self._page_generate.set_progress)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_generate_finished(self, lua_path: str) -> None:
        """Called when the worker emits finished(lua_path)."""
        self._page_generate._back_btn.setEnabled(True)
        self._page_generate.append_log(f"Script saved: {lua_path}")
        self._page_generate.set_progress(1.0)
        self.go_to(PAGE_SCRIPT_MANAGER)

    def _on_generate_failed(self, error: str) -> None:
        """Called when the worker emits failed(error); stays on GeneratePage."""
        self._page_generate._back_btn.setEnabled(True)
        self._page_generate.append_log(f"Error: {error}")
        # Stay on GeneratePage so user can read the error

    # ── Public API ─────────────────────────────────────────────────────────

    def go_to(self, page_index: int) -> None:
        """Switch the visible page to *page_index*."""
        self._stack.setCurrentIndex(page_index)
