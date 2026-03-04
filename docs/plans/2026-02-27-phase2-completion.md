# Phase 2 Completion Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the three Phase 2 stubs: CLI generate pipeline, UnityMonoDumper._walk_assemblies(), and UnrealDumper UE4SS auto-injection.

**Architecture:** All changes are additive — each task fills in a pre-existing placeholder without touching unrelated code. The CLI pipeline (Task 1) is cross-platform; the Mono and UE4SS tasks (Tasks 2–3) are Windows-only and guarded by `platform.system()` checks already present in the code. Everything is tested via mocks — no real game or Windows machine required.

**Tech Stack:** Python 3.12, pytest + unittest.mock, pymem (mocked), ctypes.windll (mocked), threading (for UE4SS poll test).

---

## Task 1: CLI `generate` Pipeline

**Files:**
- Modify: `src/cli/main.py`
- Modify: `tests/unit/test_cli.py`

### Step 1: Add failing tests for cmd_generate

Add `TestGenerateCommand` class to `tests/unit/test_cli.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# 4. generate command (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateCommand:
    """Full pipeline with stub LLM + mocked dumper — no real game needed."""

    @pytest.fixture
    def fake_il2cpp_exe(self, tmp_path):
        """64-bit PE with GameAssembly.dll → UNITY_IL2CPP detection."""
        import struct
        exe = tmp_path / "Game.exe"
        dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
        pe  = b"PE\x00\x00" + struct.pack("<H", 0x8664)
        exe.write_bytes(dos + b"\x00" * (0x40 - len(dos)) + pe)
        (tmp_path / "GameAssembly.dll").touch()
        return exe

    @pytest.fixture
    def fake_structure(self):
        from src.dumper.models import StructureJSON, ClassInfo, FieldInfo
        return StructureJSON(
            engine="Unity_IL2CPP",
            version="2022.3",
            classes=[
                ClassInfo(
                    name="PlayerController", namespace="Game",
                    fields=[FieldInfo(name="health", type="float", offset="0x58")],
                ),
            ],
        )

    def test_generate_creates_lua_file(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """Happy path: generates .lua file in output dir."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            out_path = cmd_generate(
                exe_path=str(fake_il2cpp_exe),
                feature="infinite_health",
                output_dir=str(tmp_path / "out"),
                no_cache=False,
                store=store,
                backend="stub",
            )

        assert out_path.exists()
        code = out_path.read_text()
        assert len(code) > 10  # stub produces non-empty script

    def test_generate_saves_to_cache(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """After generation, record should be retrievable from store."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out"), False, store, "stub")

        records = store.search("Game")
        assert len(records) == 1
        assert records[0].feature == "infinite_health"

    def test_generate_cache_hit_skips_dumper(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """Second call with same args hits cache — dumper.dump() not called again."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out1"), False, store, "stub")
            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out2"), False, store, "stub")

        assert mock_dumper.dump.call_count == 1  # only called once

    def test_generate_no_cache_forces_redump(self, store, fake_il2cpp_exe, fake_structure, tmp_path):
        """--no-cache always calls dumper even on cache hit."""
        from unittest.mock import patch, MagicMock
        from src.cli.main import cmd_generate

        with patch("src.cli.main.get_dumper") as mock_gd:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper

            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out1"), False, store, "stub")
            cmd_generate(str(fake_il2cpp_exe), "infinite_health",
                         str(tmp_path / "out2"), True, store, "stub")  # no_cache=True

        assert mock_dumper.dump.call_count == 2

    def test_main_generate_returns_0(self, tmp_path, fake_structure):
        """main() returns exit code 0 on successful generation."""
        import struct
        from unittest.mock import patch, MagicMock
        from src.cli.main import main

        exe = tmp_path / "Game.exe"
        dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", 0x40)
        pe  = b"PE\x00\x00" + struct.pack("<H", 0x8664)
        exe.write_bytes(dos + b"\x00" * (0x40 - len(dos)) + pe)
        (tmp_path / "GameAssembly.dll").touch()

        with patch("src.cli.main.get_dumper") as mock_gd, \
             patch("src.cli.main.ScriptStore") as mock_store_cls:
            mock_dumper = MagicMock()
            mock_dumper.dump.return_value = fake_structure
            mock_gd.return_value = mock_dumper
            mock_store = MagicMock()
            mock_store.get.return_value = None
            mock_store.save.return_value = 1
            mock_store_cls.return_value = mock_store

            rc = main([
                "--db", str(tmp_path / "test.db"),
                "generate",
                "--exe", str(exe),
                "--feature", "infinite_health",
                "--output", str(tmp_path / "out"),
                "--backend", "stub",
            ])

        assert rc == 0

    def test_parse_feature_type_known(self):
        from src.cli.main import _parse_feature_type
        from src.analyzer.models import FeatureType
        assert _parse_feature_type("infinite_health") == FeatureType.INFINITE_HEALTH

    def test_parse_feature_type_unknown_returns_custom(self):
        from src.cli.main import _parse_feature_type
        from src.analyzer.models import FeatureType
        assert _parse_feature_type("fly_mode") == FeatureType.CUSTOM
```

