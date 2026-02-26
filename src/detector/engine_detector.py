"""
GameEngineDetector — pure static analysis, no process required.

Detection priority (first match wins):
  1. GameAssembly.dll present              → Unity_IL2CPP
  2. Mono/ dir or mono*.dll present        → Unity_Mono
  3. UnityPlayer.dll present (fallback)    → Unity_Mono (conservative)
  4. UE5-*.dll present                     → UE5
  5. UE4-*.dll / UE4Game.exe present       → UE4
  6. None of the above                     → Unknown
"""

import logging
import os
import re
import struct
from pathlib import Path

from src.exceptions import DetectorError
from .models import EngineInfo, EngineType

__all__ = ["GameEngineDetector"]

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_UE4_DLL_RE  = re.compile(r"^UE4-.*\.dll$", re.IGNORECASE)
_UE5_DLL_RE  = re.compile(r"^UE5-.*\.dll$", re.IGNORECASE)
_MONO_DLL_RE = re.compile(r"^mono.*\.dll$",  re.IGNORECASE)

# Known Unity version file relative to game root
_UNITY_VERSION_FILES = [
    "UnityPlayer.dll",
    "GameAssembly.dll",
]


class GameEngineDetector:
    """
    Detect the game engine used by a given executable.

    Usage::

        detector = GameEngineDetector()
        info = detector.detect("C:/Games/MyGame/MyGame.exe")
        print(info)  # Unity_IL2CPP 2022.3.10 (64-bit)
    """

    def detect(self, game_exe_path: str) -> EngineInfo:
        """
        Detect engine info for the given game executable.

        Args:
            game_exe_path: Absolute path to the game's main .exe file.

        Returns:
            EngineInfo with type, version, bitness, and engine-specific extras.

        Raises:
            FileNotFoundError: The exe path does not exist.
            DetectorError: Detection failed due to an unexpected error.
        """
        exe = Path(game_exe_path).resolve()
        if not exe.exists():
            raise FileNotFoundError(f"Game executable not found: {exe}")

        game_dir = exe.parent
        logger.info("Detecting engine for: %s", exe)

        try:
            bitness = self._detect_bitness(exe)
            engine_type, version, extra = self._detect_engine(game_dir)
            info = EngineInfo(
                type=engine_type,
                version=version,
                bitness=bitness,
                exe_path=str(exe),
                game_dir=str(game_dir),
                extra=extra,
            )
            logger.info("Detected: %s", info)
            return info
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise DetectorError(f"Engine detection failed: {exc}") from exc

    # ── Private helpers ───────────────────────────────────────────────────────

    def _detect_engine(
        self, game_dir: Path
    ) -> tuple[EngineType, str, dict]:
        """Return (EngineType, version_str, extra_dict)."""

        files = self._list_files_flat(game_dir)

        # 1. Unity IL2CPP
        if self._has_file(files, "GameAssembly.dll"):
            logger.debug("Found GameAssembly.dll → Unity_IL2CPP")
            version = self._read_unity_version(game_dir)
            extra = self._collect_il2cpp_paths(game_dir)
            return EngineType.UNITY_IL2CPP, version, extra

        # 2. Unity Mono (explicit Mono dir or mono*.dll)
        if self._has_mono(files, game_dir):
            logger.debug("Found Mono indicators → Unity_Mono")
            version = self._read_unity_version(game_dir)
            extra = self._collect_mono_paths(game_dir)
            return EngineType.UNITY_MONO, version, extra

        # 3. Unity Mono fallback (UnityPlayer.dll only)
        if self._has_file(files, "UnityPlayer.dll"):
            logger.debug("Found UnityPlayer.dll (fallback) → Unity_Mono")
            version = self._read_unity_version(game_dir)
            extra = self._collect_mono_paths(game_dir)
            return EngineType.UNITY_MONO, version, extra

        # 4. Unreal Engine 5
        ue5 = [f for f in files if _UE5_DLL_RE.match(f)]
        if ue5:
            logger.debug("Found UE5 DLLs: %s", ue5[:3])
            version = self._read_ue_version(game_dir, major=5)
            return EngineType.UE5, version, {"ue_minor": self._parse_ue_minor(version)}

        # 5. Unreal Engine 4
        ue4 = [f for f in files if _UE4_DLL_RE.match(f)]
        has_ue4_exe = self._has_file(files, "UE4Game.exe")
        if ue4 or has_ue4_exe:
            logger.debug("Found UE4 indicators")
            version = self._read_ue_version(game_dir, major=4)
            return EngineType.UE4, version, {"ue_minor": self._parse_ue_minor(version)}

        # 6. Unknown
        logger.warning("Could not determine engine type for: %s", game_dir)
        return EngineType.UNKNOWN, "unknown", {}

    def _list_files_flat(self, directory: Path) -> list[str]:
        """Return filenames (not paths) from the top two directory levels."""
        result: list[str] = []
        try:
            for entry in directory.iterdir():
                result.append(entry.name)
                # one level deeper (e.g. <GameName>_Data/)
                if entry.is_dir():
                    try:
                        result.extend(e.name for e in entry.iterdir() if e.is_file())
                    except PermissionError:
                        pass
        except PermissionError as exc:
            raise DetectorError(f"Cannot read game directory: {exc}") from exc
        return result

    @staticmethod
    def _has_file(files: list[str], name: str) -> bool:
        return name.lower() in {f.lower() for f in files}

    @staticmethod
    def _has_mono(files: list[str], game_dir: Path) -> bool:
        """True if any mono DLL or Mono/ sub-directory is present."""
        if any(_MONO_DLL_RE.match(f) for f in files):
            return True
        return (game_dir / "MonoBleedingEdge").is_dir() or (game_dir / "Mono").is_dir()

    # ── Unity version reading ─────────────────────────────────────────────────

    def _read_unity_version(self, game_dir: Path) -> str:
        """
        Try to extract the Unity version string.
        Checks <game>_Data/globalgamemanagers (binary) and falls back to
        reading the ProductVersion in UnityPlayer.dll PE resources.
        Returns "unknown" if nothing found.
        """
        # Strategy 1: globalgamemanagers binary signature
        version = self._parse_globalgamemanagers(game_dir)
        if version:
            return version

        # Strategy 2: UnityPlayer.dll file version
        unity_dll = game_dir / "UnityPlayer.dll"
        if unity_dll.exists():
            version = self._read_pe_file_version(unity_dll)
            if version:
                return version

        return "unknown"

    def _parse_globalgamemanagers(self, game_dir: Path) -> str | None:
        """
        Unity stores its version string early in globalgamemanagers.
        Format: b'\\x00' + b'20xx.x.x' (ASCII, null-terminated).
        """
        candidates = [
            game_dir / f"{game_dir.name}_Data" / "globalgamemanagers",
            # some games use a different data folder name
            *[p / "globalgamemanagers" for p in game_dir.iterdir()
              if p.is_dir() and p.name.endswith("_Data")],
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                with open(path, "rb") as f:
                    data = f.read(256)  # version is always in the first 256 bytes
                # Unity version regex: 20xx.x.xfx or 201x / 202x
                match = re.search(rb"(20\d{2}\.\d+\.\d+[a-z]\d+)", data)
                if match:
                    return match.group(1).decode("ascii")
            except OSError:
                continue
        return None

    @staticmethod
    def _read_pe_file_version(dll_path: Path) -> str | None:
        """
        Read the FileVersion from a Windows PE binary's VS_VERSION_INFO.
        Works cross-platform (pure Python, no ctypes / win32api required).
        Only reads the first 64 KB to keep it fast.
        """
        try:
            with open(dll_path, "rb") as f:
                data = f.read(65536)
            # VS_VERSION_INFO magic: \xbd\x04\xef\xfe
            idx = data.find(b"\xbd\x04\xef\xfe")
            if idx == -1:
                return None
            # FileVersion is at offsets +8,+10,+12,+14 from magic (little-endian WORDs)
            # Layout: dwFileVersionMS (DWORD) then dwFileVersionLS (DWORD)
            # each DWORD = (major<<16 | minor)
            ms = struct.unpack_from("<I", data, idx + 8)[0]
            ls = struct.unpack_from("<I", data, idx + 12)[0]
            major  = (ms >> 16) & 0xFFFF
            minor  = ms & 0xFFFF
            build  = (ls >> 16) & 0xFFFF
            # patch  = ls & 0xFFFF  # not used in Unity version string
            return f"{major}.{minor}.{build}"
        except (OSError, struct.error):
            return None

    # ── Unreal version reading ────────────────────────────────────────────────

    def _read_ue_version(self, game_dir: Path, major: int) -> str:
        """
        Try to read UE version from:
          1. Engine/Build/Build.version JSON
          2. UE4-<Name>-Win64-Shipping.dll filename (minor encoded in name)
        Falls back to "<major>.unknown".
        """
        build_version = game_dir / "Engine" / "Build" / "Build.version"
        if build_version.exists():
            try:
                import json
                with open(build_version) as f:
                    data = json.load(f)
                minor = data.get("MinorVersion", 0)
                patch = data.get("PatchVersion", 0)
                return f"{major}.{minor}.{patch}"
            except Exception:
                pass
        return f"{major}.unknown"

    @staticmethod
    def _parse_ue_minor(version: str) -> int:
        """Extract minor version integer from '4.27.2' → 27. Returns 0 on failure."""
        parts = version.split(".")
        try:
            return int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            return 0

    # ── IL2CPP / Mono path helpers ────────────────────────────────────────────

    @staticmethod
    def _collect_il2cpp_paths(game_dir: Path) -> dict:
        """Locate GameAssembly.dll and global-metadata.dat for the IL2CPP dumper."""
        extra: dict = {}
        assembly = game_dir / "GameAssembly.dll"
        if assembly.exists():
            extra["assembly_path"] = str(assembly)

        # metadata is inside <Name>_Data/il2cpp_data/Metadata/
        for data_dir in game_dir.iterdir():
            if not data_dir.is_dir():
                continue
            metadata = data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat"
            if metadata.exists():
                extra["metadata_path"] = str(metadata)
                break

        return extra

    @staticmethod
    def _collect_mono_paths(game_dir: Path) -> dict:
        """Locate mono*.dll for the Mono dumper."""
        extra: dict = {}
        for candidate in ["MonoBleedingEdge/EmbedRuntime", "Mono/EmbedRuntime", "."]:
            search_dir = game_dir / candidate
            if not search_dir.is_dir():
                continue
            for entry in search_dir.iterdir():
                if _MONO_DLL_RE.match(entry.name):
                    extra["mono_dll_path"] = str(entry)
                    return extra
        return extra

    # ── PE bitness ────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_bitness(exe_path: Path) -> int:
        """
        Read the PE Machine field to determine 32 vs 64 bit.
        Returns 64 if file cannot be read (safe default for modern games).
        """
        try:
            with open(exe_path, "rb") as f:
                # DOS header: e_magic='MZ', e_lfanew at offset 0x3C
                f.seek(0x3C)
                pe_offset = struct.unpack("<I", f.read(4))[0]
                f.seek(pe_offset)
                signature = f.read(4)
                if signature != b"PE\x00\x00":
                    return 64
                machine = struct.unpack("<H", f.read(2))[0]
                # 0x014c = IMAGE_FILE_MACHINE_I386
                # 0x8664 = IMAGE_FILE_MACHINE_AMD64
                return 32 if machine == 0x014C else 64
        except (OSError, struct.error):
            return 64
