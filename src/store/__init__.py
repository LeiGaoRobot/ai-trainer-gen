"""
store — SQLite-backed persistence layer for generated CE Lua scripts.

Public API
──────────
ScriptRecord  — dataclass representing one cached script
ScriptStore   — CRUD interface (save, get, search, invalidate, …)
"""

from src.store.models import ScriptRecord
from src.store.db import ScriptStore

__all__ = ["ScriptRecord", "ScriptStore"]
