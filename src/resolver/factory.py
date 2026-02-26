"""Factory function — returns the right resolver for a given engine type."""

from __future__ import annotations

from .base import AbstractResolver
from .il2cpp_resolver import IL2CPPResolver
from .models import ResolutionStrategy
from .mono_resolver import MonoResolver
from .unreal_resolver import UnrealResolver

__all__ = ["get_resolver"]

_RESOLVER_MAP: dict[str, AbstractResolver] = {
    "Unity_Mono":   MonoResolver(),
    "Unity_IL2CPP": IL2CPPResolver(),
    "UE4":          UnrealResolver(),
    "UE5":          UnrealResolver(),
}

# Default fallback — used when engine is Unknown
_FALLBACK = IL2CPPResolver()


def get_resolver(engine_type: str) -> AbstractResolver:
    """
    Return the resolver instance for the given EngineType value string.

    Parameters
    ----------
    engine_type : EngineType.value string, e.g. "Unity_Mono" or "UE4"

    Returns
    -------
    AbstractResolver appropriate for that engine.
    Falls back to IL2CPPResolver (pointer-chain) for unknown engines.
    """
    return _RESOLVER_MAP.get(engine_type, _FALLBACK)
