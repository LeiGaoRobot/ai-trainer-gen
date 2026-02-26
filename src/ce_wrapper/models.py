"""Data models for the ce_wrapper module."""

import logging
from dataclasses import dataclass, field
from typing import Optional

__all__ = ["CEProcess", "InjectionResult"]

logger = logging.getLogger(__name__)


@dataclass
class CEProcess:
    """
    Represents a game process that CE has attached to.

    pid       — OS process identifier
    name      — executable file name, e.g. "MyGame.exe"
    is_64bit  — True if the process is 64-bit (default); False for 32-bit
    """
    pid:      int
    name:     str
    is_64bit: bool = True

    def __str__(self) -> str:
        bits = "64" if self.is_64bit else "32"
        return f"CEProcess({self.name}, pid={self.pid}, {bits}-bit)"


@dataclass
class InjectionResult:
    """
    Result of a single CEBridge.inject() call.

    success     — True iff the script was injected and activated successfully
    feature_id  — identifier of the TrainerFeature that was injected
    error       — human-readable error message when success is False
    address     — resolved memory address (for debugging), may be None
    """
    success:    bool
    feature_id: str
    error:      Optional[str] = None
    address:    Optional[int] = None

    def __str__(self) -> str:
        if self.success:
            return f"InjectionResult(OK, feature={self.feature_id})"
        return f"InjectionResult(FAIL, feature={self.feature_id}, error={self.error!r})"
