"""
ScriptStore — SQLite-backed persistence layer for generated CE Lua scripts.

Usage::

    store = ScriptStore(db_path="~/.ai-trainer/scripts.db")

    # Cache a new script
    row_id = store.save(record)

    # Look up cached script
    rec = store.get(game_hash="abc123", feature="infinite_health")
    if rec:
        inject(rec.lua_script)
        store.record_success(rec.id)
    else:
        script = llm_analyzer.analyze(...)
        store.save(ScriptRecord(...))

    # Invalidate after game update
    removed = store.invalidate(game_hash="abc123")
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.store.models import ScriptRecord

__all__ = ["ScriptStore"]

logger = logging.getLogger(__name__)

# Path to the SQL schema file bundled with this package
_SCHEMA_PATH = Path(__file__).parent / "migrations" / "schema.sql"


class ScriptStore:
    """
    CRUD interface for the local SQLite script cache.

    The database file and schema are created automatically on first open.
    All operations use context-managed connections; no persistent connection
    is kept open between calls (safe for single-process use on all platforms).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        """Create tables if they don't already exist."""
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(sql)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ScriptRecord:
        def _dt(s: Optional[str]) -> Optional[datetime]:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        return ScriptRecord(
            id=row["id"],
            game_hash=row["game_hash"],
            game_name=row["game_name"],
            engine_type=row["engine_type"],
            feature=row["feature"],
            lua_script=row["lua_script"],
            aob_sigs=row["aob_sigs"],
            created_at=_dt(row["created_at"]),
            last_used=_dt(row["last_used"]),
            success_count=row["success_count"],
            fail_count=row["fail_count"],
        )

    # ── Public API ────────────────────────────────────────────────────────

    def save(self, record: ScriptRecord) -> int:
        """
        Persist *record* to the database.

        Uses INSERT OR REPLACE so that duplicate (game_hash, feature) pairs
        are silently updated rather than raising a constraint error.

        Returns:
            The SQLite rowid of the newly inserted (or replaced) row.
        """
        created = (
            record.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            if record.created_at
            else datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR REPLACE INTO scripts
                    (game_hash, game_name, engine_type, feature,
                     lua_script, aob_sigs, created_at,
                     success_count, fail_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.game_hash,
                    record.game_name,
                    record.engine_type,
                    record.feature,
                    record.lua_script,
                    record.aob_sigs,
                    created,
                    record.success_count,
                    record.fail_count,
                ),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def get(self, game_hash: str, feature: str) -> Optional[ScriptRecord]:
        """
        Retrieve a cached script by (game_hash, feature).

        Returns:
            ScriptRecord if found, None on cache miss.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scripts WHERE game_hash=? AND feature=?",
                (game_hash, feature),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def record_success(self, record_id: int) -> None:
        """Increment success_count and update last_used for *record_id*."""
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET success_count = success_count + 1, last_used=? WHERE id=?",
                (now, record_id),
            )
            conn.commit()

    def record_failure(self, record_id: int) -> None:
        """Increment fail_count for *record_id*."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE scripts SET fail_count = fail_count + 1 WHERE id=?",
                (record_id,),
            )
            conn.commit()

    def invalidate(self, game_hash: str) -> int:
        """
        Delete all cached scripts for *game_hash* (e.g. after a game update).

        Returns:
            Number of rows deleted.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM scripts WHERE game_hash=?", (game_hash,)
            )
            conn.commit()
            return cur.rowcount

    def search(self, game_name: str = "") -> list[ScriptRecord]:
        """
        Search cached scripts by game name substring.

        Args:
            game_name: Substring to match (case-insensitive).
                       Empty string returns all records.

        Returns:
            List of matching ScriptRecord objects.
        """
        pattern = f"%{game_name}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE game_name LIKE ? ORDER BY created_at DESC",
                (pattern,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def delete(self, record_id: int) -> bool:
        """
        Delete a single script record by id.

        Returns:
            True if a row was deleted, False if id not found.
        """
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM scripts WHERE id=?", (record_id,))
            conn.commit()
            return cur.rowcount > 0
