"""
Unit tests for src/cli/ — Week 4

Coverage plan
─────────────
arg parsing   → 5 tests  (generate / list / export subcommands)
list command  → 2 tests  (empty store, populated store)
export cmd    → 1 test   (bad ID raises SystemExit / error)
─────────────────────────────────────────────────────────────────
Total         = 8 new tests
"""

import sys
from io import StringIO
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse(args: list[str]):
    """Call the CLI argument parser and return the parsed namespace."""
    from src.cli.main import build_parser
    parser = build_parser()
    return parser.parse_args(args)


@pytest.fixture
def store(tmp_path):
    """Fresh ScriptStore for CLI command tests."""
    from src.store.db import ScriptStore
    return ScriptStore(db_path=str(tmp_path / "cli_test.db"))


# ─────────────────────────────────────────────────────────────────────────────
# 1. Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestArgParsing:

    def test_generate_subcommand_parses_exe_and_feature(self):
        ns = _parse(["generate", "--exe", "C:/Games/g.exe", "--feature", "infinite_health"])
        assert ns.subcommand == "generate"
        assert ns.exe == "C:/Games/g.exe"
        assert ns.feature == "infinite_health"

    def test_generate_output_defaults_to_none(self):
        ns = _parse(["generate", "--exe", "g.exe", "--feature", "f"])
        assert ns.output is None

    def test_generate_with_output_flag(self):
        ns = _parse(["generate", "--exe", "g.exe", "--feature", "f", "--output", "./out"])
        assert ns.output == "./out"

    def test_list_subcommand_game_defaults_to_none(self):
        ns = _parse(["list"])
        assert ns.subcommand == "list"
        assert ns.game is None

    def test_export_subcommand_parses_id_and_format(self):
        ns = _parse(["export", "--id", "42", "--format", "ct"])
        assert ns.subcommand == "export"
        assert ns.id == 42
        assert ns.format == "ct"


# ─────────────────────────────────────────────────────────────────────────────
# 2. list command
# ─────────────────────────────────────────────────────────────────────────────

class TestListCommand:

    def test_list_empty_store_outputs_zero_records(self, store, capsys):
        from src.cli.main import cmd_list
        cmd_list(store=store, game=None)
        captured = capsys.readouterr()
        assert "0" in captured.out or "no" in captured.out.lower() or captured.out.strip() == ""

    def test_list_with_records_prints_game_name(self, store, capsys):
        from src.store.models import ScriptRecord
        from src.cli.main import cmd_list
        store.save(ScriptRecord(
            game_hash="h1", game_name="Hollow Knight",
            engine_type="Unity_Mono", feature="inf_hp", lua_script="--",
        ))
        cmd_list(store=store, game=None)
        captured = capsys.readouterr()
        assert "Hollow Knight" in captured.out


# ─────────────────────────────────────────────────────────────────────────────
# 3. export command
# ─────────────────────────────────────────────────────────────────────────────

class TestExportCommand:

    def test_export_invalid_id_raises(self, store, tmp_path):
        from src.cli.main import cmd_export
        with pytest.raises((ValueError, SystemExit, KeyError)):
            cmd_export(store=store, record_id=9999, fmt="ct",
                       output_dir=str(tmp_path))


