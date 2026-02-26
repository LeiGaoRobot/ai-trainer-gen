"""
IL2CPPDumper — static analysis, no game process required.

Workflow:
  1. Locate GameAssembly.dll + global-metadata.dat from EngineInfo.extra
  2. Shell-invoke IL2CPPDumper.exe → writes DummyDll/*.cs + script.json
  3. Parse DummyDll/*.cs  →  extract [FieldOffset(0xXX)] annotations
  4. Build StructureJSON

The bundled IL2CPPDumper binary lives at:
  tools/il2cpp_dumper/Il2CppDumper.exe
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from src.detector.models import EngineInfo, EngineType
from src.exceptions import DumperError, DumpTimeoutError, UnsupportedVersionError
from .base import AbstractDumper
from .models import ClassInfo, FieldInfo, StructureJSON

__all__ = ["IL2CPPDumper"]

logger = logging.getLogger(__name__)

# Path to bundled IL2CPPDumper relative to project root
_DUMPER_RELATIVE = Path("tools") / "il2cpp_dumper" / "Il2CppDumper.exe"

# Regex patterns for dummy .cs parsing
_CLASS_RE   = re.compile(
    r"(?:public|internal|private|protected)?\s*(?:sealed\s+)?(?:abstract\s+)?"
    r"(?:class|struct|interface)\s+(\w+)"
    r"(?:\s*:\s*([\w,\s<>]+))?"
    r"\s*\{"
)
_FIELD_RE   = re.compile(
    r"\[FieldOffset\(0x([0-9A-Fa-f]+)\)\]\s*"
    r"(?:public|private|protected|internal)?\s*(?:static\s+)?"
    r"([\w\[\]<>.,\s\*]+?)\s+(\w+)\s*;"
)
_STATIC_RE  = re.compile(r"\bstatic\b")
_NS_RE      = re.compile(r"^namespace\s+([\w.]+)")


class IL2CPPDumper(AbstractDumper):
    """
    Dump class structure from a Unity IL2CPP game using the external
    IL2CPPDumper tool. Falls back gracefully if the tool is absent.
    """

    def __init__(self, dumper_exe: str | None = None, timeout: int = 120) -> None:
        """
        Args:
            dumper_exe: Override path to Il2CppDumper.exe.
                        Defaults to the bundled binary.
            timeout:    Seconds before the subprocess is killed.
        """
        self._timeout = timeout
        self._dumper_exe = Path(dumper_exe) if dumper_exe else self._find_dumper()

    def supports(self, engine_info: EngineInfo) -> bool:
        return engine_info.type == EngineType.UNITY_IL2CPP

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        assembly = engine_info.extra.get("assembly_path", "")
        metadata = engine_info.extra.get("metadata_path", "")

        if not assembly or not Path(assembly).exists():
            raise DumperError(
                "GameAssembly.dll not found. "
                "Run GameEngineDetector first and ensure 'assembly_path' is set in extra."
            )
        if not metadata or not Path(metadata).exists():
            raise DumperError(
                "global-metadata.dat not found. "
                "Ensure 'metadata_path' is set in EngineInfo.extra."
            )

        with tempfile.TemporaryDirectory(prefix="ai_trainer_il2cpp_") as tmp:
            tmp_path = Path(tmp)
            raw_dump = tmp_path / "dump"
            raw_dump.mkdir()

            self._run_dumper(assembly, metadata, raw_dump)

            classes = self._parse_dummy_cs(raw_dump)
            logger.info("IL2CPP: parsed %d classes from %s", len(classes), raw_dump)

            structure = StructureJSON(
                engine=str(engine_info.type),
                version=engine_info.version,
                classes=classes,
                raw_dump_path=str(raw_dump),
            )
        return structure

    # ── subprocess ────────────────────────────────────────────────────────────

    def _run_dumper(self, assembly: str, metadata: str, output_dir: Path) -> None:
        if not self._dumper_exe or not self._dumper_exe.exists():
            raise DumperError(
                f"IL2CPPDumper binary not found at: {self._dumper_exe}. "
                "Place Il2CppDumper.exe in tools/il2cpp_dumper/."
            )

        cmd = [
            str(self._dumper_exe),
            assembly,
            metadata,
            str(output_dir),
        ]
        logger.debug("Running: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise DumpTimeoutError(
                f"IL2CPPDumper timed out after {self._timeout}s"
            ) from exc
        except FileNotFoundError as exc:
            raise DumperError(f"Cannot execute IL2CPPDumper: {exc}") from exc

        if result.returncode != 0:
            raise DumperError(
                f"IL2CPPDumper exited with code {result.returncode}.\n"
                f"stderr: {result.stderr[:2000]}"
            )

    # ── .cs parser ────────────────────────────────────────────────────────────

    def _parse_dummy_cs(self, dump_dir: Path) -> list[ClassInfo]:
        """
        Recursively parse all *.cs files in dump_dir.
        Returns a flat list of ClassInfo objects.
        """
        classes: list[ClassInfo] = []
        cs_files = list(dump_dir.rglob("*.cs"))
        logger.debug("Parsing %d .cs files", len(cs_files))

        for cs_file in cs_files:
            try:
                classes.extend(self._parse_single_cs(cs_file))
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", cs_file.name, exc)

        return classes

    def _parse_single_cs(self, cs_file: Path) -> list[ClassInfo]:
        """Parse a single dummy .cs file → list[ClassInfo]."""
        text = cs_file.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        classes: list[ClassInfo] = []
        current_ns = ""
        current_class: ClassInfo | None = None
        brace_depth = 0
        class_brace_start = -1

        for line in lines:
            stripped = line.strip()

            # Track namespace
            ns_match = _NS_RE.match(stripped)
            if ns_match:
                current_ns = ns_match.group(1)
                continue

            # Detect class/struct/interface declaration
            cls_match = _CLASS_RE.search(stripped)
            if cls_match and "{" in stripped:
                class_name   = cls_match.group(1)
                parent_raw   = cls_match.group(2) or ""
                parent_class = parent_raw.split(",")[0].strip() or None
                current_class = ClassInfo(
                    name=class_name,
                    namespace=current_ns,
                    parent_class=parent_class if parent_class else None,
                )
                classes.append(current_class)
                class_brace_start = brace_depth
                brace_depth += stripped.count("{") - stripped.count("}")
                continue

            # Track brace depth
            brace_depth += stripped.count("{") - stripped.count("}")

            # Parse field if inside a class body
            if current_class is not None:
                field_match = _FIELD_RE.search(stripped)
                if field_match:
                    offset_hex  = field_match.group(1)
                    field_type  = field_match.group(2).strip()
                    field_name  = field_match.group(3).strip()
                    is_static   = bool(_STATIC_RE.search(stripped))
                    current_class.fields.append(FieldInfo(
                        name=field_name,
                        type=field_type,
                        offset=f"0x{offset_hex.upper()}",
                        is_static=is_static,
                    ))

            # Close class context when brace depth returns to where class started
            if brace_depth <= class_brace_start and current_class is not None:
                current_class = None
                class_brace_start = -1

        return classes

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _find_dumper() -> Path | None:
        """
        Search for Il2CppDumper.exe in:
          1. tools/il2cpp_dumper/   (relative to CWD — project root)
          2. PATH
        """
        local = Path.cwd() / _DUMPER_RELATIVE
        if local.exists():
            return local
        # also try relative to this file's location
        here = Path(__file__).parent.parent.parent / _DUMPER_RELATIVE
        if here.exists():
            return here
        return None
