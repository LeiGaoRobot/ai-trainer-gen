"""Data models for the store module."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

__all__ = ["ScriptRecord"]


@dataclass
class ScriptRecord:
    """
    Persistent record of a generated CE Lua script.

    Fields
    ──────
    id           — SQLite row id (None until saved)
    game_hash    — SHA256(exe_path + file_size), used as cache key
    game_name    — human-readable game title
    engine_type  — EngineType value string, e.g. "Unity_Mono"
    feature      — TrainerFeature id, e.g. "infinite_health"
    lua_script   — the full generated CE Lua code
    aob_sigs     — JSON-serialised list of AOBSignature dicts (may be empty)
    created_at   — UTC timestamp of creation
    last_used    — UTC timestamp of last successful injection (may be None)
    success_count — number of successful injections
    fail_count    — number of failed injections
    """
    game_hash:     str
    game_name:     str
    engine_type:   str
    feature:       str
    lua_script:    str
    id:            Optional[int]      = None
    aob_sigs:      str                = "[]"   # JSON string
    created_at:    Optional[datetime] = None
    last_used:     Optional[datetime] = None
    success_count: int                = 0
    fail_count:    int                = 0

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(tz=timezone.utc)

    def __str__(self) -> str:
        return (
            f"ScriptRecord(id={self.id}, game={self.game_name!r}, "
            f"feature={self.feature!r}, ok={self.success_count})"
        )
