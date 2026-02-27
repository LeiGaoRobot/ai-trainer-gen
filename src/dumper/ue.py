"""
UnrealDumper — structure export via UE4SS or UE SDK dump.

Workflow:
  1. Check if ObjectDump.txt already exists (from a previous UE4SS run)
  2. If not: detect UE4SS installation, send F10 to game window, wait for dump
  3. Parse ObjectDump.txt → StructureJSON
  4. Enrich with version-specific offsets from ue_offsets_table.json
"""

import json
import logging
import platform
import re
import time
from pathlib import Path

from src.detector.models import EngineInfo, EngineType
from src.exceptions import DumperError, DumpTimeoutError
from .base import AbstractDumper
from .models import ClassInfo, FieldInfo, StructureJSON

__all__ = ["UnrealDumper"]

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

_OFFSETS_TABLE = Path(__file__).parent.parent.parent / "config" / "ue_offsets_table.json"

# UE4SS installation marker filenames (any of these in the game dir means installed)
_UE4SS_MARKERS = [
    "UE4SS.dll",
    "UE4SS.log",
    "xinput1_3.dll",
    "version.dll",
    "dwmapi.dll",
]

_DUMP_POLL_INTERVAL = 0.5   # seconds between existence checks
_DUMP_TIMEOUT = 60.0        # total seconds to wait for ObjectDump.txt

_VK_F10     = 0x79   # Virtual key code for F10
_WM_KEYDOWN = 0x100  # WM_KEYDOWN message
_WM_KEYUP   = 0x101  # WM_KEYUP message

# ObjectDump.txt line patterns (UE4SS format)
_CLASS_LINE_RE = re.compile(r"^Class\s+([\w:./]+)")
_PROP_LINE_RE  = re.compile(
    r"^\s+\[\+0x([0-9A-Fa-f]+)\]\s+([\w]+)\s*:\s*([\w<>\[\],\s]+)"
)


