"""
UnrealDumper — structure export via UE4SS or UE SDK dump.

Workflow:
  1. Check if UE4SS is installed alongside the game
  2. Trigger UE4SS Lua dump (writes ObjectDump.txt to game dir)
  3. Parse ObjectDump.txt → StructureJSON
  4. Enrich with version-specific offsets from ue_offsets_table.json

Stub: UE4SS integration is Phase 2. This module provides the parser
for pre-existing ObjectDump.txt files and the data model.
"""

import json
import logging
import re
from pathlib import Path

from src.detector.models import EngineInfo, EngineType
from src.exceptions import DumperError
from .base import AbstractDumper
from .models import ClassInfo, FieldInfo, StructureJSON

__all__ = ["UnrealDumper"]

logger = logging.getLogger(__name__)

_OFFSETS_TABLE = Path(__file__).parent.parent.parent / "config" / "ue_offsets_table.json"

# ObjectDump.txt line patterns (UE4SS format)
_CLASS_LINE_RE = re.compile(r"^Class\s+([\w:]+)")
_PROP_LINE_RE  = re.compile(
    r"^\s+\[\+0x([0-9A-Fa-f]+)\]\s+([\w]+)\s*:\s*([\w<>\[\],\s]+)"
)


class UnrealDumper(AbstractDumper):
    """
    Dump UObject property tree from a running Unreal Engine game.

    Phase 1 (MVP): parse a pre-existing ObjectDump.txt.
    Phase 2: inject UE4SS and trigger dump automatically.
    """

    def supports(self, engine_info: EngineInfo) -> bool:
        return engine_info.type in (EngineType.UE4, EngineType.UE5)

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        game_dir = Path(engine_info.game_dir)

        # Check for pre-existing dump (from manual UE4SS run)
        dump_file = game_dir / "ObjectDump.txt"
        if dump_file.exists():
            logger.info("Found pre-existing ObjectDump.txt, parsing...")
            classes = self._parse_object_dump(dump_file)
        else:
            # Phase 2: auto-inject UE4SS
            raise DumperError(
                "ObjectDump.txt not found in game directory. "
                "Run UE4SS manually first: press F10 in-game to generate the dump, "
                "then re-run this tool. "
                "(Automatic UE4SS injection is planned for Phase 2.)"
            )

        offsets = self._load_offsets(engine_info.version)
        logger.info("UE: parsed %d classes, offsets for UE %s",
                    len(classes), engine_info.version)

        return StructureJSON(
            engine=str(engine_info.type),
            version=engine_info.version,
            classes=classes,
            raw_dump_path=str(dump_file),
        )

    # ── Parser ────────────────────────────────────────────────────────────────

    def _parse_object_dump(self, dump_file: Path) -> list[ClassInfo]:
        """Parse UE4SS ObjectDump.txt format."""
        classes: list[ClassInfo] = []
        current: ClassInfo | None = None

        for line in dump_file.read_text(encoding="utf-8", errors="replace").splitlines():
            cls_m = _CLASS_LINE_RE.match(line)
            if cls_m:
                full_name = cls_m.group(1)
                # UE uses Package.ClassName notation
                parts = full_name.rsplit(".", 1)
                ns    = parts[0] if len(parts) == 2 else ""
                name  = parts[-1]
                current = ClassInfo(name=name, namespace=ns)
                classes.append(current)
                continue

            prop_m = _PROP_LINE_RE.match(line)
            if prop_m and current is not None:
                offset     = f"0x{prop_m.group(1).upper()}"
                prop_name  = prop_m.group(2)
                prop_type  = prop_m.group(3).strip()
                current.fields.append(FieldInfo(
                    name=prop_name, type=prop_type, offset=offset
                ))

        return classes

    # ── Offsets table ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_offsets(version: str) -> dict:
        """
        Load GObjects/GNames offsets for the given UE version.
        Returns empty dict if the table or version entry is missing.
        """
        if not _OFFSETS_TABLE.exists():
            logger.debug("ue_offsets_table.json not found, skipping offset enrichment")
            return {}
        try:
            with open(_OFFSETS_TABLE) as f:
                table: dict = json.load(f)
            # Try exact match, then major.minor
            if version in table:
                return table[version]
            major_minor = ".".join(version.split(".")[:2])
            if major_minor in table:
                return table[major_minor]
            logger.debug("No offset entry for UE version %s", version)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load ue_offsets_table.json: %s", exc)
        return {}
