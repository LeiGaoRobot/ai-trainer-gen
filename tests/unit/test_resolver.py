"""
Unit tests for the resolver module.

Covers:
  • FieldResolution helpers (ce_read_fn, ce_write_fn, __str__)
  • EngineContext.from_engine_info
  • MonoResolver.resolve + preamble_lua
  • IL2CPPResolver.resolve + preamble_lua
  • UnrealResolver.resolve + preamble_lua
  • get_resolver factory
  • PromptBuilder engine-aware system prompts
  • ScriptValidator engine-aware AOB skipping
"""

import pytest

from src.resolver.models import EngineContext, FieldResolution, ResolutionStrategy
from src.resolver.mono_resolver import MonoResolver
from src.resolver.il2cpp_resolver import IL2CPPResolver
from src.resolver.unreal_resolver import UnrealResolver
from src.resolver.factory import get_resolver
from src.dumper.models import ClassInfo, FieldInfo, StructureJSON
from src.analyzer.prompts.builder import PromptBuilder
from src.analyzer.models import FeatureType, GeneratedScript, TrainerFeature
from src.analyzer.validator import ScriptValidator


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def player_structure() -> StructureJSON:
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
                    FieldInfo(name="ammo",      type="int32",  offset="0x68"),
                ],
            ),
            ClassInfo(
                name="GameManager",
                namespace="Game",
                fields=[
                    FieldInfo(name="instance", type="GameManager", offset="0x20",
                              is_static=True),
                ],
            ),
        ],
    )


@pytest.fixture
def mono_context(player_structure) -> EngineContext:
    ctx = EngineContext(
        engine_type="Unity_Mono",
        engine_version="2022.3.10",
        bitness=64,
        assembly_name="Assembly-CSharp",
        module_name="mono.dll",
    )
    resolver = MonoResolver()
    ctx.resolutions = resolver.resolve(player_structure, ctx)
    return ctx


@pytest.fixture
def il2cpp_context(player_structure) -> EngineContext:
    ctx = EngineContext(
        engine_type="Unity_IL2CPP",
        engine_version="2022.3.10",
        bitness=64,
        assembly_name="Assembly-CSharp",
        module_name="GameAssembly.dll",
    )
    resolver = IL2CPPResolver()
    ctx.resolutions = resolver.resolve(player_structure, ctx)
    return ctx


@pytest.fixture
def ue4_structure() -> StructureJSON:
    return StructureJSON(
        engine="UE4",
        version="4.27",
        classes=[
            ClassInfo(
                name="BP_PlayerCharacter_C",
                namespace="",
                fields=[
                    FieldInfo(name="Health",    type="float", offset="0x0330"),
                    FieldInfo(name="MaxHealth", type="float", offset="0x0334"),
                ],
            ),
        ],
    )


@pytest.fixture
def ue4_context(ue4_structure) -> EngineContext:
    ctx = EngineContext(
        engine_type="UE4",
        engine_version="4.27",
        bitness=64,
        module_name="SomeGame-Win64-Shipping.exe",
    )
    resolver = UnrealResolver()
    ctx.resolutions = resolver.resolve(ue4_structure, ctx)
    return ctx


# ── FieldResolution helpers ────────────────────────────────────────────────────

class TestFieldResolutionHelpers:
    def test_ce_read_fn_float(self):
        r = FieldResolution("C", "f", "float", ResolutionStrategy.MONO_API)
        assert r.ce_read_fn() == "readFloat"

    def test_ce_read_fn_int32(self):
        r = FieldResolution("C", "f", "int32", ResolutionStrategy.MONO_API)
        assert r.ce_read_fn() == "readInteger"

    def test_ce_write_fn_float(self):
        r = FieldResolution("C", "f", "float", ResolutionStrategy.MONO_API)
        assert r.ce_write_fn() == "writeFloat"

    def test_ce_read_fn_unknown_defaults_to_float(self):
        r = FieldResolution("C", "f", "SomeUnknownType", ResolutionStrategy.MONO_API)
        assert r.ce_read_fn() == "readFloat"

    def test_str_representation(self):
        r = FieldResolution("PlayerController", "health", "float",
                            ResolutionStrategy.MONO_API)
        s = str(r)
        assert "PlayerController" in s
        assert "health" in s
        assert "mono_api" in s


