"""
Unit tests for src/store/ — Week 4

Coverage plan
─────────────
models.py   → 3 tests  (ScriptRecord fields, defaults, str)
db.py       → 11 tests (save, get, miss, success/fail counters,
                        invalidate, search, upsert, multi-game,
                        schema auto-create, delete)
─────────────────────────────────────────────────────────────────
Total       = 14 new tests
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. ScriptRecord model
# ─────────────────────────────────────────────────────────────────────────────

class TestScriptRecord:
    """ScriptRecord dataclass — stored representation of a generated script."""

    def test_creates_with_required_fields(self):
        from src.store.models import ScriptRecord
        rec = ScriptRecord(
            game_hash="abc123",
            game_name="MyGame",
            engine_type="Unity_Mono",
            feature="infinite_health",
            lua_script="-- lua code",
        )
        assert rec.game_hash == "abc123"
        assert rec.feature == "infinite_health"

    def test_id_defaults_to_none(self):
        from src.store.models import ScriptRecord
        rec = ScriptRecord(
            game_hash="x", game_name="g", engine_type="UE4",
            feature="f", lua_script="l",
        )
        assert rec.id is None

    def test_counters_default_to_zero(self):
        from src.store.models import ScriptRecord
        rec = ScriptRecord(
            game_hash="x", game_name="g", engine_type="UE4",
            feature="f", lua_script="l",
        )
        assert rec.success_count == 0
        assert rec.fail_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. ScriptStore CRUD
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """Return a fresh ScriptStore backed by a temporary SQLite file."""
    from src.store.db import ScriptStore
    db_path = str(tmp_path / "test.db")
    return ScriptStore(db_path=db_path)


def _record(
    game_hash: str = "hash1",
    game_name: str = "Game",
    engine_type: str = "Unity_Mono",
    feature: str = "infinite_health",
    lua_script: str = "-- lua",
):
    from src.store.models import ScriptRecord
    return ScriptRecord(
        game_hash=game_hash,
        game_name=game_name,
        engine_type=engine_type,
        feature=feature,
        lua_script=lua_script,
    )


class TestScriptStoreSave:
    """save() — persist a ScriptRecord and return its row id."""

    def test_save_returns_integer_id(self, store):
        row_id = store.save(_record())
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_save_two_records_returns_distinct_ids(self, store):
        id1 = store.save(_record(game_hash="g1", feature="f1"))
        id2 = store.save(_record(game_hash="g2", feature="f1"))
        assert id1 != id2

    def test_schema_auto_created_on_first_open(self, tmp_path):
        from src.store.db import ScriptStore
        db_path = str(tmp_path / "fresh.db")
        s = ScriptStore(db_path=db_path)
        # Should not raise; DB + schema created automatically
        row_id = s.save(_record())
        assert row_id >= 1


class TestScriptStoreGet:
    """get() — retrieve by (game_hash, feature)."""

    def test_get_returns_saved_record(self, store):
        store.save(_record(game_hash="h1", feature="inf_hp"))
        rec = store.get(game_hash="h1", feature="inf_hp")
        assert rec is not None
        assert rec.game_hash == "h1"
        assert rec.feature == "inf_hp"

    def test_get_returns_none_on_cache_miss(self, store):
        rec = store.get(game_hash="missing", feature="anything")
        assert rec is None

    def test_get_preserves_lua_script(self, store):
        lua = "writeFloat(0xDEAD, 9999.0)"
        store.save(_record(lua_script=lua))
        rec = store.get(game_hash="hash1", feature="infinite_health")
        assert rec.lua_script == lua


class TestScriptStoreCounters:
    """record_success() and record_failure() update hit counters."""

    def test_record_success_increments_success_count(self, store):
        row_id = store.save(_record())
        store.record_success(row_id)
        store.record_success(row_id)
        rec = store.get("hash1", "infinite_health")
        assert rec.success_count == 2

    def test_record_failure_increments_fail_count(self, store):
        row_id = store.save(_record())
        store.record_failure(row_id)
        rec = store.get("hash1", "infinite_health")
        assert rec.fail_count == 1

    def test_counters_are_independent(self, store):
        row_id = store.save(_record())
        store.record_success(row_id)
        store.record_failure(row_id)
        rec = store.get("hash1", "infinite_health")
        assert rec.success_count == 1
        assert rec.fail_count == 1


class TestScriptStoreInvalidate:
    """invalidate() — remove all cached scripts for a game."""

    def test_invalidate_removes_matching_records(self, store):
        store.save(_record(game_hash="g1", feature="f1"))
        store.save(_record(game_hash="g1", feature="f2"))
        removed = store.invalidate(game_hash="g1")
        assert removed == 2
        assert store.get("g1", "f1") is None
        assert store.get("g1", "f2") is None

    def test_invalidate_does_not_affect_other_games(self, store):
        store.save(_record(game_hash="g1", feature="f1"))
        store.save(_record(game_hash="g2", feature="f1"))
        store.invalidate(game_hash="g1")
        rec = store.get("g2", "f1")
        assert rec is not None


class TestScriptStoreSearch:
    """search() — query by game name substring."""

    def test_search_returns_matching_records(self, store):
        store.save(_record(game_name="Hollow Knight", feature="f1"))
        store.save(_record(game_hash="h2", game_name="Dark Souls", feature="f1"))
        results = store.search(game_name="Hollow")
        assert len(results) == 1
        assert results[0].game_name == "Hollow Knight"

    def test_search_empty_query_returns_all(self, store):
        store.save(_record(game_hash="h1", feature="f1"))
        store.save(_record(game_hash="h2", feature="f1", game_name="Other Game"))
        results = store.search(game_name="")
        assert len(results) >= 2
