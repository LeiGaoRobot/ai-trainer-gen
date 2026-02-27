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
from src.dumper.base import get_dumper

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
    from src.resolver.factory import get_resolver
    from src.resolver.models import EngineContext
    from src.analyzer.llm_analyzer import LLMAnalyzer, LLMConfig
    from src.analyzer.models import TrainerFeature

    # 1. Detect engine
    logger.info("Detecting engine for: %s", exe_path)
    engine_info = GameEngineDetector().detect(exe_path)
    logger.info("Detected: %s", engine_info)

    # 2. Stable cache key derived from the game directory path.
    # Use the exe stem (e.g. "Game" from "Game.exe") as the human-readable
    # game name; fall back to the parent directory name if exe_path unavailable.
    exe_stem = Path(engine_info.exe_path).stem if engine_info.exe_path else ""
    game_name = exe_stem or Path(engine_info.game_dir).name
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
