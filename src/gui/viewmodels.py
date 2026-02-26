"""
GUI ViewModels — pure-Python observable state containers.

No Qt imports here; every class is testable without a display.
Qt widgets observe these objects and update themselves in response to state
changes.  (Signal emission is handled by the Qt layer, not here.)

Public API
──────────
ProcessInfo              — lightweight process descriptor
ProcessListViewModel     — manages OS process list + selection + filter
FeatureConfigViewModel   — manages selected trainer features
GenerateState            — enum for generation lifecycle
GenerateViewModel        — manages generation log + progress + state
ScriptManagerViewModel   — manages cached script list + search
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.store.models import ScriptRecord

__all__ = [
    "ProcessInfo",
    "ProcessListViewModel",
    "FeatureConfigViewModel",
    "GenerateState",
    "GenerateViewModel",
    "ScriptManagerViewModel",
]

logger = logging.getLogger(__name__)


# ── ProcessListViewModel ───────────────────────────────────────────────────────

@dataclass
class ProcessInfo:
    """Lightweight descriptor for a running OS process."""
    pid:  int
    name: str

    def __str__(self) -> str:
        return f"{self.name} (pid={self.pid})"


class ProcessListViewModel:
    """
    Manages the list of running processes.

    Attributes
    ──────────
    processes         — full list (set by refresh)
    filter_text       — substring to match against process names (case-insensitive)
    selected          — the currently chosen ProcessInfo, or None
    filtered_processes — derived: processes whose name contains filter_text
    """

    def __init__(self) -> None:
        self.processes:   list[ProcessInfo]       = []
        self.filter_text: str                      = ""
        self.selected:    Optional[ProcessInfo]    = None

    def set_processes(self, processes: list[ProcessInfo]) -> None:
        """Replace the process list (called after OS scan)."""
        self.processes = list(processes)
        # Clear selection if selected process is no longer in the list
        if self.selected and self.selected not in self.processes:
            self.selected = None

    @property
    def filtered_processes(self) -> list[ProcessInfo]:
        """Return processes matching the current filter_text (case-insensitive)."""
        if not self.filter_text:
            return list(self.processes)
        query = self.filter_text.lower()
        return [p for p in self.processes if query in p.name.lower()]

    def select(self, process: ProcessInfo) -> None:
        """Mark *process* as selected."""
        self.selected = process


# ── FeatureConfigViewModel ─────────────────────────────────────────────────────

# Standard features shown as checkboxes in the UI
_STANDARD_FEATURES = [
    "infinite_health",
    "infinite_mana",
    "infinite_ammo",
    "infinite_currency",
    "infinite_stamina",
    "one_hit_kill",
    "speed_hack",
    "godmode",
]


class FeatureConfigViewModel:
    """
    Manages trainer feature selection.

    Attributes
    ──────────
    standard_features    — fixed list of built-in feature ids
    selected_features    — features the user has toggled on
    custom_description   — optional free-text feature description
    """

    def __init__(self) -> None:
        self.standard_features:  list[str] = list(_STANDARD_FEATURES)
        self.selected_features:  list[str] = []
        self.custom_description: str        = ""

    def toggle(self, feature: str) -> None:
        """Add *feature* if not selected; remove it if already selected."""
        if feature in self.selected_features:
            self.selected_features.remove(feature)
        else:
            self.selected_features.append(feature)

    @property
    def has_selection(self) -> bool:
        """True iff at least one feature (standard or custom) is chosen."""
        return bool(self.selected_features) or bool(self.custom_description.strip())


# ── GenerateViewModel ──────────────────────────────────────────────────────────

class GenerateState(str, Enum):
    IDLE    = "idle"
    RUNNING = "running"
    DONE    = "done"
    ERROR   = "error"


class GenerateViewModel:
    """
    Tracks the state of an LLM script-generation run.

    Attributes
    ──────────
    log_lines — list of log message strings (newest last)
    progress  — float in [0.0, 1.0]
    state     — GenerateState
    """

    def __init__(self) -> None:
        self.log_lines: list[str]   = []
        self.progress:  float        = 0.0
        self.state:     GenerateState = GenerateState.IDLE

    def append_log(self, message: str) -> None:
        """Append *message* to the log."""
        self.log_lines.append(message)

    def set_progress(self, value: float) -> None:
        """Set progress, clamped to [0.0, 1.0]."""
        self.progress = max(0.0, min(1.0, value))

    def start(self) -> None:
        """Transition to RUNNING state."""
        self.state = GenerateState.RUNNING
        self.log_lines.clear()
        self.progress = 0.0

    def finish(self) -> None:
        """Transition to DONE state."""
        self.state = GenerateState.DONE
        self.progress = 1.0

    def error(self, message: str) -> None:
        """Transition to ERROR state and log the error."""
        self.state = GenerateState.ERROR
        self.append_log(f"ERROR: {message}")


# ── ScriptManagerViewModel ─────────────────────────────────────────────────────

class ScriptManagerViewModel:
    """
    Manages the cached script history shown in the script manager page.

    Attributes
    ──────────
    records       — full list of ScriptRecord objects
    search_query  — substring filter applied to game_name
    selected      — currently highlighted record, or None
    visible_records — derived: records matching search_query
    """

    def __init__(self) -> None:
        self.records:      list[ScriptRecord]   = []
        self.search_query: str                   = ""
        self.selected:     Optional[ScriptRecord] = None

    def load(self, records: list[ScriptRecord]) -> None:
        """Replace the record list (e.g. after a Store.search() call)."""
        self.records = list(records)
        self.selected = None

    @property
    def visible_records(self) -> list[ScriptRecord]:
        """Return records whose game_name contains search_query (case-insensitive)."""
        if not self.search_query:
            return list(self.records)
        q = self.search_query.lower()
        return [r for r in self.records if q in r.game_name.lower()]
