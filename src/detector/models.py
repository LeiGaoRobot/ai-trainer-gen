"""Data models for the detector module."""

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["EngineType", "EngineInfo"]


class EngineType(str, Enum):
    UNITY_MONO   = "Unity_Mono"
    UNITY_IL2CPP = "Unity_IL2CPP"
    UE4          = "UE4"
    UE5          = "UE5"
    UNKNOWN      = "Unknown"


@dataclass
class EngineInfo:
    """
    Result returned by GameEngineDetector.detect().
    Passed downstream to the appropriate Dumper.
    """
    type:     EngineType
    version:  str           # e.g. "2022.3.10f1" or "4.27.2"
    bitness:  int           # 32 or 64
    exe_path: str           # absolute path to the main .exe
    game_dir: str           # parent directory of exe_path
    extra:    dict = field(default_factory=dict)
    # extra keys used by individual dumpers:
    #   Unity_Mono   → "mono_dll_path": str
    #   Unity_IL2CPP → "metadata_path": str, "assembly_path": str
    #   UE4 / UE5    → "ue_minor": int

    def __str__(self) -> str:
        return f"{self.type.value} {self.version} ({self.bitness}-bit)"
