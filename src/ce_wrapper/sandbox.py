"""
Sandbox — stateless AOB pattern validation + hit-count uniqueness checks.

Design goals
────────────
* All pure-Python, no CE or OS process dependency.
* Can be unit-tested on any platform.
* Provides the building blocks that a real CEBridge implementation will call
  after an actual AOB scan returns its results.

Public surface
──────────────
SandboxResult          — dataclass returned by check_* methods
Sandbox.validate_aob_pattern(pattern) → bool   (class method, pure format check)
Sandbox().check_aob_unique(hit_count, aob_name) → SandboxResult
"""

import logging
import re
from dataclasses import dataclass

__all__ = ["SandboxResult", "Sandbox"]

logger = logging.getLogger(__name__)

# A valid AOB token is either exactly 2 hex digits or "??"
_TOKEN_RE = re.compile(r"^([0-9A-Fa-f]{2}|\?\?)$")
# Minimum number of bytes for a pattern to be meaningful
_MIN_BYTES = 4
# Maximum wildcard fraction allowed (> this → pattern too generic).
# 0.60 accommodates standard RIP-relative patterns like "48 8B 05 ?? ?? ?? ??"
# (4/7 ≈ 57%) while still rejecting all-wildcard patterns.
_MAX_WILDCARD_RATIO = 0.60


@dataclass
class SandboxResult:
    """
    Result of a single sandbox check.

    passed — True iff the check succeeded
    detail — human-readable explanation (always set)
    """
    passed: bool
    detail: str

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.detail}"


class Sandbox:
    """
    Validates AOB patterns and scan results before injection.

    All checks are conservative: prefer false-negatives (reject a valid
    pattern) over false-positives (accept a bad one).
    """

    # ── Class-level pure format check ─────────────────────────────────────

    @classmethod
    def validate_aob_pattern(cls, pattern: str) -> bool:
        """
        Return True iff *pattern* is a well-formed AOB byte sequence.

        Rules
        ─────
        1. Non-empty and space-separated tokens.
        2. Each token is a 2-digit hex value or "??".
        3. At least _MIN_BYTES tokens.
        4. Wildcard ratio ≤ _MAX_WILDCARD_RATIO.

        Args:
            pattern: space-separated AOB string, e.g. "48 8B 05 ?? ?? ?? ??"

        Returns:
            True if all rules pass, False otherwise.
        """
        if not pattern or not pattern.strip():
            return False

        tokens = pattern.strip().split()

        # Each token must match the expected format
        if not all(_TOKEN_RE.match(t) for t in tokens):
            return False

        # Minimum length
        if len(tokens) < _MIN_BYTES:
            return False

        # Wildcard ratio
        wildcards = sum(1 for t in tokens if t == "??")
        if wildcards / len(tokens) > _MAX_WILDCARD_RATIO:
            return False

        return True

    # ── Instance-level hit-count check ────────────────────────────────────

    def check_aob_unique(self, hit_count: int, aob_name: str) -> SandboxResult:
        """
        Validate that an AOB scan found exactly one match.

        AOB patterns must have a unique hit to be safe to use — zero hits
        means the pattern is outdated, multiple hits mean it is too generic.

        Args:
            hit_count: Number of addresses the AOB scan returned.
            aob_name:  Name of the AOB (for diagnostic messages).

        Returns:
            SandboxResult with passed=True iff hit_count == 1.
        """
        if hit_count == 0:
            return SandboxResult(
                passed=False,
                detail=f"'{aob_name}': 0 matches — pattern not found in process memory",
            )
        if hit_count == 1:
            return SandboxResult(
                passed=True,
                detail=f"'{aob_name}': 1 unique match — OK",
            )
        # hit_count > 1
        return SandboxResult(
            passed=False,
            detail=(
                f"'{aob_name}': {hit_count} multiple matches — "
                "pattern is too generic, injection unsafe"
            ),
        )
