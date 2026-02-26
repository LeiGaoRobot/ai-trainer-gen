"""
Unit tests for the analyzer module.

Covers:
  • AOBSignature validation / helpers
  • TrainerFeature construction & constraints
  • GeneratedScript / ScriptValidation dataclasses
  • ScriptValidator checks (all error paths + warning paths)
  • PromptBuilder output format
  • LLMAnalyzer with stub backend (happy path + retry + batch)
  • _parse_response edge cases
"""

import pytest

from src.analyzer.models import (
    AOBSignature,
    FeatureType,
    GeneratedScript,
    ScriptValidation,
    TrainerFeature,
)
from src.analyzer.validator import ScriptValidator
from src.analyzer.prompts.builder import PromptBuilder
from src.analyzer.llm_analyzer import LLMAnalyzer, LLMConfig, _parse_response
from src.dumper.models import ClassInfo, FieldInfo, StructureJSON
from src.exceptions import ScriptGenerationError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_structure() -> StructureJSON:
    return StructureJSON(
        engine="Unity_IL2CPP",
        version="2022.3.10",
        classes=[
            ClassInfo(
                name="PlayerController",
                namespace="Game.Player",
                parent_class="MonoBehaviour",
                fields=[
                    FieldInfo(name="health",    type="float",  offset="0x58"),
                    FieldInfo(name="maxHealth", type="float",  offset="0x5C"),
                    FieldInfo(name="gold",      type="int32",  offset="0x64"),
                ],
            ),
        ],
    )


@pytest.fixture
def health_feature() -> TrainerFeature:
    return TrainerFeature(
        name="Infinite Health",
        feature_type=FeatureType.INFINITE_HEALTH,
        hotkey="F1",
    )


@pytest.fixture
def valid_aob() -> AOBSignature:
    return AOBSignature(
        pattern="89 87 ?? ?? 00 00 F3 0F 11",
        offset=0,
        module="GameAssembly.dll",
        description="health write",
    )


@pytest.fixture
def stub_script(health_feature, valid_aob) -> GeneratedScript:
    """A minimal but syntactically plausible generated script."""
    lua = """\
local cheatEnabled = false

local function applyCheat()
  local addr = AOBScan("89 87 ?? ?? 00 00 F3 0F 11")
  if addr then
    writeFloat(addr + 0x58, 9999.0)
  end
end

local function toggle()
  cheatEnabled = not cheatEnabled
  if cheatEnabled then applyCheat() end
end

registerHotkey(0x70, toggle)
"""
    return GeneratedScript(
        lua_code=lua,
        feature=health_feature,
        aob_sigs=[valid_aob],
        model_id="stub-v1",
    )


# ── AOBSignature ──────────────────────────────────────────────────────────────

class TestAOBSignature:
    def test_valid_pattern(self, valid_aob):
        assert valid_aob.is_valid() is True

    def test_tokens(self, valid_aob):
        assert valid_aob.tokens() == ["89", "87", "??", "??", "00", "00", "F3", "0F", "11"]

    def test_wildcard_ratio(self, valid_aob):
        # 2 wildcards out of 9 tokens
        assert abs(valid_aob.wildcard_ratio() - 2 / 9) < 0.001

    def test_empty_pattern_invalid(self):
        aob = AOBSignature(pattern="")
        assert aob.is_valid() is False

    def test_bad_token_invalid(self):
        aob = AOBSignature(pattern="89 GG 00")
        assert aob.is_valid() is False

    def test_single_byte_valid(self):
        aob = AOBSignature(pattern="90")
        assert aob.is_valid() is True

    def test_str_representation(self, valid_aob):
        s = str(valid_aob)
        assert "AOB" in s
        assert "GameAssembly.dll" in s

    def test_all_wildcards_ratio_is_one(self):
        aob = AOBSignature(pattern="?? ?? ??")
        assert aob.wildcard_ratio() == 1.0


# ── TrainerFeature ────────────────────────────────────────────────────────────

class TestTrainerFeature:
    def test_construction(self, health_feature):
        assert health_feature.name == "Infinite Health"
        assert health_feature.feature_type == FeatureType.INFINITE_HEALTH

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            TrainerFeature(name="")

    def test_str_contains_name_and_type(self, health_feature):
        s = str(health_feature)
        assert "Infinite Health" in s
        assert "infinite_health" in s

    def test_default_feature_type_is_custom(self):
        feat = TrainerFeature(name="My Feature")
        assert feat.feature_type == FeatureType.CUSTOM


