"""
CEBridge — thin wrapper around the Cheat Engine COM automation interface.

Design
──────
• All real COM calls are gated behind _IS_WINDOWS so the module is fully
  importable (and testable) on macOS/Linux.
• The _com_factory parameter is an injectable callable → pass a lambda in
  tests; leave as None in production to use the real win32com.client.

Raises
──────
BridgeNotAvailableError  — non-Windows platform, or pywin32 not installed
BridgeError              — CE COM operation failed after connect()
"""

import logging
import platform
from typing import Any, Callable, List, Optional

from src.analyzer.models import AOBSignature, GeneratedScript
from src.ce_wrapper.models import CEProcess, InjectionResult
from src.exceptions import BridgeError, BridgeNotAvailableError

__all__ = ["CEBridge"]

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"
_CE_PROG_ID = "Cheat Engine.Application"


class CEBridge:
    """
    Wraps Cheat Engine COM automation.

    Usage (production)::

        with CEBridge() as bridge:
            proc = bridge.connect()
            result = bridge.inject(script, proc)
            hits = bridge.validate_aob(aob, proc)

    Usage (tests)::

        fake_app = MagicMock()
        bridge = CEBridge(_com_factory=lambda: fake_app)
    """

    def __init__(
        self,
        _com_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._com_factory = _com_factory
        self._app: Optional[Any] = None

    def connect(self, ce_path: str = "") -> CEProcess:
        """
        Connect to a running CE instance and return the attached process.

        Args:
            ce_path: Unused — reserved for future path-based CE launch.

        Returns:
            CEProcess describing the process CE is currently attached to.

        Raises:
            BridgeNotAvailableError: Not running on Windows, or pywin32 missing.
        """
        if not _IS_WINDOWS:
            raise BridgeNotAvailableError(
                "CE COM bridge requires Windows. "
                "On other platforms, use CTBuilder for offline .ct export only."
            )
        factory = self._com_factory or self._default_com_factory
        try:
            self._app = factory()
            pid  = self._app.OpenedProcessID
            name = self._app.OpenedProcessName
        except Exception as exc:  # noqa: BLE001
            self._app = None
            raise BridgeError(f"Failed to connect to CE: {exc}") from exc
        logger.info("CEBridge: connected to %s (pid=%s)", name, pid)
        return CEProcess(pid=pid, name=name)

    def inject(self, script: GeneratedScript, process: CEProcess) -> InjectionResult:
        """
        Execute script.lua_code inside CE and return the result.

        Returns InjectionResult(success=False, ...) on COM errors — never raises.
        Raises BridgeError if connect() was not called first.
        """
        if self._app is None:
            raise BridgeError("Not connected. Call connect() first.")
        try:
            self._app.ExecuteScript(script.lua_code)
            logger.info("CEBridge: injected feature '%s'", script.feature.name)
            return InjectionResult(success=True, feature_id=script.feature.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CEBridge: inject failed — %s", exc)
            return InjectionResult(
                success=False,
                feature_id=script.feature.name,
                error=str(exc),
            )

    def validate_aob(
        self,
        aob: AOBSignature,
        process: CEProcess,
    ) -> List[int]:
        """
        Scan process memory for aob and return matching addresses.

        Returns an empty list on COM errors or no hits — never raises.
        Raises BridgeError if connect() was not called first.
        """
        if self._app is None:
            raise BridgeError("Not connected. Call connect() first.")
        try:
            hits = self._app.AOBScan(aob.pattern) or []
            logger.debug("CEBridge: AOB '%s' → %d hits", aob.pattern, len(hits))
            return list(hits)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CEBridge: AOBScan failed — %s", exc)
            return []

    def close(self) -> None:
        """Release the COM reference."""
        self._app = None

    def __enter__(self) -> "CEBridge":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @staticmethod
    def _default_com_factory() -> Any:
        """
        Build the real Cheat Engine COM application object.

        Imported lazily to keep the module importable on non-Windows.
        Raises BridgeNotAvailableError if pywin32 is not installed.
        """
        try:
            import win32com.client  # type: ignore[import]
            return win32com.client.Dispatch(_CE_PROG_ID)
        except ImportError as exc:
            raise BridgeNotAvailableError(
                "pywin32 is not installed. Install with: pip install pywin32"
            ) from exc
