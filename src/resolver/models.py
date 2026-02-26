"""
Data models for the resolver module.

Key concepts
────────────
ResolutionStrategy  — which CE Lua technique to use for this engine
FieldResolution     — how to access ONE specific field at runtime
EngineContext       — aggregated engine info passed to resolvers
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

__all__ = [
    "ResolutionStrategy",
    "FieldResolution",
    "EngineContext",
]


class ResolutionStrategy(str, Enum):
    """
    CE Lua address resolution technique, chosen per engine type.

    MONO_API
        CE's built-in Mono runtime bridge.
        Uses `mono_findClass`, `mono_getClassField`, `mono_getFieldOffset`.
        Most reliable for Unity Mono games — no AOB needed.

    IL2CPP_PTR
        Static field offset (from IL2CPPDumper) + pointer-chain AOB.
        One AOB locates the singleton root; subsequent ptr offsets reach
        the actual object.  Much more robust than per-field AOB scanning.

    UE_GOBJECTS
        Scans GUObjectArray (one AOB, game-version stable) then walks
        the object list to find the target actor by class name, and uses
        static property offsets from the UE4SS dump.

    AOB_WRITE
        Legacy / fallback: scan for the assembly instruction that writes
        the field and NOP/hook it.  Fragile across patches but works for
        engines with no better alternative.
    """
    MONO_API    = "mono_api"
    IL2CPP_PTR  = "il2cpp_ptr"
    UE_GOBJECTS = "ue_gobjects"
    AOB_WRITE   = "aob_write"


@dataclass
class FieldResolution:
    """
    Describes how to read/write ONE field at CE Lua runtime.

    The resolver populates `lua_read_expr` and `lua_write_expr` — the
    PromptBuilder inlines these directly into the generated script.

    lua_write_expr uses `{value}` as a placeholder for the value to write,
    e.g.  "writeFloat(getPlayerBase() + 0x58, {value})"
    """
    class_name:  str
    field_name:  str
    field_type:  str              # "float" | "int32" | "int64" | …
    strategy:    ResolutionStrategy

    # ── MONO_API fields ───────────────────────────────────────────────────
    mono_assembly:  str = "Assembly-CSharp"
    mono_namespace: str = ""       # e.g. "Game.Player"

    # ── IL2CPP_PTR fields ─────────────────────────────────────────────────
    field_offset:   int  = 0       # from dump (e.g. 0x58)
    # root_aob is omitted here; the IL2CPPResolver adds it to the script preamble

    # ── UE_GOBJECTS fields ────────────────────────────────────────────────
    ue_class_path:  str = ""       # e.g. "BP_PlayerCharacter_C"

    # ── Generated CE Lua snippets (filled by resolver) ────────────────────
    lua_read_expr:  str = ""       # expression that evaluates to the current value
    lua_write_expr: str = ""       # statement that writes {value}

    # ── Metadata ──────────────────────────────────────────────────────────
    confidence:     float = 1.0    # 0.0–1.0; lower if field name was guessed
    notes:          str   = ""

    # ── Helpers ───────────────────────────────────────────────────────────

    def ce_read_fn(self) -> str:
        """CE Lua read function name for this field's type."""
        return _CE_READ.get(self.field_type.lower(), "readFloat")

    def ce_write_fn(self) -> str:
        """CE Lua write function name for this field's type."""
        return _CE_WRITE.get(self.field_type.lower(), "writeFloat")

    def __str__(self) -> str:
        return (
            f"FieldResolution({self.class_name}.{self.field_name} "
            f"[{self.field_type}] via {self.strategy.value})"
        )


# CE Lua type → read/write function mapping
_CE_READ = {
    "float":   "readFloat",
    "single":  "readFloat",
    "double":  "readDouble",
    "int32":   "readInteger",
    "int":     "readInteger",
    "uint32":  "readInteger",
    "int64":   "readQword",
    "int16":   "readSmallInteger",
    "byte":    "readBytes",
    "bool":    "readBytes",
}
_CE_WRITE = {k: v.replace("read", "write") for k, v in _CE_READ.items()}
_CE_WRITE["readBytes"] = "writeBytes"


@dataclass
class EngineContext:
    """
    Enriched engine context passed to resolvers and PromptBuilder.

    Combines the raw EngineInfo with resolved field access metadata so
    the PromptBuilder never has to re-derive this information itself.
    """
    engine_type:  str             # EngineType value string, e.g. "Unity_IL2CPP"
    engine_version: str = ""
    bitness:      int  = 64
    exe_path:     str  = ""

    # Extra engine-specific paths / identifiers
    assembly_name:  str = "Assembly-CSharp"   # Unity only
    module_name:    str = ""                  # e.g. "GameAssembly.dll"

    # Resolved fields (filled by resolver)
    resolutions: list[FieldResolution] = field(default_factory=list)

    @classmethod
    def from_engine_info(cls, engine_info) -> "EngineContext":
        """
        Construct from a detector.EngineInfo object.
        `engine_info` is typed loosely to avoid a circular import.
        """
        module = ""
        assembly = engine_info.extra.get("assembly_name", "Assembly-CSharp")
        if engine_info.type.value == "Unity_IL2CPP":
            module = "GameAssembly.dll"
        elif engine_info.type.value in ("UE4", "UE5"):
            module = engine_info.extra.get("primary_module", "")
        return cls(
            engine_type=engine_info.type.value,
            engine_version=engine_info.version,
            bitness=engine_info.bitness,
            exe_path=engine_info.exe_path,
            assembly_name=assembly,
            module_name=module,
        )