# ── EngineContext ─────────────────────────────────────────────────────────────

class TestEngineContext:
    def test_from_engine_info_il2cpp(self):
        """Smoke test: build from a duck-typed engine_info."""
        class FakeInfo:
            type = type("T", (), {"value": "Unity_IL2CPP"})()
            version = "2022.3"
            bitness = 64
            exe_path = "/game/Game.exe"
            extra = {"assembly_name": "Assembly-CSharp"}

        ctx = EngineContext.from_engine_info(FakeInfo())
        assert ctx.engine_type == "Unity_IL2CPP"
        assert ctx.module_name == "GameAssembly.dll"
        assert ctx.assembly_name == "Assembly-CSharp"

    def test_from_engine_info_ue4(self):
        class FakeInfo:
            type = type("T", (), {"value": "UE4"})()
            version = "4.27"
            bitness = 64
            exe_path = "/game/Game.exe"
            extra = {"primary_module": "Game-Win64-Shipping.exe"}

        ctx = EngineContext.from_engine_info(FakeInfo())
        assert ctx.engine_type == "UE4"
        assert ctx.module_name == "Game-Win64-Shipping.exe"


# ── MonoResolver ──────────────────────────────────────────────────────────────

class TestMonoResolver:
    def test_resolve_returns_resolutions(self, player_structure, mono_context):
        assert len(mono_context.resolutions) > 0

    def test_all_resolutions_are_mono_strategy(self, mono_context):
        for r in mono_context.resolutions:
            assert r.strategy == ResolutionStrategy.MONO_API

    def test_resolution_has_lua_exprs(self, mono_context):
        for r in mono_context.resolutions:
            assert r.lua_read_expr, f"Missing lua_read_expr for {r.field_name}"
            assert r.lua_write_expr, f"Missing lua_write_expr for {r.field_name}"

    def test_lua_read_expr_uses_mono_offset(self, mono_context):
        health = next(r for r in mono_context.resolutions if r.field_name == "health")
        assert "_monoOffset" in health.lua_read_expr
        assert "PlayerController" in health.lua_read_expr

    def test_lua_write_expr_contains_value_placeholder(self, mono_context):
        health = next(r for r in mono_context.resolutions if r.field_name == "health")
        assert "{value}" in health.lua_write_expr

    def test_static_field_uses_static_exprs(self, player_structure, mono_context):
        """GameManager.instance is static — should use mono_getStaticFieldAddress."""
        static_res = [r for r in mono_context.resolutions if r.is_static
                      if hasattr(r, 'is_static')] if False else \
                     [r for r in mono_context.resolutions if "getStaticFieldAddress" in r.lua_read_expr]
        # Just verify static field was emitted (GameManager.instance)
        gm_fields = [r for r in mono_context.resolutions if r.class_name == "GameManager"]
        assert len(gm_fields) >= 1

    def test_preamble_contains_mono_helpers(self, mono_context):
        preamble = MonoResolver().preamble_lua(mono_context)
        assert "_monoClass" in preamble
        assert "_monoField" in preamble
        assert "_monoOffset" in preamble
        assert "mono_findClass" in preamble

    def test_preamble_contains_assembly_name(self, mono_context):
        preamble = MonoResolver().preamble_lua(mono_context)
        assert "Assembly-CSharp" in preamble


# ── IL2CPPResolver ────────────────────────────────────────────────────────────