### Step 2: Run tests — verify they FAIL

```bash
cd /Users/paulgao/AI/Workspace/CC/brainstorm/ai-trainer-gen
python -m pytest tests/unit/test_cli.py::TestGenerateCommand -v
```

Expected: `ERRORS` — `cmd_generate`, `_parse_feature_type`, `get_dumper` not found in `src.cli.main`.

### Step 3: Implement `cmd_generate` in `src/cli/main.py`

Replace the file. Key changes:
1. Add top-level imports: `import hashlib`, `import json as _json`
2. Add `from src.dumper.base import get_dumper` at module level (lazy import in function is fine too)
3. Add `_parse_feature_type()` helper
4. Add `_write_output()` helper
5. Add `cmd_generate()` function
6. Add `--backend`, `--model`, `--api-key` flags to generate subcommand
7. Update `main()` to call `cmd_generate()`
8. Update `__all__`

**Full replacement for `src/cli/main.py`:**

```python
"""
CLI entry point for ai-trainer-gen.

Usage
─────
  # Generate a trainer script (Stub LLM mode — no API key needed)
  python -m ai_trainer_gen generate \\
      --exe "C:/Games/MyGame/MyGame.exe" \\
      --feature "infinite_health" \\
      --output ./out/

  # List cached scripts
  python -m ai_trainer_gen list
  python -m ai_trainer_gen list --game "Hollow Knight"

  # Export a .ct table by record id
  python -m ai_trainer_gen export --id 42 --format ct

Subcommands are implemented as standalone functions (cmd_generate, cmd_list,
cmd_export) so they can be unit-tested without invoking argparse.
"""

import argparse
import hashlib
import json as _json
import logging
import sys
from pathlib import Path
from typing import Optional

from src.store.db import ScriptStore
from src.store.models import ScriptRecord

__all__ = ["build_parser", "cmd_generate", "cmd_list", "cmd_export", "main"]

logger = logging.getLogger(__name__)


# ── Argument parser ────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """
    Build and return the top-level argument parser.

    Subcommands: generate | list | export
    """
    parser = argparse.ArgumentParser(
        prog="ai-trainer-gen",
        description="AI-powered Cheat Engine trainer generator",
    )
    parser.add_argument(
        "--db",
        default="~/.ai-trainer/scripts.db",
        metavar="PATH",
        help="SQLite database path (default: ~/.ai-trainer/scripts.db)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable verbose debug logging",
    )

    sub = parser.add_subparsers(dest="subcommand")

    # ── generate ──────────────────────────────────────────────────────────
    gen = sub.add_parser("generate", help="Generate a CE Lua trainer script")
    gen.add_argument(
        "--exe",
        required=True,
        metavar="PATH",
        help="Path to the game executable",
    )
    gen.add_argument(
        "--feature",
        required=True,
        metavar="FEATURE",
        help="Trainer feature to generate (e.g. infinite_health)",
    )
    gen.add_argument(
        "--output",
        default=None,
        metavar="DIR",
        help="Output directory for generated script (default: ./output/)",
    )
    gen.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Bypass ScriptStore cache and force regeneration",
    )
    gen.add_argument(
        "--backend",
        choices=["stub", "anthropic", "openai"],
        default="stub",
        help="LLM backend to use (default: stub; use anthropic for production)",
    )
    gen.add_argument(
        "--model",
        default="",
        metavar="MODEL",
        help="LLM model override (default: backend-specific default)",
    )
    gen.add_argument(
        "--api-key",
        default="",
        dest="api_key",
        metavar="KEY",
        help="API key (or use ANTHROPIC_API_KEY / OPENAI_API_KEY env var)",
    )

    # ── list ──────────────────────────────────────────────────────────────
    lst = sub.add_parser("list", help="List cached trainer scripts")
    lst.add_argument(
        "--game",
        default=None,
        metavar="NAME",
        help="Filter by game name substring",
    )

    # ── export ────────────────────────────────────────────────────────────
    exp = sub.add_parser("export", help="Export a cached script as .ct table")
    exp.add_argument(
        "--id",
        required=True,
        type=int,
        metavar="ID",
        help="Script record id to export",
    )
    exp.add_argument(
        "--format",
        choices=["ct", "lua"],
        default="ct",
        help="Export format: ct (Cheat Table XML) or lua (raw Lua script)",
    )
    exp.add_argument(
        "--output",
        default=None,
        metavar="DIR",
        help="Output directory (default: current directory)",
    )

    return parser


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_feature_type(feature: str):
    """Map feature name string to FeatureType enum; returns CUSTOM if unknown."""
    from src.analyzer.models import FeatureType
    try:
        return FeatureType(feature.lower())
    except ValueError:
        return FeatureType.CUSTOM


def _write_output(lua_code: str, game_name: str, feature: str,
                  output_dir: Optional[str]) -> Path:
    """Write Lua code to <output_dir>/<game>_<feature>.lua, return the path."""
    out_dir = Path(output_dir) if output_dir else Path.cwd() / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in f"{game_name}_{feature}")
    out_path = out_dir / f"{safe}.lua"
    out_path.write_text(lua_code, encoding="utf-8")
    return out_path


# ── Command implementations ───────────────────────────────────────────────────


def cmd_generate(
    exe_path: str,
    feature: str,
    output_dir: Optional[str],
    no_cache: bool,
    store: ScriptStore,
    backend: str = "stub",
    model: str = "",
    api_key: str = "",
) -> Path:
    """
    Full generation pipeline: detect → dump → resolve → analyze → cache → write.

    Args:
        exe_path:   Absolute path to the game executable.
        feature:    Feature name (e.g. "infinite_health").
        output_dir: Directory to write the Lua file (default: ./output/).
        no_cache:   If True, skip cache lookup and always re-generate.
        store:      ScriptStore instance for caching.
        backend:    LLM backend ("stub" | "anthropic" | "openai").
        model:      Model override; empty = backend default.
        api_key:    API key; empty = read from env.

    Returns:
        Path to the written .lua file.

    Raises:
        Any exception from detector / dumper / analyzer propagates to the caller.
    """
    from src.detector import GameEngineDetector
    from src.dumper.base import get_dumper
    from src.resolver.factory import get_resolver
    from src.resolver.models import EngineContext
    from src.analyzer.llm_analyzer import LLMAnalyzer, LLMConfig
    from src.analyzer.models import TrainerFeature

    # 1. Detect engine
    logger.info("Detecting engine for: %s", exe_path)
    engine_info = GameEngineDetector().detect(exe_path)
    logger.info("Detected: %s", engine_info)

    # 2. Stable cache key derived from the game directory path
    game_name = Path(engine_info.game_dir).name
    game_hash = hashlib.sha256(engine_info.game_dir.encode()).hexdigest()[:16]

    # 3. Cache lookup
    if not no_cache:
        cached = store.get(game_hash, feature)
        if cached:
            logger.info("Cache hit: %s / %s", game_name, feature)
            print(f"[cache hit] Returning cached script for '{feature}'")
            return _write_output(cached.lua_script, game_name, feature, output_dir)

    # 4. Dump game structure
    dumper = get_dumper(engine_info)
    logger.info("Dumping structure via %s", type(dumper).__name__)
    structure = dumper.dump(engine_info)

    # 5. Resolve field accesses (engine-specific CE Lua expressions)
    context = EngineContext.from_engine_info(engine_info)
    resolver = get_resolver(engine_info.type)
    resolutions = resolver.resolve(structure, context)
    context.resolutions = resolutions
    logger.debug("Resolved %d field accesses", len(resolutions))

    # 6. Generate script via LLM
    trainer_feature = TrainerFeature(
        name=feature,
        feature_type=_parse_feature_type(feature),
    )
    config = LLMConfig(backend=backend, model=model, api_key=api_key)
    script = LLMAnalyzer(config).analyze(structure, trainer_feature, context)

    # 7. Persist to cache
    aob_json = _json.dumps([
        {"pattern": s.pattern, "offset": s.offset, "module": s.module}
        for s in script.aob_sigs
    ]) if script.aob_sigs else None
    record = ScriptRecord(
        game_hash=game_hash,
        game_name=game_name,
        engine_type=str(engine_info.type),
        feature=feature,
        lua_script=script.lua_code,
        aob_sigs=aob_json,
    )
    store.save(record)

    # 8. Write output file
    out_path = _write_output(script.lua_code, game_name, feature, output_dir)
    logger.info("Script written to %s", out_path)
    return out_path


def cmd_list(store: ScriptStore, game: Optional[str]) -> None:
    """Print cached script records to stdout."""
    records = store.search(game_name=game or "")
    if not records:
        print("0 cached scripts found.")
        return
    for rec in records:
        tag = f"[{rec.id:>4}]"
        status = f"ok={rec.success_count} fail={rec.fail_count}"
        print(f"{tag}  {rec.game_name:<30} {rec.feature:<25} {status}")


def cmd_export(
    store: ScriptStore,
    record_id: int,
    fmt: str,
    output_dir: Optional[str],
) -> Path:
    """Export a cached script record to a file."""
    all_records = store.search(game_name="")
    record = next((r for r in all_records if r.id == record_id), None)

    if record is None:
        raise ValueError(f"No script record with id={record_id}")

    out_dir = Path(output_dir) if output_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "lua":
        filename = f"{record.game_name}_{record.feature}_{record_id}.lua"
        out_path = out_dir / filename
        out_path.write_text(record.lua_script, encoding="utf-8")
    else:
        from src.ce_wrapper.ct_builder import CTBuilder
        from src.analyzer.models import TrainerFeature, GeneratedScript, FeatureType
        feature = TrainerFeature(name=record.feature, feature_type=FeatureType.CUSTOM)
        script = GeneratedScript(lua_code=record.lua_script, feature=feature)
        xml_str = CTBuilder().build(script)
        filename = f"{record.game_name}_{record.feature}_{record_id}.ct"
        out_path = out_dir / filename
        out_path.write_text(xml_str, encoding="utf-8")

    logger.info("Exported record %d to %s", record_id, out_path)
    print(f"Exported → {out_path}")
    return out_path


# ── Entry point ───────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Main CLI entry point. Returns exit code."""
    parser = build_parser()
    ns = parser.parse_args(argv)

    level = logging.DEBUG if ns.debug else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s")

    if ns.subcommand is None:
        parser.print_help()
        return 0

    store = ScriptStore(db_path=ns.db)

    if ns.subcommand == "list":
        cmd_list(store=store, game=ns.game)
        return 0

    if ns.subcommand == "export":
        try:
            cmd_export(
                store=store,
                record_id=ns.id,
                fmt=ns.format,
                output_dir=getattr(ns, "output", None),
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if ns.subcommand == "generate":
        try:
            cmd_generate(
                exe_path=ns.exe,
                feature=ns.feature,
                output_dir=getattr(ns, "output", None),
                no_cache=ns.no_cache,
                store=store,
                backend=getattr(ns, "backend", "stub"),
                model=getattr(ns, "model", ""),
                api_key=getattr(ns, "api_key", ""),
            )
        except Exception as exc:
            logger.debug("generate failed", exc_info=True)
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 4: Run tests — verify they PASS

```bash
python -m pytest tests/unit/test_cli.py -v
```

Expected: all tests PASS (both old 8 and new ~9).

### Step 5: Run full test suite

```bash
python -m pytest -q
```

Expected: all 213+ tests pass.

### Step 6: Commit

```bash
git add src/cli/main.py tests/unit/test_cli.py
git commit -m "feat(cli): wire up generate pipeline — detector→dump→resolve→analyze→cache→write"
```

---

## Task 2: UnityMonoDumper._walk_assemblies()

**Files:**
- Modify: `src/dumper/unity_mono.py`
- Modify: `tests/unit/test_dumper_models.py`

### Step 1: Add failing tests

Append `TestUnityMonoDumperWalkAssemblies` to `tests/unit/test_dumper_models.py`:

```python
class TestUnityMonoDumperWalkAssemblies:
    """
    Test _MonoReader internals via mocked pymem.
    No Windows or running game required.
    """

    @pytest.fixture
    def reader(self):
        """_MonoReader with a pre-populated _exports dict (no attach needed)."""
        from src.dumper.unity_mono import _MonoReader
        r = _MonoReader("Game.exe", "C:/mono-2.0-bdwgc.dll")
        # Simulate resolved exports
        r._exports = {
            "mono_domain_get": 0x7FF000001000,
        }
        return r

    def test_read_ptr_reads_8_bytes_le(self, reader):
        """_read_ptr reads 8 bytes as a little-endian unsigned int."""
        from unittest.mock import MagicMock
        reader._pm = MagicMock()
        reader._pm.read_bytes.return_value = b"\x01\x00\x00\x00\x00\x00\x00\x00"
        assert reader._read_ptr(0x1000) == 1

    def test_read_int32_reads_4_bytes_le(self, reader):
        """_read_int32 reads 4 bytes as a little-endian unsigned int."""
        from unittest.mock import MagicMock
        reader._pm = MagicMock()
        reader._pm.read_bytes.return_value = b"\x0A\x00\x00\x00"
        assert reader._read_int32(0x1000) == 10

    def test_read_cstring_stops_at_null(self, reader):
        """_read_cstring returns the string up to the first null byte."""
        from unittest.mock import MagicMock
        reader._pm = MagicMock()
        reader._pm.read_bytes.return_value = b"PlayerController\x00garbage"
        result = reader._read_cstring(0x2000)
        assert result == "PlayerController"

    def test_find_root_domain_parses_mov_rax(self, reader):
        """_find_root_domain_ptr finds MOV RAX, [RIP+disp] and follows it."""
        from unittest.mock import MagicMock, patch
        reader._pm = MagicMock()

        # Construct minimal function body: MOV RAX, [RIP+5]; RET
        # Instruction: 48 8B 05 05 00 00 00  (7 bytes, disp=5)
        # RIP at end of instruction = fn_va + 7
        # global_va = (fn_va + 7) + 5 = fn_va + 12
        fn_va = reader._exports["mono_domain_get"]
        code = b"\x48\x8B\x05\x05\x00\x00\x00" + b"\xC3" + b"\x00" * 24
        domain_ptr = 0xDEADBEEF00000001

        def fake_read_bytes(addr, size):
            if addr == fn_va:
                return code
            if addr == fn_va + 12:  # global_va
                return domain_ptr.to_bytes(8, "little")
            return b"\x00" * size

        reader._pm.read_bytes.side_effect = fake_read_bytes
        result = reader._find_root_domain_ptr()
        assert result == domain_ptr

    def test_find_root_domain_raises_if_no_mov_rax(self, reader):
        """_find_root_domain_ptr raises DumperError if pattern not found."""
        from unittest.mock import MagicMock
        from src.exceptions import DumperError
        reader._pm = MagicMock()
        fn_va = reader._exports["mono_domain_get"]
        reader._pm.read_bytes.return_value = b"\x90" * 32  # all NOPs
        with pytest.raises(DumperError, match="mono_domain_get"):
            reader._find_root_domain_ptr()

    def test_walk_assemblies_returns_classes_from_glist(self, reader):
        """_walk_assemblies traverses GList and returns ClassInfo objects."""
        from unittest.mock import MagicMock, patch

        reader._pm = MagicMock()

        # Layout (64-bit addresses):
        DOMAIN   = 0x10000
        GLIST1   = 0x20000
        ASSEMBLY = 0x30000
        IMAGE    = 0x40000

        # Assembly image name string
        IMG_NAME_STR = 0x50000
        # Class name string
        CLASS_NAME_STR = 0x60000
        # Namespace string
        NS_STR = 0x70000

        import struct

        def mk_ptr(v: int) -> bytes:
            return struct.pack("<Q", v)

        memory = {
            # domain->domain_assemblies at DOMAIN + 0xD0
            DOMAIN + 0xD0: mk_ptr(GLIST1),
            # GList node 1: data=ASSEMBLY, next=0 (end of list)
            GLIST1 + 0x00: mk_ptr(ASSEMBLY),
            GLIST1 + 0x08: mk_ptr(0),         # next = NULL
            # MonoAssembly->image at ASSEMBLY + 0x60
            ASSEMBLY + 0x60: mk_ptr(IMAGE),
            # MonoImage->assembly_name (char*) at IMAGE + 0x10
            IMAGE + 0x10: mk_ptr(IMG_NAME_STR),
            # MonoImage->n_typedef_rows at IMAGE + 0x18
            IMAGE + 0x18: struct.pack("<I", 1),  # 1 class
            # MonoImage->typedef_names at IMAGE + 0x20 (ptr to array of char*)
            IMAGE + 0x20: mk_ptr(CLASS_NAME_STR),
            IMAGE + 0x28: mk_ptr(NS_STR),
            # Strings
            IMG_NAME_STR:   b"Assembly-CSharp\x00",
            CLASS_NAME_STR: b"PlayerController\x00",
            NS_STR:         b"Game.Player\x00",
        }

        def fake_read(addr, size):
            for base, data in memory.items():
                if addr == base:
                    return data[:size]
            return b"\x00" * size

        reader._pm.read_bytes.side_effect = fake_read

        # Patch _find_root_domain_ptr to return our fake domain
        with patch.object(reader, "_find_root_domain_ptr", return_value=DOMAIN):
            classes = reader._walk_assemblies()

        assert len(classes) >= 1
        names = [c.name for c in classes]
        assert "PlayerController" in names

    def test_walk_assemblies_handles_null_assembly_gracefully(self, reader):
        """NULL assembly pointer in GList is skipped without crashing."""
        from unittest.mock import MagicMock, patch
        import struct

        reader._pm = MagicMock()
        DOMAIN = 0x10000
        GLIST1 = 0x20000

        def mk_ptr(v): return struct.pack("<Q", v)
        memory = {
            DOMAIN + 0xD0: mk_ptr(GLIST1),
            GLIST1 + 0x00: mk_ptr(0),   # NULL assembly
            GLIST1 + 0x08: mk_ptr(0),   # end of list
        }
        reader._pm.read_bytes.side_effect = lambda a, s: memory.get(a, b"\x00"*s)[:s]

        with patch.object(reader, "_find_root_domain_ptr", return_value=DOMAIN):
            classes = reader._walk_assemblies()

        assert classes == []

    def test_walk_assemblies_caps_at_max_assemblies(self, reader):
        """GList longer than _MAX_ASSEMBLIES is capped (infinite loop prevention)."""
        from unittest.mock import MagicMock, patch
        import struct

        reader._pm = MagicMock()
        DOMAIN = 0x10000

        # Build a circular-ish GList (each node points to next, then wraps)
        # by having many nodes that all have NULL assemblies
        nodes = list(range(0x20000, 0x20000 + 600 * 0x10, 0x10))  # 600 nodes

        def mk_ptr(v): return struct.pack("<Q", v)

        memory: dict = {DOMAIN + 0xD0: mk_ptr(nodes[0])}
        for i, node in enumerate(nodes):
            memory[node + 0x00] = mk_ptr(0)         # NULL assembly (skip)
            memory[node + 0x08] = mk_ptr(nodes[i+1] if i < len(nodes)-1 else 0)

        reader._pm.read_bytes.side_effect = lambda a, s: memory.get(a, b"\x00"*s)[:s]

        with patch.object(reader, "_find_root_domain_ptr", return_value=DOMAIN):
            classes = reader._walk_assemblies()

        # Should not hang; returns empty list (all NULL assemblies)
        assert isinstance(classes, list)
