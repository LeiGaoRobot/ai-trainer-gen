"""
GeneratePage — page 3 of the trainer GUI.

Displays a scrollable log of LLM generation output and a progress bar.
The "Back" button returns to FeatureConfigPage.

Layout
──────
  ┌─────────────────────────────────────────┐
  │ Generation Log:                         │
  │ ┌─────────────────────────────────────┐ │
  │ │ [Step 1] Scanning process memory…   │ │
  │ │ [Step 2] Resolving AOB signature…   │ │
  │ │ …                                   │ │
  │ └─────────────────────────────────────┘ │
  │ [████████░░░░░░░░░░░░] 42 %            │
  │                                [← Back] │
  └─────────────────────────────────────────┘
"""

import logging

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.viewmodels import GenerateViewModel, GenerateState

__all__ = ["GeneratePage"]

logger = logging.getLogger(__name__)


class GeneratePage(QWidget):
    """Third page: watch the LLM generate the Lua trainer script."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._vm = GenerateViewModel()
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Title
        layout.addWidget(QLabel("<b>Generation Log</b>"))

        # Log display
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setPlaceholderText("Generation output will appear here…")
        layout.addWidget(self._log_view)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Back button
        btn_row = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        btn_row.addWidget(self._back_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── Public helpers ──────────────────────────────────────────────────────

    def append_log(self, message: str) -> None:
        """Append a line to the log display and update the ViewModel."""
        self._vm.append_log(message)
        self._log_view.appendPlainText(message)

    def set_progress(self, value: float) -> None:
        """Set progress (0.0 – 1.0) and update the progress bar."""
        self._vm.set_progress(value)
        self._progress_bar.setValue(int(self._vm.progress * 100))

    def reset(self) -> None:
        """Reset log and progress for a fresh generation run."""
        self._vm.start()
        self._log_view.clear()
        self._progress_bar.setValue(0)