# ─────────────────────────────────────────────────────────────────────────────
# 4. generate command (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateCommand:
    """Full pipeline with stub LLM + mocked dumper — no real game needed."""

    @pytest.fixture
    def fake_il2cpp_exe(self, tmp_path):
        """64-bit PE with GameAssembly.dll → UNITY_IL2CPP detection."""
        import struct
        exe = tmp_path / "Game.exe"
        dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
        pe  = b"PE\x00\x00" + struct.pack("<H", 0x8664)
        exe.write_bytes(dos + b"\x00" * (0x40 - len(dos)) + pe)
        (tmp_path / "GameAssembly.dll").touch()
        return exe

    @pytest.fixture
    def fake_structure(self):
        from src.dumper.models import StructureJSON, ClassInfo, FieldInfo
        return StructureJSON(
            engine="Unity_IL2CPP",
            version="2022.3",
            classes=[
                ClassInfo(
                    name="PlayerController", namespace="Game",
                    fields=[FieldInfo(name="health", type="float", offset="0x58")],
                ),
            ],
        )

    def test_generate_creates_lua_file(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """Happy path: generates .lua file in output dir."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            out_path = cmd_generate(
                exe_path=str(fake_il2cpp_exe),
                feature="infinite_health",
                output_dir=str(tmp_path / "out"),
                no_cache=False,
                store=store,
                backend="stub",
            )

        assert out_path.exists()
        code = out_path.read_text()
        assert len(code) > 10  # stub produces non-empty script

    def test_generate_saves_to_cache(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """After generation, record should be retrievable from store."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out"), False, store, "stub")

        records = store.search("Game")
        assert len(records) == 1
        assert records[0].feature == "infinite_health"

    def test_generate_cache_hit_skips_dumper(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """Second call with same args hits cache — dumper.dump() not called again."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out1"), False, store, "stub")
            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out2"), False, store, "stub")

        assert mock_dumper.dump.call_count == 1  # only called once

    def test_generate_no_cache_forces_redump(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """--no-cache always calls dumper even on cache hit."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out1"), False, store, "stub")
            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out2"), True, store, "stub")  # no_cache=True

        assert mock_dumper.dump.call_count == 2

    def test_main_generate_returns_0(self, tmp_path, fake_structure):
        """main() returns exit code 0 on successful generation."""
        import struct
        from unittest.mock import patch, MagicMock
        from src.cli.main import main

        exe = tmp_path / "Game.exe"
        dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
        pe  = b"PE\x00\x00" + struct.pack("<H", 0x8664)
        exe.write_bytes(dos + b"\x00" * (0x40 - len(dos)) + pe)
        (tmp_path / "GameAssembly.dll").touch()

        with patch("src.cli.main.get_dumper") as mock_gd, \
             patch("src.cli.main.ScriptStore") as mock_store_cls:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.save.return_value = 1
            mock_store_cls.return_value = mock_store

            rc = main([
                "--db", str(tmp_path / "test.db"),
                "generate",
                "--exe", str(exe),
                "--feature", "infinite_health",
                "--output", str(tmp_path / "out"),
                "--backend", "stub",
            ])

        assert rc == 0

    def test_parse_feature_type_known(self):
        from src.cli.main import _parse_feature_type
        from src.analyzer.models import FeatureType
        assert _parse_feature_type("infinite_health") == FeatureType.INFINITE_HEALTH

    def test_parse_feature_type_unknown_returns_custom(self):
        from src.cli.main import _parse_feature_type
        from src.analyzer.models import FeatureType
        assert _parse_feature_type("fly_mode") == FeatureType.CUSTOM

    @pytest.fixture
    def fake_script(self):
        from src.analyzer.models import GeneratedScript, TrainerFeature, FeatureType
        feature = TrainerFeature(name="infinite_health", feature_type=FeatureType.INFINITE_HEALTH)
        return GeneratedScript(lua_code="-- stub lua\nprint('health')", feature=feature)

    @staticmethod
    def _make_engine_info(exe_path: str):
        """Build a minimal EngineInfo for test use."""
        import os
        from src.detector.models import EngineInfo, EngineType
        return EngineInfo(
            type=EngineType.UNITY_IL2CPP,
            version="2022.3",
            bitness=64,
            exe_path=exe_path,
            game_dir=os.path.dirname(exe_path),
        )

    def test_progress_cb_none_does_not_raise(self, fake_il2cpp_exe, fake_structure, fake_script, tmp_path):
        """cmd_generate with progress_cb=None (default) runs without error."""
        from unittest.mock import patch
        from src.cli.main import cmd_generate
        from src.store.db import ScriptStore

        store = ScriptStore(str(tmp_path / "s.db"))

        with patch("src.cli.main.GameEngineDetector") as mock_det, \
             patch("src.cli.main.get_dumper") as mock_get_dumper, \
             patch("src.cli.main.get_resolver") as mock_res_f, \
             patch("src.cli.main.LLMAnalyzer") as mock_llm:
            mock_det.return_value.detect.return_value = self._make_engine_info(str(fake_il2cpp_exe))
            mock_get_dumper.return_value.dump.return_value = fake_structure
            mock_res_f.return_value.resolve.return_value = []
            mock_llm.return_value.analyze.return_value = fake_script

            result = cmd_generate(
                exe_path=str(fake_il2cpp_exe),
                feature="infinite_health",
                output_dir=str(tmp_path),
                no_cache=False,
                store=store,
            )
        assert result.suffix == ".lua"

    def test_progress_cb_called_at_each_step(self, fake_il2cpp_exe, fake_structure, fake_script, tmp_path):
        """progress_cb is invoked multiple times with non-decreasing pct."""
        from unittest.mock import patch
        from src.cli.main import cmd_generate
        from src.store.db import ScriptStore

        store = ScriptStore(str(tmp_path / "s.db"))
        calls: list = []

        with patch("src.cli.main.GameEngineDetector") as mock_det, \
             patch("src.cli.main.get_dumper") as mock_get_dumper, \
             patch("src.cli.main.get_resolver") as mock_res_f, \
             patch("src.cli.main.LLMAnalyzer") as mock_llm:
            mock_det.return_value.detect.return_value = self._make_engine_info(str(fake_il2cpp_exe))
            mock_get_dumper.return_value.dump.return_value = fake_structure
            mock_res_f.return_value.resolve.return_value = []
            mock_llm.return_value.analyze.return_value = fake_script

            cmd_generate(
                exe_path=str(fake_il2cpp_exe),
                feature="infinite_health",
                output_dir=str(tmp_path),
                no_cache=False,
                store=store,
                progress_cb=lambda pct, msg: calls.append((pct, msg)),
            )

        assert len(calls) >= 3
        percentages = [pct for pct, _ in calls]
        assert percentages == sorted(percentages), "progress must be non-decreasing"

    def test_progress_cb_final_value_is_1(self, fake_il2cpp_exe, fake_structure, fake_script, tmp_path):
        """The last progress_cb call always has pct == 1.0."""
        from unittest.mock import patch
        from src.cli.main import cmd_generate
        from src.store.db import ScriptStore
        import pytest

        store = ScriptStore(str(tmp_path / "s.db"))
        last_pct: list = []

        with patch("src.cli.main.GameEngineDetector") as mock_det, \
             patch("src.cli.main.get_dumper") as mock_get_dumper, \
             patch("src.cli.main.get_resolver") as mock_res_f, \
             patch("src.cli.main.LLMAnalyzer") as mock_llm:
            mock_det.return_value.detect.return_value = self._make_engine_info(str(fake_il2cpp_exe))
            mock_get_dumper.return_value.dump.return_value = fake_structure
            mock_res_f.return_value.resolve.return_value = []
            mock_llm.return_value.analyze.return_value = fake_script

            cmd_generate(
                exe_path=str(fake_il2cpp_exe),
                feature="infinite_health",
                output_dir=str(tmp_path),
                no_cache=False,
                store=store,
                progress_cb=lambda pct, msg: last_pct.append(pct),
            )

        assert last_pct[-1] == pytest.approx(1.0)
