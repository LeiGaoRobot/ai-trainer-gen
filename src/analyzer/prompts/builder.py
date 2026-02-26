"""
PromptBuilder — engine-aware LLM prompt assembly for CE Lua script generation.

Each engine gets its own system-prompt extension and output contract:

  Unity Mono    → CE mono_* API, no AOB for individual fields
  Unity IL2CPP  → known field offsets + one root AOB per class
  UE4 / UE5     → GObjects walk + static property offsets
  Unknown       → legacy AOB-for-write-instruction (original fallback)

The resolver module pre-computes FieldResolution objects that contain
ready-made lua_read_expr / lua_write_expr snippets, which the builder
inlines into the prompt so the LLM knows exactly what CE Lua patterns
to use for each field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..models import FeatureType, TrainerFeature

if TYPE_CHECKING:
    from src.dumper.models import StructureJSON
    from src.resolver.models import EngineContext

__all__ = ["PromptBuilder"]


# ── Shared output-format contract ─────────────────────────────────────────────

_OUTPUT_CONTRACT = """\
Output format — three delimited sections (all required):
  [SCRIPT_BEGIN]
  <Complete CE Lua script>
  [SCRIPT_END]
  [AOB_BEGIN]
  <one AOB per line: PATTERN | OFFSET | MODULE | DESCRIPTION>
  (Leave this section empty if no AOBs are used — e.g. for Mono scripts)
  [AOB_END]
"""

# ── Shared coding rules ───────────────────────────────────────────────────────

_SHARED_RULES = """\
Rules you MUST follow:
1. Output ONLY valid CE Lua inside the delimiters. No markdown fences.
2. Include an enable/disable toggle (`cheatEnabled` flag + hotkey).
3. Add inline comments so the user understands each section.
4. If provided field access expressions are incomplete (e.g. `_getObj_X()`
   is not yet defined), implement sensible stubs with a clear TODO comment.
5. If information is genuinely insufficient, output `-- INSUFFICIENT_DATA`
   on its own line and explain why in comments.
"""

# ── Engine-specific system-prompt addenda ─────────────────────────────────────

_ENGINE_ADDENDUM = {
    "Unity_Mono": """\
ENGINE: Unity Mono (CE built-in Mono bridge)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Available CE Mono Lua API:
  mono_findClass(assembly, namespace, class)  → classPtr
  mono_getClassField(classPtr, fieldName)     → fieldDescriptor
  mono_getFieldOffset(fieldDescriptor)        → integer byte offset
  mono_findObject(assembly, namespace, class) → first live instance (slow)
  mono_object_get_field_address(obj, field)   → direct field address

Key rules:
• DO NOT use AOBScan for individual fields — Mono resolves offsets at runtime.
• The preamble below includes `_monoClass`, `_monoField`, `_monoOffset` helpers.
• Use the pre-built `lua_write_expr` snippets from the field list below.
• To find a live object instance, prefer a known static singleton field over
  `mono_findObject` (which is slow on large heaps).
• AOBs are only acceptable for finding static singleton pointers if no
  static field path exists.
""",

    "Unity_IL2CPP": """\
ENGINE: Unity IL2CPP (AoT-compiled, static field offsets known)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Key rules:
• Field offsets are FIXED (AoT compilation) — use them directly.
• DO NOT AOBScan for write instructions for individual fields.
• Use ONE AOB per class to find its singleton/static root pointer.
• The preamble below includes `_resolveRIP` and `_findRoot` helpers.
• Implement `_getBase_<ClassName>()` for each class using `_findRoot`.
• Singleton pattern: `48 8B 05 ?? ?? ?? ??` (RIP-relative MOV in GameAssembly.dll)
• After finding the root, walk a short pointer chain (usually 1-3 hops).
""",

    "UE4": """\
