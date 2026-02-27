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


# ─────────────────────────────────────────────────────────────────────────────
# 6. GenerateWorker
# ─────────────────────────────────────────────────────────────────────────────

from unittest.mock import patch, MagicMock


class TestGenerateWorker:
    """GenerateWorker — runs cmd_generate in a QThread, emits signals."""

    def _make_worker(self, exe_path="/game/Game.exe", features=None, backend="stub"):
        from src.gui.worker import GenerateWorker
        from src.store.db import ScriptStore
        import tempfile, os
        store = ScriptStore(os.path.join(tempfile.mkdtemp(), "test.db"))
        return GenerateWorker(
            exe_path=exe_path,
            features=features or ["infinite_health"],
            store=store,
            backend=backend,
        )

    def test_worker_emits_finished_on_success(self, tmp_path):
        """On successful cmd_generate, worker emits finished(lua_path)."""
        worker = self._make_worker()
        results = []
        worker.finished.connect(lambda p: results.append(p))

        with patch("src.gui.worker.cmd_generate", return_value=tmp_path / "out.lua"):
            worker.run()

        assert len(results) == 1
        assert results[0].endswith(".lua")

    def test_worker_emits_failed_on_exception(self):
        """When cmd_generate raises, worker emits failed(error_msg)."""
        worker = self._make_worker()
        errors = []
        worker.failed.connect(lambda e: errors.append(e))

        with patch("src.gui.worker.cmd_generate", side_effect=RuntimeError("boom")):
            worker.run()

        assert len(errors) == 1
        assert "boom" in errors[0]

    def test_worker_emits_progress_updates(self, tmp_path):
        """progress_cb passed to cmd_generate causes progress_updated signals."""
        worker = self._make_worker()
        progress_values = []
        worker.progress_updated.connect(lambda v: progress_values.append(v))

        def fake_generate(*args, **kwargs):
            cb = kwargs.get("progress_cb")
            if cb:
                cb(0.25, "step A")
                cb(1.0,  "done")
            return tmp_path / "out.lua"

        with patch("src.gui.worker.cmd_generate", side_effect=fake_generate):
            worker.run()

        assert 0.25 in progress_values
        assert 1.0  in progress_values

    def test_worker_emits_log_for_progress_cb(self, tmp_path):
        """progress_cb messages are forwarded as log_emitted signals."""
        worker = self._make_worker()
        log_lines = []
        worker.log_emitted.connect(lambda m: log_lines.append(m))

        def fake_generate(*args, **kwargs):
            cb = kwargs.get("progress_cb")
            if cb:
                cb(0.5, "halfway there")
            return tmp_path / "out.lua"

        with patch("src.gui.worker.cmd_generate", side_effect=fake_generate):
            worker.run()

        assert any("halfway there" in line for line in log_lines)


# ─────────────────────────────────────────────────────────────────────────────
# 7. MainWindowWiring
# ─────────────────────────────────────────────────────────────────────────────

class TestMainWindowWiring:
    """MainWindow — Generate button launches worker, signals route to pages."""

    def _make_window(self, tmp_path):
        from src.gui.main_window import MainWindow
        from unittest.mock import patch
        with patch("src.gui.main_window.tempfile.gettempdir", return_value=str(tmp_path)):
            win = MainWindow()
        return win

    def _click_generate(self, win):
        """Click Generate with both GenerateWorker and QThread fully mocked."""
        from unittest.mock import patch, MagicMock

        with patch("src.gui.main_window.GenerateWorker") as MockWorker, \
             patch("src.gui.main_window.QThread") as MockThread:
            mock_w = MagicMock()
            MockWorker.return_value = mock_w
            for sig in ("finished", "failed", "log_emitted", "progress_updated"):
                setattr(mock_w, sig, MagicMock())
            MockThread.return_value = MagicMock()
            win._page_features._generate_btn.click()

    def test_generate_navigates_to_generate_page(self, tmp_path, qtbot):
        """Clicking Generate button navigates to GeneratePage (index 2)."""
        from src.gui.viewmodels import ProcessInfo

        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        win._page_process._vm.selected = ProcessInfo(
            pid=1, name="Game.exe", exe_path="/fake/Game.exe"
        )
        win._page_features._vm.toggle("infinite_health")
        self._click_generate(win)

        assert win._stack.currentIndex() == 2  # PAGE_GENERATE

    def test_generate_resets_generate_page(self, tmp_path, qtbot):
        """Clicking Generate calls reset() on GeneratePage before starting."""
        from src.gui.viewmodels import ProcessInfo

        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        win._page_process._vm.selected = ProcessInfo(
            pid=1, name="Game.exe", exe_path="/fake/Game.exe"
        )
        win._page_generate._log_view.appendPlainText("old log")  # dirty state
        self._click_generate(win)

        assert win._page_generate._log_view.toPlainText() == ""  # was reset

    def test_worker_finished_navigates_to_script_manager(self, tmp_path, qtbot):
        """On worker finished signal, MainWindow navigates to ScriptManagerPage (index 3)."""
        from src.gui.viewmodels import ProcessInfo

        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        win._page_process._vm.selected = ProcessInfo(
            pid=1, name="Game.exe", exe_path="/fake/Game.exe"
        )
        self._click_generate(win)

        # Simulate the worker emitting finished
        win._on_generate_finished("/output/Game_infinite_health.lua")
        assert win._stack.currentIndex() == 3  # PAGE_SCRIPT_MANAGER

    def test_worker_failed_stays_on_generate_page(self, tmp_path, qtbot):
        """On worker failed signal, MainWindow stays on GeneratePage (index 2)."""
        from src.gui.viewmodels import ProcessInfo

        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        win._page_process._vm.selected = ProcessInfo(
            pid=1, name="Game.exe", exe_path="/fake/Game.exe"
        )
        self._click_generate(win)

        win._on_generate_failed("Engine detection failed: file not found")
        assert win._stack.currentIndex() == 2  # still on GeneratePage
