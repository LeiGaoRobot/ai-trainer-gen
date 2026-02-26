"""
cli — command-line interface for ai-trainer-gen.

Entry points
────────────
  python -m ai_trainer_gen   (via src/__main__.py)
  generate-trainer           (via pyproject.toml [project.scripts])

Subcommands: generate | list | export
"""

from src.cli.main import build_parser, cmd_list, cmd_export, main

__all__ = ["build_parser", "cmd_list", "cmd_export", "main"]
