"""
FeatureConfigPage — page 2 of the trainer GUI.

User selects trainer features via checkboxes, optionally types a custom
description, then clicks "Generate" to kick off the LLM pipeline.

Layout
──────
  ┌─────────────────────────────────────────┐
  │ Standard features:                      │
  │ ☑ Infinite Health   ☑ Infinite Mana    │
  │ ☐ Infinite Ammo     ☐ Infinite Currency │
  │ ☐ One Hit Kill      ☐ Speed Hack        │
  │ ☐ God Mode                              │
  │                                         │
  │ Custom description:                     │
  │ [________________________________________│
  │                          [Generate →]  │
  └─────────────────────────────────────────┘
"""

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.viewmodels import FeatureConfigViewModel

__all__ = ["FeatureConfigPage"]

logger = logging.getLogger(__name__)

# Human-readable labels for the standard features
_FEATURE_LABELS: dict[str, str] = {
    "infinite_health":   "Infinite Health",
    "infinite_mana":     "Infinite Mana",
    "infinite_ammo":     "Infinite Ammo",
    "infinite_currency": "Infinite Currency",
    "infinite_stamina":  "Infinite Stamina",
    "one_hit_kill":      "One Hit Kill",
    "speed_hack":        "Speed Hack",
    "godmode":           "God Mode",
}


class FeatureConfigPage(QWidget):
    """Second page: choose what the trainer should do."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._vm = FeatureConfigViewModel()
        self._checkboxes: dict[str, QCheckBox] = {}
        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Title
        layout.addWidget(QLabel("<b>Configure Trainer Features</b>"))

        # Standard-feature checkboxes
        group = QGroupBox("Standard Features")
        grid = QVBoxLayout(group)
        for feature_id in self._vm.standard_features:
            label = _FEATURE_LABELS.get(feature_id, feature_id.replace("_", " ").title())
            cb = QCheckBox(label)
            cb.toggled.connect(lambda checked, fid=feature_id: self._on_toggle(fid, checked))
            self._checkboxes[feature_id] = cb
            grid.addWidget(cb)
        layout.addWidget(group)

        # Custom description
        layout.addWidget(QLabel("Custom description (optional):"))
        self._custom_edit = QLineEdit()
        self._custom_edit.setPlaceholderText("e.g. freeze enemy spawn timer")
        self._custom_edit.textChanged.connect(
            lambda t: setattr(self._vm, "custom_description", t)
        )
        layout.addWidget(self._custom_edit)

        layout.addStretch()

        # Generate button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._generate_btn = QPushButton("Generate →")
        btn_row.addWidget(self._generate_btn)
        layout.addLayout(btn_row)

    # ── Slots ──────────────────────────────────────────────────────────────

    def _on_toggle(self, feature_id: str, checked: bool) -> None:
        if checked and feature_id not in self._vm.selected_features:
            self._vm.toggle(feature_id)
        elif not checked and feature_id in self._vm.selected_features:
            self._vm.toggle(feature_id)