```

### Step 2: Run tests — verify they FAIL

```bash
python -m pytest tests/unit/test_dumper_models.py::TestUnityMonoDumperWalkAssemblies -v
```

Expected: `AttributeError: '_MonoReader' object has no attribute '_read_ptr'`

### Step 3: Implement in `src/dumper/unity_mono.py`

Replace `unity_mono.py` content. Key additions in `_MonoReader`:
- Constants `_DOMAIN_ASSEMBLIES_OFFSET`, `_GLIST_DATA_OFFSET`, `_GLIST_NEXT_OFFSET`, `_ASSEMBLY_IMAGE_OFFSET`, `_IMAGE_NAME_OFFSET`, `_IMAGE_N_ROWS_OFFSET`, `_IMAGE_NAMES_OFFSET`, `_MAX_ASSEMBLIES`
- Methods `_read_ptr`, `_read_int32`, `_read_cstring`
- Method `_find_root_domain_ptr`
- Full `_walk_assemblies` implementation
- Full `_read_assembly_classes` implementation

```python
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
# Override in a subclass if your game uses a different Mono version.
_DOMAIN_ASSEMBLIES_OFFSET = 0xD0   # MonoDomain.domain_assemblies (GList*)
_GLIST_DATA_OFFSET = 0x00          # GList.data  (void* — the assembly ptr)
_GLIST_NEXT_OFFSET = 0x08          # GList.next  (GList*)
_ASSEMBLY_IMAGE_OFFSET = 0x60      # MonoAssembly.image (MonoImage*)
_IMAGE_NAME_OFFSET = 0x10          # MonoImage.assembly_name (char*)
_IMAGE_N_ROWS_OFFSET = 0x18        # MonoImage typedef row count (uint32)
_IMAGE_NAMES_OFFSET = 0x20         # MonoImage typedef name ptrs (char*[])
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
                offset = local_va - base_local
                self._exports[name] = base_remote + offset

        ctypes.windll.kernel32.FreeLibrary(hmod)
        logger.debug("Resolved %d/%d Mono exports", len(self._exports), len(self._MONO_EXPORTS))

    # ── Memory read helpers ───────────────────────────────────────────────────

    def _read_ptr(self, addr: int) -> int:
        """Read an 8-byte little-endian pointer from the target process."""
        return int.from_bytes(self._pm.read_bytes(addr, 8), "little")

    def _read_int32(self, addr: int) -> int:
        """Read a 4-byte little-endian unsigned int from the target process."""
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

        code = self._pm.read_bytes(fn_va, 32)

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
                logger.debug("Skipping assembly @ 0x%X: %s", assembly_ptr, exc)

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
        ns_ptr     = self._read_ptr(image_ptr + _IMAGE_NAMES_OFFSET + 8)

        classes: list[ClassInfo] = []
        for i in range(n_rows):
            try:
                name_str_ptr = self._read_ptr(names_ptr + i * 8) if names_ptr else 0
                ns_str_ptr   = self._read_ptr(ns_ptr   + i * 8) if ns_ptr   else 0
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
```

### Step 4: Run tests — verify they PASS

```bash
python -m pytest tests/unit/test_dumper_models.py -v
```

Expected: all tests pass including new `TestUnityMonoDumperWalkAssemblies`.

### Step 5: Run full test suite

```bash
python -m pytest -q
```

Expected: all tests pass.

### Step 6: Commit

```bash
git add src/dumper/unity_mono.py tests/unit/test_dumper_models.py
git commit -m "feat(dumper): implement UnityMonoDumper._walk_assemblies via direct Mono struct traversal"
```

---

## Task 3: UnrealDumper UE4SS Auto-Injection

**Files:**
- Modify: `src/dumper/ue.py`
- Modify: `tests/unit/test_dumper_models.py`

### Step 1: Add failing tests

Append `TestUnrealDumperUE4SS` to `tests/unit/test_dumper_models.py`:

```python
class TestUnrealDumperUE4SS:
    """Test UE4SS detection and auto-injection trigger logic."""

    @pytest.fixture
    def ue4_info(self, tmp_path):
        from src.detector.models import EngineInfo, EngineType
        return EngineInfo(
            type=EngineType.UE4, version="4.27", bitness=64,
            exe_path=str(tmp_path / "Game.exe"),
            game_dir=str(tmp_path),
        )

    def test_raises_with_no_dump_and_no_ue4ss(self, ue4_info, tmp_path):
        """No ObjectDump.txt + no UE4SS markers → DumperError with install instructions."""
        from src.dumper.ue import UnrealDumper
        from src.exceptions import DumperError
        dumper = UnrealDumper()
        with pytest.raises(DumperError, match="UE4SS is not installed"):
            dumper.dump(ue4_info)

    def test_detect_ue4ss_true_when_marker_present(self, tmp_path):
        """_detect_ue4ss returns True when any marker file exists."""
        from src.dumper.ue import UnrealDumper
        (tmp_path / "UE4SS.dll").touch()
        assert UnrealDumper()._detect_ue4ss(tmp_path) is True

    def test_detect_ue4ss_false_when_no_markers(self, tmp_path):
        """_detect_ue4ss returns False when no marker files exist."""
        from src.dumper.ue import UnrealDumper
        assert UnrealDumper()._detect_ue4ss(tmp_path) is False

    def test_detect_ue4ss_recognises_xinput_marker(self, tmp_path):
        """xinput1_3.dll is also a valid UE4SS installation marker."""
        from src.dumper.ue import UnrealDumper
        (tmp_path / "xinput1_3.dll").touch()
        assert UnrealDumper()._detect_ue4ss(tmp_path) is True

    def test_raises_on_non_windows(self, ue4_info, tmp_path):
        """On non-Windows, _trigger_ue4ss_dump raises DumperError about Windows."""
        from unittest.mock import patch
        from src.dumper.ue import UnrealDumper
        from src.exceptions import DumperError
        # UE4SS present but not Windows
        (tmp_path / "UE4SS.dll").touch()
        dumper = UnrealDumper()
        with patch("src.dumper.ue._IS_WINDOWS", False):
            with pytest.raises(DumperError, match="Windows"):
                dumper._trigger_ue4ss_dump(tmp_path, ue4_info)

    def test_trigger_waits_for_dump_to_appear(self, ue4_info, tmp_path):
        """
        _trigger_ue4ss_dump polls until ObjectDump.txt appears.
        A background thread writes the file after a short delay.
        """
        import threading
        from unittest.mock import patch
        from src.dumper.ue import UnrealDumper

        (tmp_path / "UE4SS.dll").touch()

        def write_dump():
            import time
            time.sleep(0.15)
            (tmp_path / "ObjectDump.txt").write_text(
                "Class /Script/Engine.Actor\n"
                "  [+0x0000] RootComponent : USceneComponent\n"
            )

        t = threading.Thread(target=write_dump)
        t.start()

        dumper = UnrealDumper()
        with patch("src.dumper.ue._IS_WINDOWS", True), \
             patch.object(dumper, "_send_f10_to_game_window", return_value=True):
            dumper._trigger_ue4ss_dump(tmp_path, ue4_info)

        t.join()
        assert (tmp_path / "ObjectDump.txt").exists()

    def test_trigger_raises_if_game_window_not_found(self, ue4_info, tmp_path):
        """If game window cannot be found, raises DumperError with instructions."""
        from unittest.mock import patch
        from src.dumper.ue import UnrealDumper
        from src.exceptions import DumperError

        (tmp_path / "UE4SS.dll").touch()
        dumper = UnrealDumper()
        with patch("src.dumper.ue._IS_WINDOWS", True), \
             patch.object(dumper, "_send_f10_to_game_window", return_value=False):
            with pytest.raises(DumperError, match="Game window not found"):
                dumper._trigger_ue4ss_dump(tmp_path, ue4_info)

    def test_full_dump_with_preexisting_file(self, ue4_info, tmp_path):
        """If ObjectDump.txt already exists, _trigger_ue4ss_dump is never called."""
        from unittest.mock import patch
        from src.dumper.ue import UnrealDumper

        (tmp_path / "ObjectDump.txt").write_text(
            "Class /Script/Engine.Actor\n"
            "  [+0x0000] RootComponent : USceneComponent\n"
        )

        dumper = UnrealDumper()
        with patch.object(dumper, "_trigger_ue4ss_dump") as mock_trigger:
            result = dumper.dump(ue4_info)

        mock_trigger.assert_not_called()
        assert len(result.classes) == 1
        assert result.classes[0].name == "Actor"
