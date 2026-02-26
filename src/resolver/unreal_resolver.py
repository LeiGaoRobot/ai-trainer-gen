"""
UnrealResolver — UE4 / UE5 address resolution via GUObjectArray.

Strategy:
  1. ONE AOB scan locates GUObjectArray (game-version-stable pattern).
  2. Walk the object array to find a target actor by class name.
  3. Static property offsets from UE4SS dump are applied directly.

This avoids per-property AOB scanning entirely.  The GObjects AOB
needs to be updated on major engine version changes but is otherwise
very stable because it targets GUObjectArray initialisation code,
not game-specific logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dumper.models import StructureJSON

from .base import AbstractResolver
from .models import EngineContext, FieldResolution, ResolutionStrategy

__all__ = ["UnrealResolver"]

# Standard GUObjectArray AOB for UE4 / UE5 (x64).
# Targets the TUObjectArray::AddUObjectToArray call site.
_GOBJECTS_AOB_UE4 = "48 8B 05 ?? ?? ?? ?? 48 8B 0C C8 48 8B 04 D1"
_GOBJECTS_AOB_UE5 = "48 89 05 ?? ?? ?? ?? E9"  # slightly different in UE5

# UObjectBase offsets (engine-version stable)
_UOB_CLASS_PRIVATE = 0x10   # UObjectBase::ClassPrivate
_UOB_NAME_PRIVATE  = 0x18   # UObjectBase::NamePrivate (FName index)


class UnrealResolver(AbstractResolver):
    """Resolver for Unreal Engine 4/5 games."""

    @property
    def strategy(self) -> ResolutionStrategy:
        return ResolutionStrategy.UE_GOBJECTS

    # ── Public API ────────────────────────────────────────────────────────

    def resolve(
        self,
        structure: "StructureJSON",
        context: EngineContext,
    ) -> list[FieldResolution]:
        """
        Emit one FieldResolution per class/field pair.

        lua_write_expr references `_findActor("{class}")` — a helper
        that walks GUObjectArray, provided in preamble_lua().
        """
        results: list[FieldResolution] = []

        for cls in structure.classes:
            if not cls.fields:
                continue

            actor_expr = f'_findActor("{cls.name}")'

            for fld in cls.fields:
                if not fld.offset:
                    continue
                try:
                    offset_int = int(fld.offset, 16) if fld.offset.startswith("0x") \
                                 else int(fld.offset, 16)
                except (ValueError, AttributeError):
                    continue

                read_fn  = FieldResolution(cls.name, fld.name, fld.type,
                                           ResolutionStrategy.UE_GOBJECTS).ce_read_fn()
                write_fn = read_fn.replace("read", "write")

                offset_hex = hex(offset_int)
                read_expr  = f"{read_fn}({actor_expr} + {offset_hex})"
                write_expr = f"{write_fn}({actor_expr} + {offset_hex}, {{value}})"

                results.append(FieldResolution(
                    class_name=cls.name,
                    field_name=fld.name,
                    field_type=fld.type,
                    strategy=ResolutionStrategy.UE_GOBJECTS,
                    ue_class_path=cls.name,
                    lua_read_expr=read_expr,
                    lua_write_expr=write_expr,
                    notes=f"Property offset {offset_hex} from UE4SS dump.",
                ))

        return results

    def preamble_lua(self, context: EngineContext) -> str:
        """GUObjectArray scanner + FName reader + _findActor helper."""
        is_ue5   = context.engine_type == "UE5"
        gobjects_aob = _GOBJECTS_AOB_UE5 if is_ue5 else _GOBJECTS_AOB_UE4
        engine_tag   = "UE5" if is_ue5 else "UE4"

        return f"""\
-- ── Unreal Engine ({engine_tag}) — GUObjectArray helpers ────────────────────────
-- GObjects AOB: {gobjects_aob}
-- UObjectBase offsets: ClassPrivate={hex(_UOB_CLASS_PRIVATE)}, NamePrivate={hex(_UOB_NAME_PRIVATE)}

local _GObjects   = nil
local _GNames     = nil
local _actorCache = {{}}

-- Resolve RIP-relative pointer (same pattern as IL2CPP)
local function _resolveRIP(addr)
  return addr + 7 + readInteger(addr + 3)
end

-- Initialise GUObjectArray (called once on script load)
local function _initGObjects()
  if _GObjects then return end
  local match = AOBScan("{gobjects_aob}")
  if match then
    _GObjects = _resolveRIP(match)
  end
end

-- Read an FName string from GNames table
local function _readFName(nameIndex)
  if not _GNames then return "" end
  local chunk  = readPointer(_GNames + (nameIndex >> 16) * 8)
  local entry  = chunk + (nameIndex & 0xFFFF) * 2
  local len    = readSmallInteger(entry)
  local strPtr = entry + 6
  return readString(strPtr, len)
end

-- Get class name of a UObject
local function _getClassName(obj)
  local classPtr = readPointer(obj + {hex(_UOB_CLASS_PRIVATE)})
  if classPtr == 0 then return "" end
  local nameIdx = readInteger(classPtr + {hex(_UOB_NAME_PRIVATE)})
  return _readFName(nameIdx)
end

-- Walk GUObjectArray to find first object whose class name matches
local function _findActor(className)
  _initGObjects()
  if not _GObjects then return 0 end
  if _actorCache[className] then return _actorCache[className] end

  local numObjs = readInteger(_GObjects + 0x14)
  for i = 0, numObjs - 1 do
    local entry = readPointer(_GObjects + 0x18 + i * 8)
    if entry ~= 0 then
      local obj = readPointer(entry)
      if obj ~= 0 and _getClassName(obj) == className then
        _actorCache[className] = obj
        return obj
      end
    end
  end
  return 0
end
-- ─────────────────────────────────────────────────────────────────────────────
"""
