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
