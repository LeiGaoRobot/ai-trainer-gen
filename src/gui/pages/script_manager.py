"""
ScriptManagerPage — page 4 of the trainer GUI.

Displays the list of cached Lua trainer scripts stored in the SQLite database.
Supports search filtering and exporting selected scripts as .ct or .lua files.

Layout
──────
  ┌─────────────────────────────────────────┐
  │ Search: [_______________________________]│
  │ ┌──────────────────────────────────────┐│
  │ │ ID  │ Game         │ Feature │ OK/Fail││
  │ │  1  │ Hollow Knight│ inf_hp  │ 3 / 0  ││
  │ │  …  │ …            │ …       │ …      ││
  │ └──────────────────────────────────────┘│
  │                    [Export] [← Back]    │
  └─────────────────────────────────────────┘
"""

import logging

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.viewmodels import ScriptManagerViewModel

__all__ = ["ScriptManagerPage"]

logger = logging.getLogger(__name__)

# Column indices
_COL_ID      = 0
_COL_GAME    = 1
_COL_FEATURE = 2
_COL_STATS   = 3
_HEADERS = ["ID", "Game", "Feature", "OK / Fail"]


class ScriptManagerPage(QWidget):
    """Fourth page: browse, search, and export cached trainer scripts."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._vm = ScriptManagerViewModel()
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Title
        layout.addWidget(QLabel("<b>Script Manager</b>"))

        # Search bar
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter by game name…")
        self._search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_edit)
        layout.addLayout(search_row)

        # Script table
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        # Bottom button row
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._export_btn = QPushButton("Export")
        self._back_btn   = QPushButton("← Back")
        btn_row.addWidget(self._export_btn)
        btn_row.addWidget(self._back_btn)
        layout.addLayout(btn_row)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        self._vm.search_query = text
        self._refresh_table()

    def _refresh_table(self) -> None:
        records = self._vm.visible_records
        self._table.setRowCount(len(records))
        for row, rec in enumerate(records):
            self._table.setItem(row, _COL_ID,      QTableWidgetItem(str(rec.id or "")))
            self._table.setItem(row, _COL_GAME,     QTableWidgetItem(rec.game_name))
            self._table.setItem(row, _COL_FEATURE,  QTableWidgetItem(rec.feature))
            self._table.setItem(row, _COL_STATS,
                                QTableWidgetItem(f"{rec.success_count} / {rec.fail_count}"))

    # ── Public API ─────────────────────────────────────────────────────────

    def load_records(self, records) -> None:
        """Populate the table with *records* (list[ScriptRecord])."""
        self._vm.load(records)
        self._refresh_table()