# ── GeneratedScript ───────────────────────────────────────────────────────────

class TestGeneratedScript:
    def test_str_shows_feature_name(self, stub_script):
        s = str(stub_script)
        assert "Infinite Health" in s

    def test_str_shows_aob_count(self, stub_script):
        s = str(stub_script)
        assert "1 AOB" in s


# ── ScriptValidation ──────────────────────────────────────────────────────────

class TestScriptValidation:
    def test_passed_no_errors(self):
        v = ScriptValidation(passed=True)
        assert "PASS" in str(v)

    def test_failed_with_errors(self):
        v = ScriptValidation(passed=False, errors=["bad syntax"])
        assert "FAIL" in str(v)
        assert "1 error" in str(v)


# ── ScriptValidator ───────────────────────────────────────────────────────────

class TestScriptValidatorHappyPath:
    def test_valid_script_passes(self, stub_script):
        validator = ScriptValidator(use_luac=False)
        result = validator.validate(stub_script)
        assert result.passed is True
        assert result.errors == []

    def test_checks_run_populated(self, stub_script):
        validator = ScriptValidator(use_luac=False)
        result = validator.validate(stub_script)
        assert len(result.checks_run) > 0


class TestScriptValidatorErrors:
    def test_empty_script_fails(self, health_feature):
        script = GeneratedScript(lua_code="", feature=health_feature)
        result = ScriptValidator(use_luac=False).validate(script)
        assert result.passed is False
        assert any("empty" in e.lower() for e in result.errors)

    def test_comments_only_script_fails(self, health_feature):
        script = GeneratedScript(lua_code="-- just a comment\n-- another\n", feature=health_feature)
        result = ScriptValidator(use_luac=False).validate(script)
        assert result.passed is False

    def test_insufficient_data_marker_fails(self, health_feature):
        lua = "-- INSUFFICIENT_DATA\n-- Not enough info to generate"
        script = GeneratedScript(lua_code=lua, feature=health_feature)
        result = ScriptValidator(use_luac=False).validate(script)
        assert result.passed is False
        assert any("INSUFFICIENT_DATA" in e or "insufficient" in e.lower() for e in result.errors)

    def test_invalid_aob_pattern_fails(self, health_feature):
        aob = AOBSignature(pattern="89 GG 00 00 00")   # 'GG' is invalid
        script = GeneratedScript(
            lua_code="local x = readFloat(0x10)\nlocal cheatEnabled = true\n",
            feature=health_feature,
            aob_sigs=[aob],
        )
        result = ScriptValidator(use_luac=False).validate(script)
        assert result.passed is False
        assert any("invalid" in e.lower() for e in result.errors)

    def test_too_short_aob_pattern_fails(self, health_feature):
        aob = AOBSignature(pattern="89 87 00")   # only 3 bytes
        script = GeneratedScript(
            lua_code="local x = writeFloat(0x10, 9999)\nlocal cheatEnabled = true\n",
            feature=health_feature,
            aob_sigs=[aob],
        )
        result = ScriptValidator(use_luac=False).validate(script)
        assert result.passed is False
        assert any("short" in e.lower() or "minimum" in e.lower() for e in result.errors)


class TestScriptValidatorWarnings:
    def test_high_wildcard_ratio_warns(self, health_feature):
        aob = AOBSignature(pattern="?? ?? ?? ?? 00 00 F3 0F 11")  # 4/9 ≈ 44% → < threshold, let's use more
        # 6/9 = 67 % > 50 %
        aob_high = AOBSignature(pattern="?? ?? ?? ?? ?? ?? F3 0F 11")
        script = GeneratedScript(
            lua_code="local x = writeFloat(0x10, 9999)\nlocal cheatEnabled = true\n",
            feature=health_feature,
            aob_sigs=[aob_high],
        )
        result = ScriptValidator(use_luac=False).validate(script)
        assert any("wildcard" in w.lower() for w in result.warnings)

    def test_no_ce_api_warns(self, health_feature):
        script = GeneratedScript(
            lua_code="local x = 1 + 1\nlocal cheatEnabled = true\n",
            feature=health_feature,
        )
        result = ScriptValidator(use_luac=False).validate(script)
        assert any("CE" in w or "api" in w.lower() or "readFloat" in w for w in result.warnings)

    def test_no_toggle_warns(self, health_feature):
        script = GeneratedScript(
            lua_code="local x = writeFloat(0x10, 9999)\n",
            feature=health_feature,
        )
        result = ScriptValidator(use_luac=False).validate(script)
        assert any("toggle" in w.lower() for w in result.warnings)