```

### Step 2: Run tests — verify they FAIL

```bash
python -m pytest tests/unit/test_dumper_models.py::TestUnrealDumperUE4SS -v
```

Expected: `AttributeError: 'UnrealDumper' object has no attribute '_detect_ue4ss'`

### Step 3: Implement in `src/dumper/ue.py`

Replace file content. Key changes:
- Add `import platform`, `import time`
- Add `_IS_WINDOWS = platform.system() == "Windows"` constant
- Add `_UE4SS_MARKERS`, `_DUMP_POLL_INTERVAL`, `_DUMP_TIMEOUT` constants
- Replace the `else: raise DumperError(...)` block in `dump()` with `self._trigger_ue4ss_dump(game_dir, engine_info)`
- Add `_trigger_ue4ss_dump()`, `_detect_ue4ss()`, `_send_f10_to_game_window()` methods

```python
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
from src.exceptions import DumperError
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
        print(f"Waiting for ObjectDump.txt (up to {_DUMP_TIMEOUT:.0f}s)...")
        elapsed = 0.0
        while elapsed < _DUMP_TIMEOUT:
            if dump_file.exists():
                logger.info("ObjectDump.txt appeared after %.1fs", elapsed)
                return
            time.sleep(_DUMP_POLL_INTERVAL)
            elapsed += _DUMP_POLL_INTERVAL

        raise DumperError(
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
        import ctypes
        import ctypes.wintypes as wt

        VK_F10    = 0x79
        WM_KEYDOWN = 0x100
        WM_KEYUP   = 0x101

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
                ctypes.windll.user32.PostMessageW(hwnd, WM_KEYDOWN, VK_F10, 0)
                ctypes.windll.user32.PostMessageW(hwnd, WM_KEYUP,   VK_F10, 0)
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
```

### Step 4: Run tests — verify they PASS

```bash
python -m pytest tests/unit/test_dumper_models.py -v
```

Expected: all tests pass including new `TestUnrealDumperUE4SS`.

### Step 5: Run full test suite

```bash
python -m pytest -q
```

Expected: all tests pass (230+ total).

### Step 6: Commit

```bash
git add src/dumper/ue.py tests/unit/test_dumper_models.py
git commit -m "feat(dumper): UnrealDumper Phase 2 — UE4SS detection, F10 trigger, poll for ObjectDump"
```

---

## Final Verification

```bash
python -m pytest -q --tb=short
```

Expected output: `X passed in Y.YYs` with zero failures.

Verify the three stubs are gone:

```bash
grep -r "Phase 2\|not yet wired up\|NotImplementedError" src/
```

Expected: no matches (or only comments in docstrings describing completed Phase 2).

Final commit:

```bash
git add .
git commit -m "chore: Phase 2 complete — all three stubs implemented and tested"
```
