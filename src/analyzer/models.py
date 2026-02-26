"""Data models for the analyzer module."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

__all__ = [
    "FeatureType",
    "AOBSignature",
    "TrainerFeature",
    "GeneratedScript",
    "ScriptValidation",
]


# ── Feature taxonomy ──────────────────────────────────────────────────────────

class FeatureType(str, Enum):
    """High-level category of a trainer feature requested by the user."""
    INFINITE_HEALTH    = "infinite_health"
    INFINITE_MANA      = "infinite_mana"
    INFINITE_AMMO      = "infinite_ammo"
    INFINITE_STAMINA   = "infinite_stamina"
    INFINITE_CURRENCY  = "infinite_currency"
    INFINITE_ITEMS     = "infinite_items"
    GODMODE            = "godmode"          # combines health + damage immunity
    ONE_HIT_KILL       = "one_hit_kill"
    NO_RELOAD          = "no_reload"
    SPEED_HACK         = "speed_hack"
    FREEZE_TIMER       = "freeze_timer"
    TELEPORT           = "teleport"
    CUSTOM             = "custom"           # free-form user description


# ── AOB signature ─────────────────────────────────────────────────────────────

@dataclass
class AOBSignature:
    """
    An Array-of-Bytes (AOB) pattern used to locate code / data in memory.

    pattern  — space-separated hex bytes, '??' = wildcard
                e.g. "89 87 ?? ?? 00 00 F3 0F 11"
    offset   — signed byte offset from pattern match to the actual value
    module   — target module name (e.g. "GameAssembly.dll"); empty = any
    description — human-readable note (e.g. "health write instruction")
    """
    pattern:     str
    offset:      int   = 0
    module:      str   = ""
    description: str   = ""

    # ── Validation helpers ────────────────────────────────────────────────

    _BYTE_RE = __import__("re").compile(r"^([0-9A-Fa-f]{2}|\?\?)$")

    def tokens(self) -> list[str]:
        """Return individual byte tokens (e.g. ['89', '87', '??'])."""
        return self.pattern.split()

    def is_valid(self) -> bool:
        """Check that every token is a valid 2-hex-digit byte or wildcard."""
        toks = self.tokens()
        if not toks:
            return False
        return all(self._BYTE_RE.match(t) for t in toks)

    def wildcard_ratio(self) -> float:
        """Fraction of wildcard bytes (0.0 – 1.0).  High ratio = less reliable."""
        toks = self.tokens()
        if not toks:
            return 0.0
        wildcards = sum(1 for t in toks if t == "??")
        return wildcards / len(toks)

    def __str__(self) -> str:
        mod = f" [{self.module}]" if self.module else ""
        return f"AOB({self.pattern}){mod} +{self.offset:#x}"


# ── Trainer feature ───────────────────────────────────────────────────────────

@dataclass
class TrainerFeature:
    """
    A single trainer feature as requested by the user.

    name        — user-facing label shown in GUI / hotkey menu
    feature_type — category enum (may be CUSTOM)
    description  — free-form user description, used verbatim in LLM prompt
    hotkey       — optional CE hotkey string, e.g. "F1" or "Ctrl+1"
    """
    name:         str
    feature_type: FeatureType = FeatureType.CUSTOM
    description:  str         = ""
    hotkey:       str         = ""

    def __post_init__(self):
        if not self.name:
            raise ValueError("TrainerFeature.name must not be empty")

    def __str__(self) -> str:
        return f"{self.name} ({self.feature_type.value})"


# ── Generated script ──────────────────────────────────────────────────────────

@dataclass
class GeneratedScript:
    """
    Output of LLMAnalyzer.analyze() for a single TrainerFeature.

    lua_code    — the complete Cheat Engine Lua script
    aob_sigs    — AOB signatures referenced in the script (for validation)
    feature     — back-reference to the originating TrainerFeature
    model_id    — LLM model that produced this script (e.g. "claude-3-5-sonnet")
    prompt_tokens  — token count of the prompt sent to the LLM
    output_tokens  — token count of the response received
    raw_response   — full LLM response text (may include reasoning / markdown)
    """
    lua_code:      str
    feature:       TrainerFeature
    aob_sigs:      list[AOBSignature] = field(default_factory=list)
    model_id:      str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    raw_response:  str = ""

    def __str__(self) -> str:
        lines = self.lua_code.count("\n") + 1
        return f"GeneratedScript<{self.feature.name}> ({lines} lines, {len(self.aob_sigs)} AOBs)"


# ── Script validation result ───────────────────────────────────────────────────

@dataclass
class ScriptValidation:
    """
    Result of ScriptValidator.validate() for a GeneratedScript.

    passed       — True iff ALL checks passed
    errors       — blocking issues that prevent the script from running
    warnings     — non-blocking issues (e.g. very high wildcard ratio)
    checks_run   — names of checks that were executed
    """
    passed:     bool
    errors:     list[str] = field(default_factory=list)
    warnings:   list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] {len(self.errors)} error(s), "
            f"{len(self.warnings)} warning(s)"
        )