class TestInlineAOBExtraction:
    def test_extracts_valid_inline_aob(self, health_feature):
        lua = 'local addr = AOBScan("89 87 ?? ?? 00 00 F3 0F 11")\nlocal cheatEnabled = true\n'
        script = GeneratedScript(lua_code=lua, feature=health_feature)
        result = ScriptValidator(use_luac=False).validate(script)
        # No error for the valid inline AOB
        assert all("invalid" not in e.lower() for e in result.errors)

    def test_detects_invalid_inline_aob(self, health_feature):
        lua = 'local addr = AOBScan("89 GG ?? ?? 00 00 F3")\nlocal cheatEnabled = true\n'
        script = GeneratedScript(lua_code=lua, feature=health_feature)
        result = ScriptValidator(use_luac=False).validate(script)
        assert any("inline" in e.lower() for e in result.errors)


# ── PromptBuilder ─────────────────────────────────────────────────────────────

class TestPromptBuilder:
    def test_system_prompt_non_empty(self):
        pb = PromptBuilder()
        assert len(pb.system_prompt()) > 100

    def test_user_message_contains_structure(self, simple_structure, health_feature):
        pb = PromptBuilder()
        _, user = pb.build(simple_structure, health_feature)
        assert "PlayerController" in user
        assert "health" in user

    def test_user_message_contains_feature_name(self, simple_structure, health_feature):
        pb = PromptBuilder()
        _, user = pb.build(simple_structure, health_feature)
        assert "Infinite Health" in user

    def test_user_message_contains_feature_hint(self, simple_structure, health_feature):
        pb = PromptBuilder()
        _, user = pb.build(simple_structure, health_feature)
        # Should contain infinite health implementation guidance
        assert "health" in user.lower()

    def test_user_message_contains_hotkey(self, simple_structure, health_feature):
        pb = PromptBuilder()
        _, user = pb.build(simple_structure, health_feature)
        assert "F1" in user

    def test_custom_feature_description_included(self, simple_structure):
        pb = PromptBuilder()
        feat = TrainerFeature(
            name="Custom Speed",
            feature_type=FeatureType.CUSTOM,
            description="Triple movement speed during sprint only",
        )
        _, user = pb.build(simple_structure, feat)
        assert "Triple movement speed" in user

    def test_max_classes_respected(self, simple_structure, health_feature):
        pb = PromptBuilder()
        _, user = pb.build(simple_structure, health_feature, max_classes=0)
        # With max_classes=0, no class entries should be present
        assert "[PlayerController" not in user

    def test_all_feature_types_have_hint(self, simple_structure):
        """Every FeatureType (except CUSTOM) should have a non-empty hint."""
        pb = PromptBuilder()
        from src.analyzer.prompts.builder import _FEATURE_HINTS
        for ft in FeatureType:
            hint = _FEATURE_HINTS.get(ft)
            assert hint is not None and len(hint) > 20, f"Missing hint for {ft}"


# ── _parse_response ───────────────────────────────────────────────────────────