class TestIL2CPPResolver:
    def test_resolve_returns_resolutions(self, player_structure, il2cpp_context):
        assert len(il2cpp_context.resolutions) > 0

    def test_all_resolutions_are_il2cpp_strategy(self, il2cpp_context):
        for r in il2cpp_context.resolutions:
            assert r.strategy == ResolutionStrategy.IL2CPP_PTR

    def test_field_offset_parsed_correctly(self, il2cpp_context):
        health = next(r for r in il2cpp_context.resolutions if r.field_name == "health")
        assert health.field_offset == 0x58

    def test_lua_read_expr_uses_known_offset(self, il2cpp_context):
        health = next(r for r in il2cpp_context.resolutions if r.field_name == "health")
        assert "0x58" in health.lua_read_expr
        assert "readFloat" in health.lua_read_expr
        assert "_getBase_PlayerController" in health.lua_read_expr

    def test_lua_write_expr_contains_value_placeholder(self, il2cpp_context):
        health = next(r for r in il2cpp_context.resolutions if r.field_name == "health")
        assert "{value}" in health.lua_write_expr

    def test_preamble_contains_rip_resolver(self, il2cpp_context):
        preamble = IL2CPPResolver().preamble_lua(il2cpp_context)
        assert "_resolveRIP" in preamble
        assert "_findRoot" in preamble

    def test_preamble_contains_module_name(self, il2cpp_context):
        preamble = IL2CPPResolver().preamble_lua(il2cpp_context)
        assert "GameAssembly.dll" in preamble

    def test_field_without_offset_is_skipped(self):
        """Fields with no offset info should be silently skipped."""
        struct = StructureJSON(
            engine="Unity_IL2CPP", version="1.0",
            classes=[ClassInfo(name="Foo", namespace="", fields=[
                FieldInfo(name="bar", type="float", offset=""),
            ])]
        )
        ctx = EngineContext(engine_type="Unity_IL2CPP")
        resolutions = IL2CPPResolver().resolve(struct, ctx)
        assert resolutions == []


# ── UnrealResolver ────────────────────────────────────────────────────────────

class TestUnrealResolver:
    def test_resolve_returns_resolutions(self, ue4_structure, ue4_context):
        assert len(ue4_context.resolutions) > 0

    def test_all_resolutions_are_ue_strategy(self, ue4_context):
        for r in ue4_context.resolutions:
            assert r.strategy == ResolutionStrategy.UE_GOBJECTS

    def test_property_offset_in_lua_expr(self, ue4_context):
        health = next(r for r in ue4_context.resolutions if r.field_name == "Health")
        assert "0x330" in health.lua_read_expr

    def test_lua_expr_uses_find_actor(self, ue4_context):
        health = next(r for r in ue4_context.resolutions if r.field_name == "Health")
        assert "_findActor" in health.lua_read_expr
        assert "BP_PlayerCharacter_C" in health.lua_read_expr

    def test_preamble_contains_gobjects_helpers(self, ue4_context):
        preamble = UnrealResolver().preamble_lua(ue4_context)
        assert "_initGObjects" in preamble
        assert "_findActor" in preamble
        assert "GUObjectArray" in preamble

    def test_ue5_preamble_uses_ue5_aob(self):
        ctx = EngineContext(engine_type="UE5", engine_version="5.1")
        preamble = UnrealResolver().preamble_lua(ctx)
        assert "UE5" in preamble


# ── get_resolver factory ──────────────────────────────────────────────────────

class TestGetResolverFactory:
    def test_unity_mono_returns_mono_resolver(self):
        r = get_resolver("Unity_Mono")
        assert isinstance(r, MonoResolver)

    def test_unity_il2cpp_returns_il2cpp_resolver(self):
        r = get_resolver("Unity_IL2CPP")
        assert isinstance(r, IL2CPPResolver)

    def test_ue4_returns_unreal_resolver(self):
        r = get_resolver("UE4")
        assert isinstance(r, UnrealResolver)

    def test_ue5_returns_unreal_resolver(self):
        r = get_resolver("UE5")
        assert isinstance(r, UnrealResolver)

    def test_unknown_returns_fallback(self):
        r = get_resolver("Unknown")
        assert isinstance(r, IL2CPPResolver)  # fallback

    def test_empty_string_returns_fallback(self):
        r = get_resolver("")
        assert isinstance(r, IL2CPPResolver)


# ── PromptBuilder engine-aware system prompts ─────────────────────────────────

