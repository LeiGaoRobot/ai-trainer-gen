"""
Unit tests for src/gui/ Qt widgets — requires PyQt6 + offscreen display.

Run with: QT_QPA_PLATFORM=offscreen pytest tests/unit/test_gui_widgets.py

Coverage plan
─────────────
MainWindow          → 2 tests
ProcessSelectPage   → 2 tests
FeatureConfigPage   → 2 tests
GeneratePage        → 2 tests
ScriptManagerPage   → 2 tests
─────────────────────────────────
Total               = 10 tests
"""

import os
import sys

import pytest

# Ensure offscreen rendering when no display is available
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PyQt6 = pytest.importorskip("PyQt6", reason="PyQt6 not installed")


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    """Single QApplication for the entire module (can only have one per process)."""
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv)
    yield _app
    # Don't call app.quit() — other tests in the session may still need it.


# ─────────────────────────────────────────────────────────────────────────────
# 1. MainWindow
# ─────────────────────────────────────────────────────────────────────────────

class TestMainWindow:

    def test_creates_without_error(self, app):
        from src.gui.main_window import MainWindow
        win = MainWindow()
        assert win is not None

    def test_has_stacked_pages(self, app):
        from src.gui.main_window import MainWindow
        from PyQt6.QtWidgets import QStackedWidget
        win = MainWindow()
        # Must have a QStackedWidget for page switching
        stacks = win.findChildren(QStackedWidget)
        assert len(stacks) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. ProcessSelectPage
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessSelectPage:

    def test_has_a_list_widget(self, app):
        from src.gui.pages.process_select import ProcessSelectPage
        from PyQt6.QtWidgets import QListWidget
        page = ProcessSelectPage()
        lists = page.findChildren(QListWidget)
        assert len(lists) >= 1

    def test_has_a_refresh_button(self, app):
        from src.gui.pages.process_select import ProcessSelectPage
        from PyQt6.QtWidgets import QPushButton
        page = ProcessSelectPage()
        buttons = page.findChildren(QPushButton)
        labels = [b.text().lower() for b in buttons]
        assert any("refresh" in lbl for lbl in labels)


# ─────────────────────────────────────────────────────────────────────────────
# 3. FeatureConfigPage
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureConfigPage:

    def test_has_checkboxes_for_standard_features(self, app):
        from src.gui.pages.feature_config import FeatureConfigPage
        from PyQt6.QtWidgets import QCheckBox
        page = FeatureConfigPage()
        checkboxes = page.findChildren(QCheckBox)
        assert len(checkboxes) >= 3

    def test_has_generate_button(self, app):
        from src.gui.pages.feature_config import FeatureConfigPage
        from PyQt6.QtWidgets import QPushButton
        page = FeatureConfigPage()
        buttons = page.findChildren(QPushButton)
        labels = [b.text().lower() for b in buttons]
        assert any("generate" in lbl for lbl in labels)


# ─────────────────────────────────────────────────────────────────────────────
# 4. GeneratePage
# ─────────────────────────────────────────────────────────────────────────────

class TestGeneratePage:

    def test_has_log_display(self, app):
        from src.gui.pages.generate import GeneratePage
        from PyQt6.QtWidgets import QTextEdit, QPlainTextEdit
        page = GeneratePage()
        logs = page.findChildren(QTextEdit) + page.findChildren(QPlainTextEdit)
        assert len(logs) >= 1

    def test_has_progress_bar(self, app):
        from src.gui.pages.generate import GeneratePage
        from PyQt6.QtWidgets import QProgressBar
        page = GeneratePage()
        bars = page.findChildren(QProgressBar)
        assert len(bars) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. ScriptManagerPage
# ─────────────────────────────────────────────────────────────────────────────

class TestScriptManagerPage:

    def test_has_table_widget(self, app):
        from src.gui.pages.script_manager import ScriptManagerPage
        from PyQt6.QtWidgets import QTableWidget
        page = ScriptManagerPage()
        tables = page.findChildren(QTableWidget)
        assert len(tables) >= 1

    def test_has_export_button(self, app):
        from src.gui.pages.script_manager import ScriptManagerPage
        from PyQt6.QtWidgets import QPushButton
        page = ScriptManagerPage()
        buttons = page.findChildren(QPushButton)
        labels = [b.text().lower() for b in buttons]
        assert any("export" in lbl for lbl in labels)
