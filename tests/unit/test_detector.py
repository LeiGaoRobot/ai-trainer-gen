"""
Unit tests for GameEngineDetector.

No real game files required — we create temporary directory trees
that mimic the file signatures of each engine type.
"""

import struct
import pytest
from pathlib import Path

from src.detector import GameEngineDetector, EngineType


@pytest.fixture
def detector():
    return GameEngineDetector()


@pytest.fixture
def fake_exe(tmp_path) -> Path:
    """Create a minimal 64-bit PE stub so _detect_bitness doesn't crash."""
    exe = tmp_path / "Game.exe"
    # DOS header with e_lfanew = 0x40
    dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
    # PE header: signature + machine=0x8664 (AMD64)
    pe  = b"PE\x00\x00" + struct.pack("<H", 0x8664)
    exe.write_bytes(dos + b"\x00" * (0x40 - len(dos)) + pe)
    return exe


# ── EngineType detection ───────────────────────────────────────────────────────

class TestEngineTypeDetection:
    def test_detects_unity_il2cpp(self, detector, fake_exe, tmp_path):
        (tmp_path / "GameAssembly.dll").touch()
        (tmp_path / "UnityPlayer.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UNITY_IL2CPP

    def test_detects_unity_mono_via_mono_dir(self, detector, fake_exe, tmp_path):
        (tmp_path / "MonoBleedingEdge").mkdir()
        (tmp_path / "UnityPlayer.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UNITY_MONO

    def test_detects_unity_mono_via_mono_dll(self, detector, fake_exe, tmp_path):
        (tmp_path / "mono-2.0-bdwgc.dll").touch()
        (tmp_path / "UnityPlayer.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UNITY_MONO

    def test_detects_unity_mono_fallback(self, detector, fake_exe, tmp_path):
        """UnityPlayer.dll alone (no Mono/IL2CPP markers) → Unity_Mono conservative."""
        (tmp_path / "UnityPlayer.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UNITY_MONO

    def test_detects_ue4(self, detector, fake_exe, tmp_path):
        (tmp_path / "UE4-MyGame-Win64-Shipping.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UE4

    def test_detects_ue5(self, detector, fake_exe, tmp_path):
        (tmp_path / "UE5-MyGame-Win64-Shipping.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UE5

    def test_il2cpp_takes_priority_over_mono(self, detector, fake_exe, tmp_path):
        """GameAssembly.dll wins even if Mono markers also present."""
        (tmp_path / "GameAssembly.dll").touch()
        (tmp_path / "MonoBleedingEdge").mkdir()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UNITY_IL2CPP

    def test_ue5_takes_priority_over_ue4(self, detector, fake_exe, tmp_path):
        (tmp_path / "UE5-Game-Win64-Shipping.dll").touch()
        (tmp_path / "UE4-Game-Win64-Shipping.dll").touch()

        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UE5

    def test_unknown_engine(self, detector, fake_exe, tmp_path):
        info = detector.detect(str(fake_exe))

        assert info.type == EngineType.UNKNOWN

    def test_raises_file_not_found(self, detector):
        with pytest.raises(FileNotFoundError):
            detector.detect("/nonexistent/path/game.exe")


# ── Bitness detection ─────────────────────────────────────────────────────────

class TestBitnessDetection:
    def _make_exe(self, path: Path, machine: int) -> Path:
        exe = path / "game.exe"
        dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
        pe  = b"PE\x00\x00" + struct.pack("<H", machine)
        exe.write_bytes(dos + b"\x00" * (0x40 - len(dos)) + pe)
        return exe

    def test_64bit_exe(self, detector, tmp_path):
        exe = self._make_exe(tmp_path, 0x8664)
        info = detector.detect(str(exe))
        assert info.bitness == 64

    def test_32bit_exe(self, detector, tmp_path):
        exe = self._make_exe(tmp_path, 0x014C)
        info = detector.detect(str(exe))
        assert info.bitness == 32

    def test_invalid_exe_defaults_to_64(self, detector, tmp_path):
        exe = tmp_path / "weird.exe"
        exe.write_bytes(b"not a PE file at all")
        info = detector.detect(str(exe))
        assert info.bitness == 64


# ── IL2CPP path collection ────────────────────────────────────────────────────

class TestIL2CPPPaths:
    def test_collects_assembly_and_metadata(self, detector, fake_exe, tmp_path):
        (tmp_path / "GameAssembly.dll").touch()
        data_dir = tmp_path / "Game_Data" / "il2cpp_data" / "Metadata"
        data_dir.mkdir(parents=True)
        metadata = data_dir / "global-metadata.dat"
        metadata.write_bytes(b"\x00" * 16)

        info = detector.detect(str(fake_exe))

        assert info.extra.get("assembly_path") == str(tmp_path / "GameAssembly.dll")
        assert info.extra.get("metadata_path") == str(metadata)

    def test_missing_metadata_still_returns_assembly(self, detector, fake_exe, tmp_path):
        (tmp_path / "GameAssembly.dll").touch()

        info = detector.detect(str(fake_exe))

        assert "assembly_path" in info.extra
        assert "metadata_path" not in info.extra


# ── Mono path collection ──────────────────────────────────────────────────────

class TestMonoPaths:
    def test_collects_mono_dll(self, detector, fake_exe, tmp_path):
        embed_dir = tmp_path / "MonoBleedingEdge" / "EmbedRuntime"
        embed_dir.mkdir(parents=True)
        mono_dll = embed_dir / "mono-2.0-bdwgc.dll"
        mono_dll.touch()

        info = detector.detect(str(fake_exe))

        assert info.extra.get("mono_dll_path") == str(mono_dll)


# ── EngineInfo helpers ────────────────────────────────────────────────────────

class TestEngineInfoModel:
    def test_str_representation(self):
        from src.detector.models import EngineInfo, EngineType
        info = EngineInfo(
            type=EngineType.UNITY_IL2CPP,
            version="2022.3.10",
            bitness=64,
            exe_path="/game/game.exe",
            game_dir="/game",
        )
        assert "Unity_IL2CPP" in str(info)
        assert "2022.3.10"    in str(info)
        assert "64"           in str(info)