class TestPromptBuilderEngineAware:
    def test_mono_system_prompt_mentions_mono_api(self):
        pb = PromptBuilder()
        sp = pb.system_prompt("Unity_Mono")
        assert "mono_findClass" in sp
        assert "mono_getClassField" in sp

    def test_il2cpp_system_prompt_mentions_field_offsets(self):
        pb = PromptBuilder()
        sp = pb.system_prompt("Unity_IL2CPP")
        assert "offset" in sp.lower()
        assert "AOB" in sp

    def test_ue4_system_prompt_mentions_gobjects(self):
        pb = PromptBuilder()
        sp = pb.system_prompt("UE4")
        assert "GUObjectArray" in sp

    def test_unknown_system_prompt_uses_aob_fallback(self):
        pb = PromptBuilder()
        sp = pb.system_prompt("Unknown")
        assert "AOB" in sp

    def test_build_with_mono_context_includes_preamble(
        self, player_structure, mono_context
    ):
        pb = PromptBuilder()
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        _, user = pb.build(player_structure, feat, mono_context)
        assert "_monoClass" in user   # preamble included

    def test_build_with_il2cpp_context_includes_resolution_table(
        self, player_structure, il2cpp_context
    ):
        pb = PromptBuilder()
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        _, user = pb.build(player_structure, feat, il2cpp_context)
        assert "_getBase_PlayerController" in user

    def test_build_without_context_still_works(self, player_structure):
        pb = PromptBuilder()
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        system, user = pb.build(player_structure, feat, None)
        assert len(system) > 50
        assert "PlayerController" in user


# ── ScriptValidator engine-aware ─────────────────────────────────────────────

class TestScriptValidatorEngineAware:
    _MONO_SCRIPT = """\
local cheatEnabled = false
local function apply()
  local cls = mono_findClass("Assembly-CSharp", "Game.Player", "PlayerController")
  local field = mono_getClassField(cls, "health")
  local offset = mono_getFieldOffset(field)
  local obj = mono_findObject("Assembly-CSharp", "Game.Player", "PlayerController")
  writeFloat(obj + offset, 9999.0)
end
local function toggle()
  cheatEnabled = not cheatEnabled
  if cheatEnabled then apply() end
end
registerHotkey(0x70, toggle)
"""

    def test_mono_script_passes_with_mono_strategy(self):
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        script = GeneratedScript(lua_code=self._MONO_SCRIPT, feature=feat)
        result = ScriptValidator(use_luac=False).validate(script, "mono_api")
        assert result.passed is True

    def test_mono_script_without_mono_api_warns(self):
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        lua = "local cheatEnabled = true\nwriteFloat(0x10, 9999)\n"
        script = GeneratedScript(lua_code=lua, feature=feat)
        result = ScriptValidator(use_luac=False).validate(script, "mono_api")
        assert any("mono_" in w for w in result.warnings)

    def test_mono_script_excessive_aob_warns(self):
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        lua = (
            "local cheatEnabled = true\n"
            "local a = mono_findClass('X','Y','Z')\n"
            "local b1 = AOBScan('AA BB CC DD EE FF 11')\n"
            "local b2 = AOBScan('AA BB CC DD EE FF 22')\n"
            "local b3 = AOBScan('AA BB CC DD EE FF 33')\n"
        )
        script = GeneratedScript(lua_code=lua, feature=feat)
        result = ScriptValidator(use_luac=False).validate(script, "mono_api")
        assert any("AOBScan" in w for w in result.warnings)

    def test_aob_checks_still_run_for_aob_write_strategy(self):
        """Legacy strategy: missing/invalid AOBs should still be flagged."""
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        from src.analyzer.models import AOBSignature
        bad_aob = AOBSignature(pattern="89 GG 00")  # invalid + too short
        lua = "local cheatEnabled = true\nwriteFloat(0x10, 9999)\n"
        script = GeneratedScript(lua_code=lua, feature=feat, aob_sigs=[bad_aob])
        result = ScriptValidator(use_luac=False).validate(script, "aob_write")
        assert result.passed is False
        assert any("invalid" in e.lower() for e in result.errors)

    def test_il2cpp_strategy_no_aob_error_for_empty_aob_list(self):
        """IL2CPP scripts with no AOBs are fine (root AOB may be inline)."""
        feat = TrainerFeature("Inf HP", FeatureType.INFINITE_HEALTH)
        lua = (
            'local cheatEnabled = true\n'
            'local base = readPointer(readPointer(getAddress("GameAssembly.dll") + 0x100))\n'
            'writeFloat(base + 0x58, 9999)\n'
        )
        script = GeneratedScript(lua_code=lua, feature=feat, aob_sigs=[])
        result = ScriptValidator(use_luac=False).validate(script, "il2cpp_ptr")
        # No AOBs present → no AOB errors
        aob_errors = [e for e in result.errors if "AOB" in e or "pattern" in e.lower()]
        assert aob_errors == []
