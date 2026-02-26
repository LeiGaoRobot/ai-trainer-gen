"""
Unit tests for src/ce_wrapper/ — Week 3

Coverage plan
─────────────
models.py      → 8 tests  (CEProcess, InjectionResult, CTTable)
ct_builder.py  → 9 tests  (XML generation, structural integrity)
sandbox.py     → 9 tests  (AOB pattern validation, hit-count logic)
─────────────────────────────────────────────────────────────────
Total target   ≥ 26 tests  (ensures overall suite hits ≥ 158)
"""

import xml.etree.ElementTree as ET
from typing import Optional

import pytest

from src.analyzer.models import AOBSignature, GeneratedScript, TrainerFeature, FeatureType
from src.resolver.models import EngineContext, FieldResolution, ResolutionStrategy


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_feature(name: str = "Infinite Health", hotkey: str = "F1") -> TrainerFeature:
    return TrainerFeature(
        name=name,
        feature_type=FeatureType.INFINITE_HEALTH,
        hotkey=hotkey,
    )


def _make_aob(pattern: str = "48 8B 05 ?? ?? ?? ??") -> AOBSignature:
    return AOBSignature(pattern=pattern, offset=0, module="game.exe")


def _make_script(
    lua_code: str = "-- stub\nwriteFloat(0x1000, 9999)",
    aob_sigs: Optional[list] = None,
    feature: Optional[TrainerFeature] = None,
) -> GeneratedScript:
    return GeneratedScript(
        lua_code=lua_code,
        feature=feature or _make_feature(),
        aob_sigs=aob_sigs if aob_sigs is not None else [_make_aob()],
    )


def _make_engine_ctx(engine_type: str = "Unity_Mono") -> EngineContext:
    return EngineContext(engine_type=engine_type, engine_version="2022.3.10", bitness=64)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Models
# ─────────────────────────────────────────────────────────────────────────────

class TestCEProcess:
    """CEProcess — represents an attached game process."""

    def test_creates_with_required_fields(self):
        from src.ce_wrapper.models import CEProcess
        proc = CEProcess(pid=1234, name="MyGame.exe")
        assert proc.pid == 1234
        assert proc.name == "MyGame.exe"

    def test_is64bit_defaults_to_true(self):
        from src.ce_wrapper.models import CEProcess
        proc = CEProcess(pid=99, name="game.exe")
        assert proc.is_64bit is True

    def test_is64bit_can_be_false(self):
        from src.ce_wrapper.models import CEProcess
        proc = CEProcess(pid=99, name="game32.exe", is_64bit=False)
        assert proc.is_64bit is False

    def test_str_contains_name_and_pid(self):
        from src.ce_wrapper.models import CEProcess
        proc = CEProcess(pid=5678, name="MyGame.exe")
        s = str(proc)
        assert "MyGame.exe" in s
        assert "5678" in s


class TestInjectionResult:
    """InjectionResult — outcome of a single inject call."""

    def test_success_flag_true(self):
        from src.ce_wrapper.models import InjectionResult
        r = InjectionResult(success=True, feature_id="infinite_health")
        assert r.success is True

    def test_failure_carries_error_message(self):
        from src.ce_wrapper.models import InjectionResult
        r = InjectionResult(
            success=False,
            feature_id="infinite_health",
            error="AOB not found",
        )
        assert r.success is False
        assert "AOB not found" in r.error

    def test_str_reflects_success(self):
        from src.ce_wrapper.models import InjectionResult
        r = InjectionResult(success=True, feature_id="foo")
        assert "OK" in str(r) or "success" in str(r).lower()

    def test_str_reflects_failure(self):
        from src.ce_wrapper.models import InjectionResult
        r = InjectionResult(success=False, feature_id="foo", error="boom")
        s = str(r).lower()
        assert "fail" in s or "error" in s or "boom" in s


# ─────────────────────────────────────────────────────────────────────────────
# 2. CTBuilder
# ─────────────────────────────────────────────────────────────────────────────