ENGINE: Unreal Engine 4 (GUObjectArray + static property offsets)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Key rules:
• ONE AOB locates GUObjectArray at startup (see preamble `_initGObjects`).
• Use `_findActor(className)` from the preamble to locate any UObject.
• Property offsets from the UE4SS dump are correct — apply them directly.
• DO NOT AOBScan for individual properties.
• Cache `_findActor` results — the array walk is expensive.
• Invalidate cache on level loads if the script stays resident.
""",

    "UE5": """\
ENGINE: Unreal Engine 5 (GUObjectArray + static property offsets)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Same strategy as UE4 but GUObjectArray layout changed slightly.
The preamble uses the correct UE5 AOB and offsets automatically.
All other rules identical to UE4.
""",

    "Unknown": """\
ENGINE: Unknown (AOB write-instruction fallback)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Falling back to traditional CE AOB scanning for write instructions.
Rules:
• Each AOB must be ≥ 7 bytes with ≤ 50% wildcards.
• Scan target module if known; otherwise scan all modules.
• NOP or hook the write instruction rather than polling a value.
""",
}

# ── Per-feature implementation hints (unchanged from before) ─────────────────

_FEATURE_HINTS: dict[FeatureType, str] = {
    FeatureType.INFINITE_HEALTH: """\
Target: prevent health from decreasing.
Fields: look for "health", "hp", "currentHp", "hitPoints".
Strategy: use the lua_write_expr for the health field — write max value
  on every game tick, OR freeze the write path for Mono/IL2CPP engines.""",

    FeatureType.INFINITE_MANA: """\
Target: prevent mana/MP from depleting.
Fields: "mana", "mp", "magicPoints", "currentMana".
Strategy: same as infinite health.""",

    FeatureType.INFINITE_AMMO: """\
Target: prevent ammo/magazine count from decreasing.
Fields: "ammo", "currentAmmo", "magazineAmmo", "clipSize".
Strategy: write max ammo on every tick, or hook the decrement path.""",

    FeatureType.INFINITE_STAMINA: """\
Target: keep stamina from depleting.
Fields: "stamina", "currentStamina", "energy".
Strategy: write max value on tick.""",

    FeatureType.INFINITE_CURRENCY: """\
Target: gold/coins never decrease.
Fields: "gold", "coins", "currency", "money".
Strategy: write a high value periodically, or hook the spend path.""",

    FeatureType.INFINITE_ITEMS: """\
Target: consumable item counts don't decrease on use.
Strategy: hook the inventory decrement and skip it.""",

    FeatureType.GODMODE: """\
Target: complete damage immunity.
Strategy: combine infinite health with zeroing incoming damage.
  Requires two field writes: keep health at max AND zero damage value.""",

    FeatureType.ONE_HIT_KILL: """\
Target: every player attack kills in one hit.
Strategy: write 0 to enemy health field; filter by actor type to avoid
  killing the player.""",

    FeatureType.NO_RELOAD: """\
Target: weapon never needs reloading.
Strategy: keep ammo at clip capacity; override the empty-check branch.""",

    FeatureType.SPEED_HACK: """\
Target: multiply movement speed by a configurable factor.
Fields: "moveSpeed", "walkSpeed", "runSpeed".
Strategy: read current value on enable, multiply by factor; restore on disable.""",

    FeatureType.FREEZE_TIMER: """\
Target: stop game timer from counting down.
Fields: "time", "remainingTime", "timer", "countdown".
Strategy: write the captured value back every tick.""",

    FeatureType.TELEPORT: """\
Target: save and restore player position.
Fields: Vector3 position or separate posX/posY/posZ fields.
Strategy: on "save" press read all three; on "teleport" press write them back.""",

    FeatureType.CUSTOM: """\
