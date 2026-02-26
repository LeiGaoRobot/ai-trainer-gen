"""Abstract base class for all structure dumpers."""

from abc import ABC, abstractmethod

from src.detector.models import EngineInfo
from src.exceptions import UnsupportedEngineError
from .models import StructureJSON

__all__ = ["AbstractDumper", "get_dumper"]


class AbstractDumper(ABC):
    """
    All engine-specific dumpers implement this interface.
    The factory function get_dumper() selects the right implementation.
    """

    @abstractmethod
    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        """
        Export the game's class/field structure.

        Args:
            engine_info: Output of GameEngineDetector.detect().

        Returns:
            Normalised StructureJSON ready for LLMAnalyzer.

        Raises:
            DumperError: Dump failed.
            UnsupportedVersionError: Engine version not supported.
            DumpTimeoutError: Operation timed out.
        """
        ...

    @abstractmethod
    def supports(self, engine_info: EngineInfo) -> bool:
        """Return True if this dumper handles the given engine."""
        ...


def get_dumper(engine_info: EngineInfo) -> "AbstractDumper":
    """
    Factory: return the correct AbstractDumper for the given engine.

    Import is deferred to avoid circular imports between sub-modules.

    Raises:
        UnsupportedEngineError: No registered dumper supports the engine.
    """
    from .unity_mono import UnityMonoDumper
    from .il2cpp import IL2CPPDumper
    from .ue import UnrealDumper

    dumpers: list[AbstractDumper] = [
        IL2CPPDumper(),
        UnityMonoDumper(),
        UnrealDumper(),
    ]
    for dumper in dumpers:
        if dumper.supports(engine_info):
            return dumper

    raise UnsupportedEngineError(
        f"No dumper available for engine: {engine_info.type} {engine_info.version}"
    )