class TestCTBuilder:
    """CTBuilder.build() — serialises GeneratedScript into CE .ct XML."""

    def _build(self, script=None, ctx=None) -> str:
        from src.ce_wrapper.ct_builder import CTBuilder
        b = CTBuilder()
        return b.build(script or _make_script(), ctx or _make_engine_ctx())

    # ── Structural checks ─────────────────────────────────────────────────

    def test_returns_string(self):
        xml = self._build()
        assert isinstance(xml, str)

    def test_is_valid_xml(self):
        xml = self._build()
        root = ET.fromstring(xml)          # raises if malformed
        assert root is not None

    def test_root_element_is_CheatTable(self):
        xml = self._build()
        root = ET.fromstring(xml)
        assert root.tag == "CheatTable"

    def test_contains_CheatEntries(self):
        xml = self._build()
        root = ET.fromstring(xml)
        entries = root.find("CheatEntries")
        assert entries is not None

    def test_feature_appears_in_entries(self):
        feature = _make_feature("God Mode", "F2")
        script = _make_script(feature=feature)
        xml = self._build(script)
        assert "God Mode" in xml

    def test_lua_code_embedded(self):
        lua = "-- test\nwriteFloat(0x1000, 9999)"
        script = _make_script(lua_code=lua)
        xml = self._build(script)
        assert "writeFloat" in xml

    def test_aob_signature_appears(self):
        aob = _make_aob("48 8B 05 11 22 33 44")
        script = _make_script(aob_sigs=[aob])
        xml = self._build(script)
        assert "48 8B 05" in xml

    def test_hotkey_preserved(self):
        feature = _make_feature("Speed", "F3")
        script = _make_script(feature=feature)
        xml = self._build(script)
        assert "F3" in xml

    def test_empty_aob_list_still_valid_xml(self):
        script = _make_script(aob_sigs=[])
        xml = self._build(script)
        ET.fromstring(xml)                # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sandbox (AOB validation + hit-count logic)
# ─────────────────────────────────────────────────────────────────────────────

class TestSandboxAOBFormat:
    """Sandbox.validate_aob_pattern() — pure format checks (no CE / memory)."""

    def _validate(self, pattern: str) -> bool:
        from src.ce_wrapper.sandbox import Sandbox
        return Sandbox.validate_aob_pattern(pattern)

    def test_valid_pattern_returns_true(self):
        assert self._validate("48 8B 05 ?? ?? ?? ??") is True

    def test_fully_concrete_pattern_valid(self):
        assert self._validate("48 89 87 00 01 00 00") is True

    def test_all_wildcards_invalid(self):
        assert self._validate("?? ?? ?? ?? ?? ?? ?? ??") is False

    def test_too_short_pattern_invalid(self):
        # fewer than 4 bytes
        assert self._validate("48 8B") is False

    def test_invalid_hex_byte_rejected(self):
        assert self._validate("GG 8B 05 ?? ?? ?? ??") is False

    def test_empty_pattern_invalid(self):
        assert self._validate("") is False

    def test_pattern_with_bad_separator_invalid(self):
        # bytes should be space-separated
        assert self._validate("488B05??????") is False


class TestSandboxHitCount:
    """Sandbox.check_aob_unique() — validates exactly-one-hit requirement."""

    def _make_sandbox(self):
        from src.ce_wrapper.sandbox import Sandbox
        return Sandbox()

    def test_zero_hits_returns_failure(self):
        from src.ce_wrapper.sandbox import SandboxResult
        sb = self._make_sandbox()
        result = sb.check_aob_unique(hit_count=0, aob_name="health_aob")
        assert result.passed is False
        assert "0" in result.detail or "no match" in result.detail.lower()

    def test_one_hit_returns_success(self):
        from src.ce_wrapper.sandbox import SandboxResult
        sb = self._make_sandbox()
        result = sb.check_aob_unique(hit_count=1, aob_name="health_aob")
        assert result.passed is True

    def test_multiple_hits_returns_failure(self):
        from src.ce_wrapper.sandbox import SandboxResult
        sb = self._make_sandbox()
        result = sb.check_aob_unique(hit_count=3, aob_name="health_aob")
        assert result.passed is False
        assert "3" in result.detail or "multiple" in result.detail.lower()


class TestSandboxResult:
    """SandboxResult dataclass."""

    def test_sandboxresult_has_passed_and_detail(self):
        from src.ce_wrapper.sandbox import SandboxResult
        r = SandboxResult(passed=True, detail="all good")
        assert r.passed is True
        assert r.detail == "all good"

    def test_str_shows_status(self):
        from src.ce_wrapper.sandbox import SandboxResult
        r = SandboxResult(passed=False, detail="AOB not found")
        s = str(r).lower()
        assert "fail" in s or "error" in s or "not found" in s
