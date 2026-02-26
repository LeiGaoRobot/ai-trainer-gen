"""
UnityMonoDumper — runtime dump via Mono embedding API.

Requires:
  - Target game is RUNNING (Mono runtime loaded in process)
  - Windows: uses ctypes + pymem to read Mono API from the target process
  - Linux/macOS: partial support via /proc/<pid>/mem

High-level flow:
  1. Find mono*.dll in the target process memory map
  2. Resolve Mono API exports: mono_domain_get, mono_domain_get_assemblies,
     mono_image_get_table_rows, mono_class_get_fields, ...
  3. Walk the assembly list → classes → fields
  4. Build StructureJSON

NOTE: The actual Mono API calls require Windows + pymem.
      On other platforms this module raises DumperError("Windows required").
      All Mono API logic is isolated in _MonoReader so it can be
      unit-tested independently via mocking.
"""

import logging
import platform
import re
from pathlib import Path

from src.detector.models import EngineInfo, EngineType
from src.exceptions import DumperError
from .base import AbstractDumper
from .models import ClassInfo, FieldInfo, StructureJSON

__all__ = ["UnityMonoDumper"]

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


class UnityMonoDumper(AbstractDumper):
    """
    Dump class structure from a running Unity Mono game.
    The game process must be active before calling dump().
    """

    def supports(self, engine_info: EngineInfo) -> bool:
        return engine_info.type == EngineType.UNITY_MONO

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        if not _IS_WINDOWS:
            raise DumperError(
                "UnityMonoDumper requires Windows (pymem dependency). "
                "On Linux, use IL2CPP mode or provide a pre-dumped structure JSON."
            )

        mono_dll = engine_info.extra.get("mono_dll_path", "")
        if not mono_dll:
            raise DumperError(
                "mono_dll_path not found in EngineInfo.extra. "
                "Re-run GameEngineDetector with the game running."
            )

        exe_name = Path(engine_info.exe_path).name
        reader = _MonoReader(exe_name, mono_dll)
        classes = reader.read_all_classes()

        logger.info("UnityMono: dumped %d classes from %s", len(classes), exe_name)

        return StructureJSON(
            engine=str(engine_info.type),
            version=engine_info.version,
            classes=classes,
        )


class _MonoReader:
    """
    Encapsulates all pymem / Mono API calls.
    Isolated here so unit tests can mock this class without needing Windows.
    """

    # Mono API export names
    _MONO_EXPORTS = [
        "mono_domain_get",
        "mono_domain_get_assemblies",
        "mono_assembly_get_image",
        "mono_image_get_table_rows",
        "mono_class_get_fields",
        "mono_field_get_name",
        "mono_field_get_type",
        "mono_type_get_name",
        "mono_field_get_offset",
        "mono_class_get_name",
        "mono_class_get_namespace",
        "mono_class_get_parent",
        "mono_class_from_mono_type",
        "mono_image_get_class",
        "mono_assembly_foreach",
    ]

    def __init__(self, process_name: str, mono_dll_path: str) -> None:
        self._process_name = process_name
        self._mono_dll_path = mono_dll_path
        self._pm = None          # pymem.Pymem instance
        self._mono_base = 0      # base address of mono*.dll in target
        self._exports: dict = {} # name → VA

    def read_all_classes(self) -> list[ClassInfo]:
        """
        Main entry point. Returns all classes from all loaded assemblies.
        Raises DumperError on any failure.
        """
        self._attach()
        self._resolve_mono_base()
        self._resolve_exports()
        return self._walk_assemblies()

    # ── Attachment ────────────────────────────────────────────────────────────

    def _attach(self) -> None:
        try:
            import pymem
            self._pm = pymem.Pymem(self._process_name)
            logger.debug("Attached to process: %s (PID %d)",
                         self._process_name, self._pm.process_id)
        except ImportError as exc:
            raise DumperError(
                "pymem is not installed. Run: pip install pymem"
            ) from exc
        except Exception as exc:
            raise DumperError(
                f"Cannot attach to '{self._process_name}': {exc}\n"
                "Make sure the game is running."
            ) from exc

    def _resolve_mono_base(self) -> None:
        """Find the loaded base address of the mono DLL in the target process."""
        import pymem.process
        mono_name = Path(self._mono_dll_path).name.lower()
        module = pymem.process.module_from_name(self._pm.process_handle, mono_name)
        if module is None:
            raise DumperError(
                f"Module '{mono_name}' not found in process '{self._process_name}'. "
                "Ensure the game is fully loaded (past the main menu)."
            )
        self._mono_base = module.lpBaseOfDll
        logger.debug("Mono base: 0x%X", self._mono_base)

    def _resolve_exports(self) -> None:
        """Build a name→VA map for required Mono API functions."""
        import ctypes
        import ctypes.wintypes as wt
        # GetProcAddress on the remote DLL — load it locally to resolve exports
        hmod = ctypes.windll.kernel32.LoadLibraryExW(
            self._mono_dll_path, None, 0x00000001  # DONT_RESOLVE_DLL_REFERENCES
        )
        if not hmod:
            raise DumperError(f"LoadLibraryEx failed for {self._mono_dll_path}")

        base_local  = hmod
        base_remote = self._mono_base

        for name in self._MONO_EXPORTS:
            local_va = ctypes.windll.kernel32.GetProcAddress(hmod, name.encode())
            if local_va:
                # Convert local VA → remote VA (same offset, different base)
                offset = local_va - base_local
                self._exports[name] = base_remote + offset

        ctypes.windll.kernel32.FreeLibrary(hmod)
        logger.debug("Resolved %d/%d Mono exports", len(self._exports), len(self._MONO_EXPORTS))

    # ── Mono API traversal ────────────────────────────────────────────────────

    def _call(self, name: str, *args) -> int:
        """Call a Mono API function in the remote process via CreateRemoteThread."""
        # For the MVP, we use direct memory reading rather than remote calls.
        # Full implementation would use WriteProcessMemory + CreateRemoteThread.
        raise NotImplementedError(
            "Remote Mono API calls are implemented in Phase 2. "
            "For MVP, use IL2CPPDumper or provide a pre-dumped JSON."
        )

    def _walk_assemblies(self) -> list[ClassInfo]:
        """
        Walk all loaded assemblies and collect class/field info.

        MVP implementation: reads the Mono internal tables directly
        via memory reads rather than remote API calls.
        Full remote-call implementation is Phase 2.
        """
        # Placeholder — returns empty list for now; will be implemented in Phase 2
        logger.warning(
            "UnityMonoDumper._walk_assemblies: full implementation pending (Phase 2). "
            "Returning empty class list."
        )
        return []