class TestParseResponse:
    def test_parses_script_block(self, health_feature):
        raw = "[SCRIPT_BEGIN]\nlocal x = 1\n[SCRIPT_END]\n[AOB_BEGIN]\n[AOB_END]"
        script = _parse_response(raw, health_feature, "test-model")
        assert script.lua_code == "local x = 1"

    def test_parses_aob_block(self, health_feature):
        raw = (
            "[SCRIPT_BEGIN]\nlocal x = 1\n[SCRIPT_END]\n"
            "[AOB_BEGIN]\n"
            "89 87 ?? ?? 00 00 F3 | 0 | GameAssembly.dll | health write\n"
            "[AOB_END]"
        )
        script = _parse_response(raw, health_feature, "test-model")
        assert len(script.aob_sigs) == 1
        assert script.aob_sigs[0].description == "health write"
        assert script.aob_sigs[0].module == "GameAssembly.dll"
        assert script.aob_sigs[0].offset == 0

    def test_negative_aob_offset(self, health_feature):
        raw = (
            "[SCRIPT_BEGIN]\nlocal x = 1\n[SCRIPT_END]\n"
            "[AOB_BEGIN]\n"
            "89 87 00 00 F3 0F 11 | -4 | | some pattern\n"
            "[AOB_END]"
        )
        script = _parse_response(raw, health_feature, "test-model")
        assert script.aob_sigs[0].offset == -4

    def test_missing_script_block_raises(self, health_feature):
        raw = "Here is some text without the required blocks."
        with pytest.raises(ScriptGenerationError):
            _parse_response(raw, health_feature, "test-model")

    def test_model_id_stored(self, health_feature):
        raw = "[SCRIPT_BEGIN]\nlocal x = 1\n[SCRIPT_END]\n[AOB_BEGIN]\n[AOB_END]"
        script = _parse_response(raw, health_feature, "my-model-123")
        assert script.model_id == "my-model-123"

    def test_token_counts_stored(self, health_feature):
        raw = "[SCRIPT_BEGIN]\nlocal x = 1\n[SCRIPT_END]\n[AOB_BEGIN]\n[AOB_END]"
        script = _parse_response(raw, health_feature, "m", prompt_tokens=100, output_tokens=200)
        assert script.prompt_tokens == 100
        assert script.output_tokens == 200


# ── LLMAnalyzer (stub backend) ────────────────────────────────────────────────

class TestLLMAnalyzerStub:
    def test_analyze_returns_script(self, simple_structure, health_feature):
        analyzer = LLMAnalyzer(LLMConfig(backend="stub"))
        script = analyzer.analyze(simple_structure, health_feature)
        assert isinstance(script, GeneratedScript)
        assert len(script.lua_code) > 0

    def test_analyze_script_has_feature_reference(self, simple_structure, health_feature):
        analyzer = LLMAnalyzer(LLMConfig(backend="stub"))
        script = analyzer.analyze(simple_structure, health_feature)
        assert script.feature is health_feature

    def test_analyze_script_has_aobs(self, simple_structure, health_feature):
        analyzer = LLMAnalyzer(LLMConfig(backend="stub"))
        script = analyzer.analyze(simple_structure, health_feature)
        assert len(script.aob_sigs) >= 1

    def test_analyze_batch_returns_all(self, simple_structure):
        features = [
            TrainerFeature(name="Inf Health", feature_type=FeatureType.INFINITE_HEALTH),
            TrainerFeature(name="Inf Ammo",   feature_type=FeatureType.INFINITE_AMMO),
        ]
        analyzer = LLMAnalyzer(LLMConfig(backend="stub"))
        scripts = analyzer.analyze_batch(simple_structure, features)
        assert len(scripts) == 2

    def test_analyze_stub_script_passes_validation(self, simple_structure, health_feature):
        analyzer  = LLMAnalyzer(LLMConfig(backend="stub"))
        validator = ScriptValidator(use_luac=False)
        script = analyzer.analyze(simple_structure, health_feature)
        result = validator.validate(script)
        assert result.passed is True

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            LLMAnalyzer(LLMConfig(backend="unknown_xyz"))

    def test_retry_on_bad_response(self, simple_structure, health_feature, monkeypatch):
        """If the first call returns garbage, the analyzer should retry."""
        call_count = [0]
        _AOB = "89 87 ?? ?? 00 00 F3 0F 11"
        _GOOD_RESPONSE = (
            "[SCRIPT_BEGIN]\n"
            "local cheatEnabled = false\n"
            f'local addr = AOBScan("{_AOB}")\n'
            "if addr then writeFloat(addr + 0x58, 9999.0) end\n"
            "[SCRIPT_END]\n"
            "[AOB_BEGIN]\n"
            f"{_AOB} | 0 | GameAssembly.dll | health write\n"
            "[AOB_END]\n"
        )

        def fake_call(self_inner, system, user, model):
            call_count[0] += 1
            if call_count[0] == 1:
                return "no delimiters here at all", 10, 10
            # second call returns a properly formatted response
            return _GOOD_RESPONSE, 100, 50

        from src.analyzer import llm_analyzer as mod
        monkeypatch.setattr(mod._StubBackend, "call", fake_call)

        analyzer = LLMAnalyzer(LLMConfig(backend="stub", retry_delay=0.0))
        script = analyzer.analyze(simple_structure, health_feature)
        assert script is not None
        assert call_count[0] == 2
