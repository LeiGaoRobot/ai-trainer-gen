"""
ProcessSelectPage — page 1 of the trainer GUI.

Lets the user pick a running game process.  Refreshing the list calls
EngineDetector on the selected executable to identify the engine.

Layout
──────
  ┌─────────────────────────────────────────┐
  │ [🔍 Filter...]                          │
  │ ┌─────────────────────────────────────┐ │
  │ │ MyGame.exe (pid=1234)  Unity_Mono   │ │
  │ │ OtherGame.exe (pid=5)  Unknown      │ │
  │ └─────────────────────────────────────┘ │
  │         [Refresh]  [Select →]           │
  └─────────────────────────────────────────┘
"""

import logging

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.viewmodels import ProcessListViewModel

__all__ = ["ProcessSelectPage"]

logger = logging.getLogger(__name__)


class ProcessSelectPage(QWidget):
    """
    First page: choose a running game process.

    Signals emitted by this page (connected by MainWindow):
      • process_selected(ProcessInfo)  — user confirmed a selection
    """

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._vm = ProcessListViewModel()
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title
        title = QLabel("<b>Select Game Process</b>")
        layout.addWidget(title)

        # Filter input
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name…")
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self._filter_edit)

        # Process list
        self._list_widget = QListWidget()
        self._list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list_widget)

        # Buttons
        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._on_refresh)
        btn_row.addWidget(self._refresh_btn)

        btn_row.addStretch()

        self._select_btn = QPushButton("Select →")
        self._select_btn.setEnabled(False)
        btn_row.addWidget(self._select_btn)

        layout.addLayout(btn_row)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_filter_changed(self, text: str) -> None:
        self._vm.filter_text = text
        self._refresh_list()

    def _on_refresh(self) -> None:
        """Scan running processes and populate the list."""
        try:
            import psutil
            procs = [
                __import__("src.gui.viewmodels", fromlist=["ProcessInfo"]).ProcessInfo(
                    pid=p.pid, name=p.name()
                )
                for p in psutil.process_iter(["pid", "name"])
            ]
        except ImportError:
            # psutil not available — show placeholder entries
            from src.gui.viewmodels import ProcessInfo
            procs = [ProcessInfo(pid=0, name="(psutil not installed — demo mode)")]
        self._vm.set_processes(procs)
        self._refresh_list()

    def _on_row_changed(self, row: int) -> None:
        filtered = self._vm.filtered_processes
        if 0 <= row < len(filtered):
            self._vm.select(filtered[row])
            self._select_btn.setEnabled(True)
        else:
            self._vm.selected = None
            self._select_btn.setEnabled(False)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._list_widget.clear()
        for proc in self._vm.filtered_processes:
            self._list_widget.addItem(str(proc))
