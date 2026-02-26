"""
Unit tests for src/gui/viewmodels.py — no Qt dependency.

ViewModels are pure-Python observable state containers.
All tests run on every platform without a display.

Coverage plan
─────────────
ProcessListViewModel   → 5 tests
FeatureConfigViewModel → 5 tests
GenerateViewModel      → 4 tests
ScriptManagerViewModel → 3 tests
─────────────────────────────────
Total                  = 17 tests
"""

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. ProcessListViewModel
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessListViewModel:
    """Holds a list of OS processes; supports filtering and selection."""

    def _vm(self):
        from src.gui.viewmodels import ProcessListViewModel
        return ProcessListViewModel()

    def test_initial_process_list_is_empty(self):
        vm = self._vm()
        assert vm.processes == []

    def test_set_processes_updates_list(self):
        from src.gui.viewmodels import ProcessInfo
        vm = self._vm()
        vm.set_processes([ProcessInfo(pid=1, name="game.exe"), ProcessInfo(pid=2, name="other.exe")])
        assert len(vm.processes) == 2

    def test_filter_by_name_returns_matching(self):
        from src.gui.viewmodels import ProcessInfo
        vm = self._vm()
        vm.set_processes([
            ProcessInfo(pid=1, name="MyGame.exe"),
            ProcessInfo(pid=2, name="chrome.exe"),
        ])
        vm.filter_text = "game"
        filtered = vm.filtered_processes
        assert len(filtered) == 1
        assert filtered[0].name == "MyGame.exe"

    def test_select_process_updates_selected(self):
        from src.gui.viewmodels import ProcessInfo
        vm = self._vm()
        p = ProcessInfo(pid=42, name="game.exe")
        vm.set_processes([p])
        vm.select(p)
        assert vm.selected is p

    def test_selected_defaults_to_none(self):
        vm = self._vm()
        assert vm.selected is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. FeatureConfigViewModel
# ─────────────────────────────────────────────────────────────────────────────

class TestFeatureConfigViewModel:
    """Holds the user's chosen trainer features before generation."""

    def _vm(self):
        from src.gui.viewmodels import FeatureConfigViewModel
        return FeatureConfigViewModel()

    def test_standard_features_list_is_non_empty(self):
        vm = self._vm()
        assert len(vm.standard_features) > 0

    def test_selected_features_initially_empty(self):
        vm = self._vm()
        assert vm.selected_features == []

    def test_toggle_feature_adds_it(self):
        vm = self._vm()
        feature = vm.standard_features[0]
        vm.toggle(feature)
        assert feature in vm.selected_features

    def test_toggle_selected_feature_removes_it(self):
        vm = self._vm()
        feature = vm.standard_features[0]
        vm.toggle(feature)  # add
        vm.toggle(feature)  # remove
        assert feature not in vm.selected_features

    def test_custom_description_defaults_to_empty_string(self):
        vm = self._vm()
        assert vm.custom_description == ""


# ─────────────────────────────────────────────────────────────────────────────
# 3. GenerateViewModel
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateViewModel:
    """Tracks state during LLM script generation."""

    def _vm(self):
        from src.gui.viewmodels import GenerateViewModel
        return GenerateViewModel()

    def test_initial_progress_is_zero(self):
        vm = self._vm()
        assert vm.progress == 0.0

    def test_append_log_grows_log_lines(self):
        vm = self._vm()
        vm.append_log("Starting analysis...")
        vm.append_log("LLM call done.")
        assert len(vm.log_lines) == 2
        assert "Starting analysis" in vm.log_lines[0]

    def test_set_progress_clamps_between_0_and_1(self):
        vm = self._vm()
        vm.set_progress(1.5)
        assert vm.progress == 1.0
        vm.set_progress(-0.5)
        assert vm.progress == 0.0

    def test_state_transitions_idle_running_done(self):
        from src.gui.viewmodels import GenerateState
        vm = self._vm()
        assert vm.state == GenerateState.IDLE
        vm.start()
        assert vm.state == GenerateState.RUNNING
        vm.finish()
        assert vm.state == GenerateState.DONE


# ─────────────────────────────────────────────────────────────────────────────
# 4. ScriptManagerViewModel
# ─────────────────────────────────────────────────────────────────────────────

class TestScriptManagerViewModel:
    """Holds the cached script list with search and selection."""

    def _vm(self):
        from src.gui.viewmodels import ScriptManagerViewModel
        return ScriptManagerViewModel()

    def test_initial_records_is_empty(self):
        vm = self._vm()
        assert vm.records == []

    def test_load_records_populates_list(self):
        from src.store.models import ScriptRecord
        vm = self._vm()
        records = [
            ScriptRecord(game_hash="h1", game_name="GameA", engine_type="Unity_Mono",
                         feature="inf_hp", lua_script="--"),
            ScriptRecord(game_hash="h2", game_name="GameB", engine_type="UE4",
                         feature="speed", lua_script="--"),
        ]
        vm.load(records)
        assert len(vm.records) == 2

    def test_search_query_filters_visible_records(self):
        from src.store.models import ScriptRecord
        vm = self._vm()
        vm.load([
            ScriptRecord(game_hash="h1", game_name="Hollow Knight", engine_type="Unity_Mono",
                         feature="inf_hp", lua_script="--"),
            ScriptRecord(game_hash="h2", game_name="Dark Souls", engine_type="UE4",
                         feature="speed", lua_script="--"),
        ])
        vm.search_query = "Hollow"
        visible = vm.visible_records
        assert len(visible) == 1
        assert visible[0].game_name == "Hollow Knight"
