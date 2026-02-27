"""
Project-wide custom exception hierarchy.
All modules raise subclasses of TrainerBaseError — never bare Exception.
"""

__all__ = [
    "TrainerBaseError",
    "DetectorError",
    "UnsupportedEngineError",
    "DumperError",
    "UnsupportedVersionError",
    "DumpTimeoutError",
    "LLMAnalyzerError",
    "LLMAPIError",
    "ScriptGenerationError",
    "CEWrapperError",
    "ProcessNotFoundError",
    "ScriptExecutionError",
    "BridgeError",
    "BridgeNotAvailableError",
    "StoreError",
]


class TrainerBaseError(Exception):
    """Root exception for all ai-trainer-gen errors."""


# ── Detector ──────────────────────────────────────────────────────────────────

class DetectorError(TrainerBaseError):
    """Raised when engine detection fails unrecoverably."""


class UnsupportedEngineError(DetectorError):
    """Raised when no Dumper exists for the detected engine type."""


# ── Dumper ────────────────────────────────────────────────────────────────────

class DumperError(TrainerBaseError):
    """Raised when structure dumping fails."""


class UnsupportedVersionError(DumperError):
    """Raised when the engine version is outside the supported range."""


class DumpTimeoutError(DumperError):
    """Raised when the dump operation exceeds the configured timeout."""


# ── LLM Analyzer ──────────────────────────────────────────────────────────────

class LLMAnalyzerError(TrainerBaseError):
    """Base class for LLM-related errors."""


class LLMAPIError(LLMAnalyzerError):
    """Raised when the upstream LLM API call fails (network, auth, rate-limit)."""


class ScriptGenerationError(LLMAnalyzerError):
    """Raised when valid script cannot be produced after MAX_RETRIES attempts."""


# ── CE Wrapper ────────────────────────────────────────────────────────────────

class CEWrapperError(TrainerBaseError):
    """Base class for Cheat Engine wrapper errors."""


class ProcessNotFoundError(CEWrapperError):
    """Raised when the target process is not running."""


class ScriptExecutionError(CEWrapperError):
    """Raised when a Lua script execution fails inside CE."""


class BridgeError(CEWrapperError):
    """Raised when a CE COM bridge operation fails."""


class BridgeNotAvailableError(BridgeError):
    """Raised when the CE COM bridge is unavailable (non-Windows or CE not installed)."""


# ── Store ─────────────────────────────────────────────────────────────────────

class StoreError(TrainerBaseError):
    """Raised on SQLite / store I/O errors."""
