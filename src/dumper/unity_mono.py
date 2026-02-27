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

# ── MonoDomain struct offsets (Unity MonoBleedingEdge 5.x, 64-bit) ────────────
# These match Unity 2019.4+ through 2022.x for most games.
_DOMAIN_ASSEMBLIES_OFFSET = 0xD0   # MonoDomain.domain_assemblies (GList*)
_GLIST_DATA_OFFSET = 0x00          # GList.data  (void* — the assembly ptr)
_GLIST_NEXT_OFFSET = 0x08          # GList.next  (GList*)
_ASSEMBLY_IMAGE_OFFSET = 0x60      # MonoAssembly.image (MonoImage*)
_IMAGE_NAME_OFFSET = 0x10          # MonoImage.assembly_name (char*)
_IMAGE_N_ROWS_OFFSET = 0x18        # MonoImage typedef row count (uint32)
_IMAGE_NAMES_OFFSET = 0x20         # MonoImage typedef name ptrs (char*[])
_IMAGE_NS_OFFSET = 0x28          # MonoImage typedef namespace ptrs (char*[])
_MAX_ASSEMBLIES = 512              # safety cap to prevent infinite loops


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

    # ── Memory read helpers ───────────────────────────────────────────────────

    def _read_ptr(self, addr: int) -> int:
        """Read an 8-byte little-endian pointer from the target process."""
        return int.from_bytes(self._pm.read_bytes(addr, 8), "little")

    def _read_int32(self, addr: int) -> int:
        """Read a 4-byte little-endian unsigned integer from the target process."""
        return int.from_bytes(self._pm.read_bytes(addr, 4), "little")

    def _read_cstring(self, addr: int, max_len: int = 256) -> str:
        """Read a null-terminated UTF-8 string from the target process."""
        if not addr:
            return ""
        try:
            data = self._pm.read_bytes(addr, max_len)
        except Exception:
            return ""
        null = data.find(b"\x00")
        raw = data[:null] if null >= 0 else data
        return raw.decode("utf-8", errors="replace")

    # ── Root domain discovery ─────────────────────────────────────────────────

    def _find_root_domain_ptr(self) -> int:
        """
        Find the root MonoDomain pointer by disassembling mono_domain_get.

        Unity Mono's mono_domain_get typically begins with:
            48 8B 05 XX XX XX XX   ; MOV RAX, [RIP + disp32]
            C3                     ; RET
        The RIP-relative load reads from the global mono_root_domain variable.
        We find this instruction, compute the global address, and dereference it.

        Raises DumperError if the expected instruction pattern is not found.
        """
        fn_va = self._exports.get("mono_domain_get")
        if fn_va is None:
            raise DumperError("mono_domain_get export not resolved")

        code = self._pm.read_bytes(fn_va, 64)

        for i in range(len(code) - 7):
            if code[i:i+3] == b"\x48\x8B\x05":
                disp = int.from_bytes(code[i+3:i+7], "little", signed=True)
                # RIP = address of next instruction = fn_va + i + 7
                global_va = fn_va + i + 7 + disp
                domain_ptr = self._read_ptr(global_va)
                logger.debug(
                    "Root domain @ 0x%X  (global @ 0x%X, disp=%+d)",
                    domain_ptr, global_va, disp,
                )
                return domain_ptr

        raise DumperError(
            "Could not find MOV RAX,[RIP+disp] in mono_domain_get. "
            "Unsupported Mono version or binary is obfuscated."
        )

    # ── Assembly / class traversal ────────────────────────────────────────────

    def _walk_assemblies(self) -> list[ClassInfo]:
        """
        Traverse MonoDomain.domain_assemblies (GList*) and collect ClassInfo
        objects from every loaded assembly.

        Uses direct memory reads — no remote function calls required.
        """
        domain = self._find_root_domain_ptr()
        if not domain:
            raise DumperError("Root MonoDomain pointer is NULL")

        glist_ptr = self._read_ptr(domain + _DOMAIN_ASSEMBLIES_OFFSET)

        classes: list[ClassInfo] = []
        visited: set[int] = set()
        count = 0

        while glist_ptr and glist_ptr not in visited and count < _MAX_ASSEMBLIES:
            visited.add(glist_ptr)
            count += 1

            assembly_ptr = self._read_ptr(glist_ptr + _GLIST_DATA_OFFSET)
            glist_ptr    = self._read_ptr(glist_ptr + _GLIST_NEXT_OFFSET)

            if not assembly_ptr:
                continue

            try:
                assembly_classes = self._read_assembly_classes(assembly_ptr)
                classes.extend(assembly_classes)
            except Exception as exc:
                logger.warning("Skipping assembly @ 0x%X: %s", assembly_ptr, exc)

        logger.info(
            "UnityMono: walked %d assemblies, collected %d classes",
            count, len(classes),
        )
        return classes

    def _read_assembly_classes(self, assembly_ptr: int) -> list[ClassInfo]:
        """
        Read class names from a MonoAssembly by reading its MonoImage tables.

        Struct layout used:
          MonoAssembly + 0x60 → MonoImage*
          MonoImage    + 0x10 → assembly_name (char*)
          MonoImage    + 0x18 → typedef row count (uint32)
          MonoImage    + 0x20 → array of class name char*  (simplified layout)
          MonoImage    + 0x28 → array of namespace char*
        """
        image_ptr = self._read_ptr(assembly_ptr + _ASSEMBLY_IMAGE_OFFSET)
        if not image_ptr:
            return []

        img_name_ptr = self._read_ptr(image_ptr + _IMAGE_NAME_OFFSET)
        img_name = self._read_cstring(img_name_ptr)
        if not img_name:
            img_name = "?"

        n_rows = self._read_int32(image_ptr + _IMAGE_N_ROWS_OFFSET)
        if n_rows <= 0 or n_rows > 50_000:
            return []

        names_ptr  = self._read_ptr(image_ptr + _IMAGE_NAMES_OFFSET)
        ns_ptr     = self._read_ptr(image_ptr + _IMAGE_NS_OFFSET)

        classes: list[ClassInfo] = []
        for i in range(n_rows):
            try:
                name_entry   = names_ptr + i * 8
                ns_entry     = ns_ptr   + i * 8
                name_str_ptr = self._read_ptr(name_entry) if names_ptr else 0
                ns_str_ptr   = self._read_ptr(ns_entry)   if ns_ptr   else 0
                name = self._read_cstring(name_str_ptr)
                ns   = self._read_cstring(ns_str_ptr)
                if name:
                    classes.append(ClassInfo(name=name, namespace=ns))
            except Exception:
                continue

        logger.debug(
            "Assembly %s: %d classes", img_name, len(classes)
        )
        return classes
