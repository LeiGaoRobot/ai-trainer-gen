"""
ScriptValidator — static analysis of LLM-generated CE Lua scripts.

Checks performed (in order):
  1. non_empty       — script has at least one non-comment line
  2. lua_syntax      — basic Lua syntax via `luac -p` (if luac is available)
  3. insufficient    — script contains INSUFFICIENT_DATA marker
  4. aob_format      — AOB patterns are valid hex/wildcard sequences
                       (SKIPPED for Mono scripts — AOBs not required)
  5. aob_length      — each AOB pattern is ≥ MIN_AOB_BYTES bytes
                       (SKIPPED for Mono scripts)
  6. aob_wildcards   — wildcard ratio ≤ MAX_WILDCARD_RATIO (warning only)
  7. ce_api_used     — calls at least one CE standard API (engine-aware set)
  8. toggle_present  — script contains an enable/disable toggle
  9. mono_api_used   — Mono scripts should call mono_* functions (warning)

Engine-aware behaviour:
  resolution_strategy = "mono_api"  → AOB checks are skipped (not needed);
                                       mono_* usage is checked instead.
  resolution_strategy = "il2cpp_ptr" → light AOB check (only root finders).
  resolution_strategy = "ue_gobjects"→ light AOB check (only GObjects scan).
  resolution_strategy = None / "aob_write" → full AOB checks enforced.

Checks 1-5 are blocking (errors) unless explicitly skipped for the engine.
Checks 6-9 emit warnings only.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .models import AOBSignature, GeneratedScript, ScriptValidation

__all__ = ["ScriptValidator"]

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_AOB_BYTES      = 7
MAX_WILDCARD_RATIO = 0.50

# Standard CE Lua read/write API
_CE_API_PATTERNS = re.compile(
    r"\b(readFloat|writeFloat|readInteger|writeInteger|readBytes|writeBytes"
    r"|getAddress|AOBScan|defineByteTable|createThread|registerSymbol"
    r"|getLocalPlayer|readDouble|writeDouble|readPointer|writePointer"
    r"|readQword|writeQword|readSmallInteger|writeSmallInteger)\b"
)
# CE Mono bridge API
_MONO_API_PATTERNS = re.compile(
    r"\b(mono_findClass|mono_getClassField|mono_getFieldOffset"
    r"|mono_findObject|mono_enumDomain|mono_enumAssemblies"
    r"|mono_object_get_field_address|mono_getStaticFieldAddress)\b"
)
_TOGGLE_PATTERNS = re.compile(
    r"\b(cheatEnabled|enabled|isActive|toggle)\b", re.IGNORECASE
)

# Resolution strategies that do NOT require per-field AOB
_NO_AOB_STRATEGIES = {"mono_api"}

# Resolution strategies where AOB is used only for root-finding (light check)
_LIGHT_AOB_STRATEGIES = {"il2cpp_ptr", "ue_gobjects"}


class ScriptValidator:
    """
    Validate a GeneratedScript using static analysis.

    Usage::
        validator = ScriptValidator()
        result = validator.validate(script, resolution_strategy="mono_api")
        if not result.passed:
            print(result.errors)
    """

    def __init__(self, use_luac: bool = True) -> None:
        self._use_luac = use_luac and shutil.which("luac") is not None
        if use_luac and not self._use_luac:
            logger.debug("luac not found — Lua syntax check will be skipped")

    # ── Public API ────────────────────────────────────────────────────────────

    def validate(
        self,
        script: GeneratedScript,
        resolution_strategy: Optional[str] = None,
    ) -> ScriptValidation:
        """
        Run all applicable checks and return a ScriptValidation.

        Parameters
        ----------
        script               : GeneratedScript to validate
        resolution_strategy  : ResolutionStrategy.value string
                               (e.g. "mono_api", "il2cpp_ptr", "ue_gobjects")
                               Controls which AOB checks are applied.
                               None → full AOB checks (legacy/unknown engine).
        """
        errors:   list[str] = []
        warnings: list[str] = []
        checks:   list[str] = []

        code     = script.lua_code
        strategy = resolution_strategy or "aob_write"
        skip_aob = strategy in _NO_AOB_STRATEGIES

        # 1. Non-empty
        checks.append("non_empty")
        substantive = [
            ln for ln in code.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ]
        if not substantive:
            errors.append("Script is empty or contains only comments.")

        # 2. Lua syntax (optional, requires luac)
        if self._use_luac:
            checks.append("lua_syntax")
            syntax_err = self._check_lua_syntax(code)
            if syntax_err:
                errors.append(f"Lua syntax error: {syntax_err}")

        # 3. Insufficient-data marker
        checks.append("insufficient_data")
        if "-- INSUFFICIENT_DATA" in code:
            errors.append(
                "LLM reported insufficient data to generate the script. "
                "Check the inline comments for details."
            )

        # 4 & 5. AOB validation
        if skip_aob:
            checks.append("aob_skipped_for_mono")
            # For Mono scripts: if any AOBs ARE present, still validate them
            # (they might be used for singleton root-finding)
            for aob in script.aob_sigs:
                if not aob.is_valid():
                    errors.append(
                        f"AOB pattern has invalid tokens: '{aob.pattern}'"
                    )
        else:
            for aob in script.aob_sigs:
                checks.append(f"aob_format:{aob.description or aob.pattern[:16]}")
                if not aob.is_valid():
                    errors.append(
                        f"AOB pattern has invalid tokens: '{aob.pattern}'. "
                        "Each token must be a 2-digit hex byte or '??'."
                    )
                    continue

                checks.append(f"aob_length:{aob.description or aob.pattern[:16]}")
                byte_count = len(aob.tokens())
                if byte_count < MIN_AOB_BYTES:
                    errors.append(
                        f"AOB pattern too short ({byte_count} bytes < {MIN_AOB_BYTES}): "
                        f"'{aob.pattern}'"
                    )

                checks.append(f"aob_wildcards:{aob.description or aob.pattern[:16]}")
                ratio = aob.wildcard_ratio()
                if ratio > MAX_WILDCARD_RATIO:
                    warnings.append(
                        f"AOB pattern has {ratio:.0%} wildcards (>{MAX_WILDCARD_RATIO:.0%}): "
                        f"'{aob.pattern}' — may cause false matches."
                    )

            # Also scan script body for inline AOB strings
            inline_aobs = self._extract_inline_aobs(code)
            for pattern in inline_aobs:
                aob = AOBSignature(pattern=pattern)
                if not aob.is_valid():
                    errors.append(
                        f"Inline AOB pattern in script has invalid tokens: '{pattern}'"
                    )

        # 6. CE API usage (warning — engine-aware)
        checks.append("ce_api_used")
        if strategy == "mono_api":
            # For Mono: check mono_* API instead of generic CE API
            if not _MONO_API_PATTERNS.search(code):
                warnings.append(
                    "Mono script does not appear to call any mono_* API functions "
                    "(mono_findClass, mono_getClassField, etc.)."
                )
        else:
            if not _CE_API_PATTERNS.search(code):
                warnings.append(
                    "Script does not call any standard CE Lua API functions. "
                    "Verify it uses readFloat/writeFloat/AOBScan/etc."
                )

        # 7. Toggle present (warning)
        checks.append("toggle_present")
        if not _TOGGLE_PATTERNS.search(code):
            warnings.append(
                "No enable/disable toggle detected (cheatEnabled / enabled / isActive). "
                "Consider adding a toggle for user convenience."
            )

        # 8. Mono-specific: warn if AOBScan used heavily (defeats the purpose)
        if strategy == "mono_api":
            checks.append("mono_no_excessive_aob")
            aob_calls = len(re.findall(r"\bAOBScan\b", code))
            if aob_calls > 2:
                warnings.append(
                    f"Mono script calls AOBScan {aob_calls} times. "
                    "For Unity Mono, prefer mono_* API — AOBs are fragile across patches."
                )

        return ScriptValidation(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            checks_run=checks,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _check_lua_syntax(lua_code: str) -> str | None:
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".lua", mode="w", encoding="utf-8", delete=False
            ) as tmp:
                tmp.write(lua_code)
                tmp_path = tmp.name

            result = subprocess.run(
                ["luac", "-p", tmp_path],
                capture_output=True, text=True, timeout=5
            )
            Path(tmp_path).unlink(missing_ok=True)

            if result.returncode != 0:
                msg = result.stderr.strip()
                msg = re.sub(r"^[^\s]+\.lua:", "<script>:", msg)
                return msg
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("luac check failed: %s", exc)
        return None

    # Broad pattern: match any quoted string of 5+ space-separated 2-char tokens
    # (allows non-hex chars so we can detect and report invalid patterns)
    _INLINE_AOB_RE = re.compile(
        r'"([0-9A-Za-z?]{2}(?:[ ][0-9A-Za-z?]{2}){4,})"'
    )

    @classmethod
    def _extract_inline_aobs(cls, code: str) -> list[str]:
        """
        Find quoted AOB strings inside the Lua code (e.g. "89 87 ?? ?? 00 00").
        Returns candidate patterns (valid or invalid) for further validation.
        Requires at least 5 space-separated 2-char tokens to reduce false positives.
        """
        results = []
        for m in cls._INLINE_AOB_RE.finditer(code):
            candidate = m.group(1).strip()
            results.append(candidate)
        return results
