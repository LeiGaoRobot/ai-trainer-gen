"""Abstract base class for all resolvers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dumper.models import StructureJSON

from .models import EngineContext, FieldResolution

__all__ = ["AbstractResolver"]


class AbstractResolver(ABC):
    """
    Translates StructureJSON class/field data into runtime FieldResolution
    objects using the resolution strategy appropriate for a given engine.

    Each concrete subclass targets one engine type.
    """

    @abstractmethod
    def resolve(
        self,
        structure: "StructureJSON",
        context: EngineContext,
    ) -> list[FieldResolution]:
        """
        Produce FieldResolution objects for every field that is worth
        exposing to the LLM.

        Implementations should:
          • Prioritise gameplay-relevant fields (health, ammo, gold, …)
          • Populate `lua_read_expr` and `lua_write_expr` for each resolution
          • Set `confidence` < 1.0 when a field name is ambiguous

        Returns an ordered list, most important fields first.
        """

    @abstractmethod
    def preamble_lua(self, context: EngineContext) -> str:
        """
        Return Lua helper code that MUST appear at the top of every generated
        script for this engine (e.g. GObjects initialisation, getPlayerBase).
        May return an empty string if no preamble is needed.
        """

    @property
    @abstractmethod
    def strategy(self) -> "ResolutionStrategy":  # noqa: F821
        """The ResolutionStrategy this resolver implements."""