class UnrealDumper(AbstractDumper):
    """
    Dump UObject property tree from a running Unreal Engine game.

    Phase 1 (MVP): parse a pre-existing ObjectDump.txt.
    Phase 2: detect UE4SS, send F10 to game window, wait for dump.
    """

    def supports(self, engine_info: EngineInfo) -> bool:
        return engine_info.type in (EngineType.UE4, EngineType.UE5)

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        game_dir = Path(engine_info.game_dir)
        dump_file = game_dir / "ObjectDump.txt"

        if dump_file.exists():
            logger.info("Found pre-existing ObjectDump.txt, parsing...")
        else:
            self._trigger_ue4ss_dump(game_dir, engine_info)
            if not dump_file.exists():
                raise DumperError(
                    "ObjectDump.txt did not appear after UE4SS trigger. "
                    "Try pressing F10 in-game manually and re-run."
                )

        classes = self._parse_object_dump(dump_file)
        offsets = self._load_offsets(engine_info.version)
        logger.info("UE: parsed %d classes, offsets for UE %s",
                    len(classes), engine_info.version)

        return StructureJSON(
            engine=str(engine_info.type),
            version=engine_info.version,
            classes=classes,
            raw_dump_path=str(dump_file),
        )

    # ── UE4SS integration ─────────────────────────────────────────────────────

    def _detect_ue4ss(self, game_dir: Path) -> bool:
        """Return True if any UE4SS marker file is found in *game_dir*."""
        return any((game_dir / marker).exists() for marker in _UE4SS_MARKERS)

    def _trigger_ue4ss_dump(self, game_dir: Path, engine_info: EngineInfo) -> None:
        """
        Attempt to trigger UE4SS's ObjectDump via F10 keypress to the game window.

        Steps:
        1. Verify this is Windows (UE4SS is Windows-only).
        2. Check UE4SS is installed (marker files present in game_dir).
        3. Find the game's main window and send WM_KEYDOWN VK_F10.
        4. Poll for ObjectDump.txt to appear (up to _DUMP_TIMEOUT seconds).

        Raises DumperError with clear instructions if any step fails.
        """
        if not _IS_WINDOWS:
            raise DumperError(
                "Auto UE4SS dump requires Windows. "
                "On other platforms, run the game with UE4SS and press F10 "
                "to generate ObjectDump.txt, then re-run this tool."
            )

        if not self._detect_ue4ss(game_dir):
            raise DumperError(
                "UE4SS is not installed in the game directory.\n"
                "To install UE4SS:\n"
                "  1. Download from https://github.com/UE4SS-RE/RE-UE4SS/releases\n"
                "  2. Extract all files into:\n"
                f"     {game_dir}\n"
                "  3. Launch the game and press F10 to dump objects.\n"
                "  4. Re-run ai-trainer-gen."
            )

        logger.info("UE4SS detected in %s, sending F10 to game window...", game_dir)
        exe_base = Path(engine_info.exe_path).stem  # e.g. "MyGame" from "MyGame.exe"

        triggered = self._send_f10_to_game_window(exe_base)
        if not triggered:
            raise DumperError(
                "Game window not found. Start the game first, then re-run.\n"
                "Once the game is running with UE4SS loaded, F10 will trigger "
                "ObjectDump.txt generation."
            )

        dump_file = game_dir / "ObjectDump.txt"
        logger.info("Waiting for ObjectDump.txt (up to %ds)...", int(_DUMP_TIMEOUT))
        deadline = time.monotonic() + _DUMP_TIMEOUT
        while time.monotonic() < deadline:
            if dump_file.exists():
                elapsed = _DUMP_TIMEOUT - (deadline - time.monotonic())
                logger.info("ObjectDump.txt appeared after %.1fs", elapsed)
                return
            time.sleep(_DUMP_POLL_INTERVAL)

        raise DumpTimeoutError(
            f"ObjectDump.txt did not appear within {_DUMP_TIMEOUT:.0f}s. "
            "Make sure UE4SS is loaded (check UE4SS.log) and try pressing F10 manually."
        )

    def _send_f10_to_game_window(self, exe_base_name: str) -> bool:
        """
        Find the first top-level window whose title contains *exe_base_name*
        and post WM_KEYDOWN + WM_KEYUP for VK_F10.

        Returns True if a matching window was found and key was sent.
        Returns False if no matching window was found.
        """
        if not _IS_WINDOWS:
            return False
        import ctypes
        import ctypes.wintypes as wt

        windows_found: list[tuple[int, str]] = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

        @EnumWindowsProc
        def _callback(hwnd: int, _: int) -> bool:
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                windows_found.append((hwnd, buf.value))
            return True

        ctypes.windll.user32.EnumWindows(_callback, 0)

        target = exe_base_name.lower()
        for hwnd, title in windows_found:
            if target in title.lower():
                ctypes.windll.user32.PostMessageW(hwnd, _WM_KEYDOWN, _VK_F10, 0)
                ctypes.windll.user32.PostMessageW(hwnd, _WM_KEYUP,   _VK_F10, 0)
                logger.debug("Sent F10 to window '%s' (hwnd=0x%X)", title, hwnd)
                return True

        logger.debug(
            "No window found matching '%s' among %d windows",
            exe_base_name, len(windows_found),
        )
        return False

    # ── Parser ────────────────────────────────────────────────────────────────

    def _parse_object_dump(self, dump_file: Path) -> list[ClassInfo]:
        """Parse UE4SS ObjectDump.txt format."""
        classes: list[ClassInfo] = []
        current: ClassInfo | None = None

        for line in dump_file.read_text(encoding="utf-8", errors="replace").splitlines():
            cls_m = _CLASS_LINE_RE.match(line)
            if cls_m:
                full_name = cls_m.group(1)
                parts = full_name.rsplit(".", 1)
                ns    = parts[0] if len(parts) == 2 else ""
                name  = parts[-1]
                current = ClassInfo(name=name, namespace=ns)
                classes.append(current)
                continue

            prop_m = _PROP_LINE_RE.match(line)
            if prop_m and current is not None:
                offset    = f"0x{prop_m.group(1).upper()}"
                prop_name = prop_m.group(2)
                prop_type = prop_m.group(3).strip()
                current.fields.append(FieldInfo(
                    name=prop_name, type=prop_type, offset=offset
                ))

        return classes

    # ── Offsets table ─────────────────────────────────────────────────────────

    @staticmethod
    def _load_offsets(version: str) -> dict:
        """Load GObjects/GNames offsets for the given UE version."""
        if not _OFFSETS_TABLE.exists():
            logger.debug("ue_offsets_table.json not found, skipping offset enrichment")
            return {}
        try:
            with open(_OFFSETS_TABLE) as f:
                table: dict = json.load(f)
            if version in table:
                return table[version]
            major_minor = ".".join(version.split(".")[:2])
            if major_minor in table:
                return table[major_minor]
            logger.debug("No offset entry for UE version %s", version)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load ue_offsets_table.json: %s", exc)
        return {}
