"""
IL2CPPResolver — Unity IL2CPP address resolution.

IL2CPP strategy:
  • Field offsets are ALREADY KNOWN from the static dump (e.g. 0x58).
    No per-field AOB scanning is needed.
  • ONE AOB locates the singleton/static root pointer for the relevant
    class (often a GameManager or similar).
  • From that root, a short pointer chain (usually 1-3 hops) reaches
    the actual MonoBehaviour instance.
  • The known field offset is applied to the resolved instance pointer.

This is far more reliable than the naïve AOB-for-every-field approach
because:
  1. The root-finder AOB is for a known singleton pattern, not a
     randomly generated write instruction.
  2. Field offsets don't change between game patches (IL2CPP is AoT).
  3. One AOB serves multiple fields in the same class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dumper.models import StructureJSON

from .base import AbstractResolver
from .models import EngineContext, FieldResolution, ResolutionStrategy

__all__ = ["IL2CPPResolver"]

# RIP-relative MOV pattern used to find static singletons in IL2CPP:
# 48 8B 05 ?? ?? ?? ??  →  mov rax, [rip + offset]
_SINGLETON_AOB_HINT = "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? 48 8B 40"

# Pointer size by bitness
_PTR_SIZE = {32: 4, 64: 8}


class IL2CPPResolver(AbstractResolver):
    """Resolver for Unity IL2CPP games (AoT compiled)."""

    @property
    def strategy(self) -> ResolutionStrategy:
        return ResolutionStrategy.IL2CPP_PTR

    # ── Public API ────────────────────────────────────────────────────────

    def resolve(
        self,
        structure: "StructureJSON",
        context: EngineContext,
    ) -> list[FieldResolution]:
        """
        Emit one FieldResolution per interesting class/field pair.

        For each class, lua_write_expr references `_getBase_{class}()`
        which the LLM must implement using the root AOB hint provided
        in preamble_lua().
        """
        results: list[FieldResolution] = []
        module = context.module_name or "GameAssembly.dll"

        for cls in structure.classes:
            if not cls.fields:
                continue

            base_helper = f"_getBase_{cls.name}()"

            for fld in cls.fields:
                if not fld.offset:
                    continue  # no offset info → can't resolve

                try:
                    offset_int = int(fld.offset, 16) if fld.offset.startswith("0x") \
                                 else int(fld.offset, 16)
                except (ValueError, AttributeError):
                    continue

                read_fn  = FieldResolution(cls.name, fld.name, fld.type,
                                           ResolutionStrategy.IL2CPP_PTR).ce_read_fn()
                write_fn = read_fn.replace("read", "write")

                offset_hex = hex(offset_int)
                read_expr  = f"{read_fn}({base_helper} + {offset_hex})"
                write_expr = f"{write_fn}({base_helper} + {offset_hex}, {{value}})"

                results.append(FieldResolution(
                    class_name=cls.name,
                    field_name=fld.name,
                    field_type=fld.type,
                    strategy=ResolutionStrategy.IL2CPP_PTR,
                    field_offset=offset_int,
                    lua_read_expr=read_expr,
                    lua_write_expr=write_expr,
                    notes=(
                        f"Field offset {offset_hex} from IL2CPPDumper. "
                        f"Implement _getBase_{cls.name}() with root AOB."
                    ),
                ))

        return results

    def preamble_lua(self, context: EngineContext) -> str:
        """
        Root-pointer resolution boilerplate for IL2CPP.

        Provides a `_resolveRIP(addr)` helper that dereferences a
        RIP-relative pointer (the standard IL2CPP singleton pattern) and
        a template `_getBase_*` function the LLM must specialise.
        """
        module = context.module_name or "GameAssembly.dll"
        ptr_size = _PTR_SIZE.get(context.bitness, 8)
        return f"""\
-- ── IL2CPP pointer-chain helpers ─────────────────────────────────────────────
-- Module : {module}
-- Bitness: {context.bitness}-bit  (pointer size = {ptr_size} bytes)
--
-- Strategy: ONE root AOB per class → pointer chain → known field offset
-- Field offsets are static (AoT compilation) — no per-field AOB needed.

local _baseCache = {{}}

-- Resolve a RIP-relative MOV instruction to its target address:
--   48 8B 05 [offset32]  →  next_instr_addr + offset32
local function _resolveRIP(matchAddr)
  local rel = readInteger(matchAddr + 3)    -- 4-byte signed offset
  return (matchAddr + 7 + rel)              -- RIP = matchAddr + 7
end

-- Generic AOB root finder: scans for pattern, resolves RIP pointer,
-- then walks an optional pointer chain.
-- chain: list of pointer offsets, e.g. {{0x20, 0x58}}
local function _findRoot(aobPattern, chain)
  local match = AOBScan(aobPattern, "{module}")
  if not match then return nil end
  local addr = readPointer(_resolveRIP(match))  -- dereference static ptr
  for _, off in ipairs(chain or {{}}) do
    if addr == 0 then return nil end
    addr = readPointer(addr + off)
  end
  return addr
end

-- TODO: Implement per-class base finders, using the AOB hint below.
-- Singleton pattern hint: "{_SINGLETON_AOB_HINT}"
-- Example:
--   local function _getBase_PlayerController()
--     if not _baseCache["PlayerController"] then
--       -- Find singleton root (scan once, cache result)
--       _baseCache["PlayerController"] = _findRoot(
--         "48 8B 05 ?? ?? ?? ?? 48 85 C0 74 ?? 48 8B 40",
--         {{0x18, 0x28}}  -- adjust chain to reach PlayerController instance
--       )
--     end
--     return _baseCache["PlayerController"]
--   end
-- ─────────────────────────────────────────────────────────────────────────────
"""