Target: implement the user-described feature using available structure data.""",
}


# ── PromptBuilder ─────────────────────────────────────────────────────────────

class PromptBuilder:
    """
    Builds (system_prompt, user_message) tuples for LLMAnalyzer.

    Usage::
        builder = PromptBuilder()
        # With engine context (preferred):
        system, user = builder.build(structure, feature, engine_context)
        # Without (legacy AOB fallback):
        system, user = builder.build(structure, feature)
    """

    def system_prompt(self, engine_type: Optional[str] = None) -> str:
        """Return the system prompt for the given engine type."""
        addendum = _ENGINE_ADDENDUM.get(engine_type or "Unknown",
                                        _ENGINE_ADDENDUM["Unknown"])
        return "\n\n".join([
            "You are an expert Cheat Engine (CE) Lua script writer for "
            "single-player PC games.",
            addendum.strip(),
            _SHARED_RULES.strip(),
            _OUTPUT_CONTRACT.strip(),
        ])

    def build(
        self,
        structure: "StructureJSON",
        feature: TrainerFeature,
        engine_context: Optional["EngineContext"] = None,
        max_classes: int = 60,
    ) -> tuple[str, str]:
        """
        Return (system_prompt, user_message).

        Parameters
        ----------
        structure       : StructureJSON from the Dumper module
        feature         : TrainerFeature describing what the user wants
        engine_context  : EngineContext with pre-computed FieldResolutions
                          (None → legacy AOB fallback)
        max_classes     : cap on classes shown in the structure section
        """
        engine_type = engine_context.engine_type if engine_context else None
        system = self.system_prompt(engine_type)
        user   = self._build_user(structure, feature, engine_context, max_classes)
        return system, user

    # ── Internal ──────────────────────────────────────────────────────────

    def _build_user(
        self,
        structure: "StructureJSON",
        feature: TrainerFeature,
        ctx: Optional["EngineContext"],
        max_classes: int,
    ) -> str:
        parts: list[str] = []

        # ── Section 1: Game structure ─────────────────────────────────────
        parts += ["## Game Structure", structure.to_prompt_str(max_classes), ""]

        # ── Section 2: Engine context + resolver preamble ─────────────────
        if ctx:
            parts += [
                "## Engine Context",
                f"Engine : {ctx.engine_type}  (v{ctx.engine_version}, "
                f"{ctx.bitness}-bit)",
                f"Module : {ctx.module_name or '(auto-detect)'}",
                "",
            ]
            if ctx.resolutions:
                parts += self._resolution_table(ctx)

        # ── Section 3: Script preamble ────────────────────────────────────
        if ctx:
            from src.resolver.factory import get_resolver
            resolver = get_resolver(ctx.engine_type)
            preamble = resolver.preamble_lua(ctx).strip()
            if preamble:
                parts += [
                    "## Required Script Preamble",
                    "Include this verbatim at the top of your script:",
                    "```lua",
                    preamble,
                    "```",
                    "",
                ]

        # ── Section 4: Feature request ────────────────────────────────────
        parts += [
            "## Requested Feature",
            f"Name : {feature.name}",
            f"Type : {feature.feature_type.value}",
        ]
        if feature.description:
            parts += [f"Description: {feature.description}"]
        if feature.hotkey:
            parts += [f"Hotkey: {feature.hotkey}"]

        # ── Section 5: Implementation hint ────────────────────────────────
        hint = _FEATURE_HINTS.get(feature.feature_type,
                                   _FEATURE_HINTS[FeatureType.CUSTOM])
        parts += ["", "## Implementation Guidance", hint, ""]

        parts += ["Now generate the CE Lua script following the output format above."]
        return "\n".join(parts)

    @staticmethod
    def _resolution_table(ctx: "EngineContext") -> list[str]:
        """Format the pre-computed FieldResolution list for the prompt."""
        lines = ["## Pre-resolved Field Access (use these expressions directly)"]
        lines.append(
            "| Class | Field | Type | Read expression | Write expression |"
        )
        lines.append("|-------|-------|------|-----------------|-----------------|")
        for r in ctx.resolutions[:40]:  # cap to avoid token explosion
            lines.append(
                f"| {r.class_name} | {r.field_name} | {r.field_type} "
                f"| `{r.lua_read_expr}` | `{r.lua_write_expr}` |"
            )
        if len(ctx.resolutions) > 40:
            lines.append(f"_(… {len(ctx.resolutions) - 40} more fields omitted)_")
        lines.append("")
        return lines
