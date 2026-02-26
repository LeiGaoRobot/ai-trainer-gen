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

from PyQt6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from src.gui.pages.process_select import ProcessSelectPage
from src.gui.pages.feature_config  import FeatureConfigPage
from src.gui.pages.generate        import GeneratePage
from src.gui.pages.script_manager  import ScriptManagerPage

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

        # FeatureConfigPage → GeneratePage
        self._page_features._generate_btn.clicked.connect(
            lambda: self.go_to(PAGE_GENERATE)
        )

        # GeneratePage ← back to FeatureConfigPage
        self._page_generate._back_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

        # ScriptManagerPage ← back to FeatureConfigPage
        self._page_scripts._back_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def go_to(self, page_index: int) -> None:
        """Switch the visible page to *page_index*."""
        self._stack.setCurrentIndex(page_index)
