"""
Runtime address resolution strategies — bridges static dump data to CE Lua code.

Each resolver takes a StructureJSON + EngineInfo and outputs FieldResolution
objects that tell the PromptBuilder exactly which CE Lua patterns to use.
"""

from .base import AbstractResolver
from .factory import get_resolver
from .il2cpp_resolver import IL2CPPResolver
from .models import EngineContext, FieldResolution, ResolutionStrategy
from .mono_resolver import MonoResolver
from .unreal_resolver import UnrealResolver

__all__ = [
    "AbstractResolver",
    "get_resolver",
    "IL2CPPResolver",
    "MonoResolver",
    "UnrealResolver",
    "EngineContext",
    "FieldResolution",
    "ResolutionStrategy",
]
