"""
gui — PyQt6 front-end for the AI Trainer Generator.

Public API
──────────
MainWindow            — top-level application window
viewmodels            — pure-Python observable state containers
pages                 — individual wizard pages
"""

from src.gui.main_window import MainWindow
from src.gui import viewmodels

__all__ = ["MainWindow", "viewmodels"]
