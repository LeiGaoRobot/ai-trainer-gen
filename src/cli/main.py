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
import logging
import sys
from pathlib import Path
from typing import Optional

from src.store.db import ScriptStore
from src.store.models import ScriptRecord

__all__ = ["build_parser", "cmd_list", "cmd_export", "main"]

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


# ── Command implementations ───────────────────────────────────────────────────


def cmd_list(store: ScriptStore, game: Optional[str]) -> None:
    """
    Print cached script records to stdout.

    Args:
        store: ScriptStore to query.
        game:  Optional game name substring filter.
    """
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
    """
    Export a cached script record to a file.

    Args:
        store:      ScriptStore to query.
        record_id:  Id of the record to export.
        fmt:        "ct" for Cheat Table XML, "lua" for raw Lua.
        output_dir: Directory to write the file to (default: cwd).

    Returns:
        Path to the written file.

    Raises:
        ValueError: If *record_id* does not exist in the store.
    """
    # Retrieve by id: search across all records and filter
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
        # ct format — build XML via CTBuilder
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
    """
    Main CLI entry point.

    Returns:
        Exit code (0 = success, non-zero = error).
    """
    parser = build_parser()
    ns = parser.parse_args(argv)

    # Configure logging
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
        # Full pipeline — requires detector → dumper → analyzer chain.
        # Implemented in a later iteration; placeholder error for now.
        print(
            "generate subcommand: full pipeline not yet wired up. "
            "Run with --stub once the pipeline module is available.",
            file=sys.stderr,
        )
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
