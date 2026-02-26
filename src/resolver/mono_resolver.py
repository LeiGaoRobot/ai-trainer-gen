"""
MonoResolver — Unity Mono runtime address resolution.

Leverages CE's built-in Mono bridge:
    mono_findClass(assembly, namespace, class)  → classPtr
    mono_getClassField(classPtr, fieldName)     → fieldDescriptor
    mono_getFieldOffset(fieldDescriptor)        → byte offset

No AOB scanning required for individual fields — CE resolves offsets
dynamically from Mono's own metadata at runtime.

The only AOB needed (optionally) is to find the single-instance root object
when it's not accessible via a known static field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dumper.models import StructureJSON

from .base import AbstractResolver
from .models import EngineContext, FieldResolution, ResolutionStrategy

__all__ = ["MonoResolver"]

# Fields that aren't useful to expose individually
_SKIP_TYPES = {"UnityEngine.Transform", "GameObject", "Component",
               "Animator", "Rigidbody", "Collider"}


class MonoResolver(AbstractResolver):
    """Resolver for Unity Mono games."""

    @property
    def strategy(self) -> ResolutionStrategy:
        return ResolutionStrategy.MONO_API

    # ── Public API ────────────────────────────────────────────────────────

    def resolve(
        self,
        structure: "StructureJSON",
        context: EngineContext,
    ) -> list[FieldResolution]:
        """
        For each class/field in the StructureJSON, emit a FieldResolution
        that uses `mono_findClass` + `mono_getFieldOffset`.

        The generated lua_write_expr references `_getObj_{class}()` — a
        per-class helper the LLM is expected to implement (typically by
        finding the MonoBehaviour instance via a static singleton or
        CE's `mono_findObject`).
        """
        results: list[FieldResolution] = []
        assembly = context.assembly_name or "Assembly-CSharp"

        for cls in structure.classes:
            if not cls.fields:
                continue

            obj_helper = f"_getObj_{cls.name}()"

            for fld in cls.fields:
                if fld.type in _SKIP_TYPES:
                    continue
                if fld.is_static:
                    # Static fields use mono_getStaticFieldValue
                    read_expr, write_expr = self._static_exprs(
                        assembly, cls.namespace, cls.name, fld.name, fld.type
                    )
                else:
                    read_expr, write_expr = self._instance_exprs(
                        assembly, cls.namespace, cls.name,
                        fld.name, fld.type, obj_helper
                    )

                results.append(FieldResolution(
                    class_name=cls.name,
                    field_name=fld.name,
                    field_type=fld.type,
                    strategy=ResolutionStrategy.MONO_API,
                    mono_assembly=assembly,
                    mono_namespace=cls.namespace,
                    lua_read_expr=read_expr,
                    lua_write_expr=write_expr,
                ))

        return results

    def preamble_lua(self, context: EngineContext) -> str:
        """
        Helper infrastructure common to all Mono scripts.

        Provides `_monoField(cls, name)` and a pattern for per-class
        object finders.  The LLM must implement `_getObj_<ClassName>()`.
        """
        assembly = context.assembly_name or "Assembly-CSharp"
        return f"""\
-- ── Mono runtime helpers ─────────────────────────────────────────────────────
-- Assembly: {assembly}
-- CE Mono bridge functions used: mono_findClass, mono_getClassField,
--   mono_getFieldOffset, mono_object_get_field_address

local _classCache = {{}}
local _fieldCache  = {{}}

local function _monoClass(ns, name)
  local key = ns .. "." .. name
  if not _classCache[key] then
    _classCache[key] = mono_findClass("{assembly}", ns, name)
  end
  return _classCache[key]
end

local function _monoField(ns, className, fieldName)
  local key = ns .. "." .. className .. ":" .. fieldName
  if not _fieldCache[key] then
    local cls = _monoClass(ns, className)
    if cls then
      _fieldCache[key] = mono_getClassField(cls, fieldName)
    end
  end
  return _fieldCache[key]
end

local function _monoOffset(ns, className, fieldName)
  local f = _monoField(ns, className, fieldName)
  return f and mono_getFieldOffset(f) or nil
end

-- TODO: Implement per-class object finders, e.g.:
--   function _getObj_PlayerController()
--     return mono_findObject("{assembly}", "Game.Player", "PlayerController")
--   end
-- ─────────────────────────────────────────────────────────────────────────────
"""

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _instance_exprs(
        assembly: str, ns: str, cls: str, field: str,
        ftype: str, obj_helper: str,
    ) -> tuple[str, str]:
        read_fn  = FieldResolution(cls, field, ftype, ResolutionStrategy.MONO_API).ce_read_fn()
        write_fn = read_fn.replace("read", "write")

        offset_call = f'_monoOffset("{ns}", "{cls}", "{field}")'
        read_expr  = f'{read_fn}({obj_helper} + {offset_call})'
        write_expr = f'{write_fn}({obj_helper} + {offset_call}, {{value}})'
        return read_expr, write_expr

    @staticmethod
    def _static_exprs(
        assembly: str, ns: str, cls: str, field: str, ftype: str
    ) -> tuple[str, str]:
        read_fn  = FieldResolution(cls, field, ftype, ResolutionStrategy.MONO_API).ce_read_fn()
        write_fn = read_fn.replace("read", "write")

        addr_expr = f'mono_getStaticFieldAddress(mono_getClassField(mono_findClass("{assembly}", "{ns}", "{cls}"), "{field}"))'
        read_expr  = f'{read_fn}({addr_expr})'
        write_expr = f'{write_fn}({addr_expr}, {{value}})'
        return read_expr, write_expr
