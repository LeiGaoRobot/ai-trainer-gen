# CLAUDE.md — AI Assistant Guide for ai-trainer-gen

## Project Overview

AI-powered game trainer generator for single-player PC games using Cheat Engine as the execution backend. Takes a game executable + feature description (e.g., "infinite health") and produces Lua scripts or `.ct` Cheat Engine tables via an LLM pipeline.

Supports Unity Mono, Unity IL2CPP, Unreal Engine 4/5, and unknown engines (AOB fallback).

## Quick Reference

```bash
# Install dependencies
pip install -e ".[dev]"

# Run all tests (213 unit tests, ~0.5s)
QT_QPA_PLATFORM=offscreen pytest

# Run tests with coverage
QT_QPA_PLATFORM=offscreen pytest --cov=src

# Lint
ruff check .

# Format
ruff format .
```

## Project Structure

```
src/
  exceptions.py            # Custom exception hierarchy (TrainerBaseError root)
  detector/                # Engine detection (static file analysis, no running game)
    engine_detector.py     # GameEngineDetector.detect()
    models.py              # EngineType enum, EngineInfo dataclass
  dumper/                   # Runtime structure extraction
    base.py                # AbstractDumper + get_dumper() factory
    models.py              # FieldInfo, ClassInfo, StructureJSON
    unity_mono.py          # UnityMonoDumper
    il2cpp.py              # IL2CPPDumper (wraps IL2CPPDumper.exe)
    ue.py                  # UnrealDumper (parses ObjectDump.txt)
  resolver/                # Field addressing strategies per engine
    base.py                # AbstractResolver interface
    models.py              # ResolutionStrategy, FieldResolution, EngineContext
    factory.py             # get_resolver(engine_type)
    mono_resolver.py       # MONO_API strategy
    il2cpp_resolver.py     # IL2CPP_PTR strategy
    unreal_resolver.py     # UE_GOBJECTS strategy
  analyzer/                # LLM integration & script generation
    llm_analyzer.py        # LLMAnalyzer (stub/anthropic/openai backends)
    models.py              # FeatureType, AOBSignature, TrainerFeature, GeneratedScript
    validator.py           # ScriptValidator (syntax, AOB format, CE API checks)
    prompts/builder.py     # PromptBuilder (engine-aware prompt assembly)
  ce_wrapper/              # Cheat Engine integration
    models.py              # CEProcess, InjectionResult, SandboxResult
    sandbox.py             # AOB format validation (no CE needed)
    ct_builder.py          # .ct XML file generation
    com_bridge.py          # Windows COM automation wrapper
  store/                   # SQLite persistence
    db.py                  # ScriptStore CRUD + search + invalidation
    models.py              # ScriptRecord dataclass
    migrations/schema.sql  # Database schema
  cli/                     # CLI entry point
    main.py                # generate/list/export subcommands (argparse)
  gui/                     # PyQt6 GUI (MVVM architecture)
    viewmodels.py          # Pure-Python ViewModels (testable without Qt)
    main_window.py         # Main window + 4-page stacked widget
    worker.py              # GenerateWorker (QThread for pipeline)
    pages/                 # process_select, feature_config, generate, script_manager
tests/
  unit/                    # 213 unit tests, all mocked (no real games needed)
```

## Data Flow Pipeline

```
GameEngineDetector.detect() → EngineInfo
  → get_dumper() → AbstractDumper.dump() → StructureJSON
  → get_resolver().resolve() → FieldResolution[]
  → LLMAnalyzer.analyze() → GeneratedScript
  → ScriptValidator.validate() → ScriptValidation
  → CTBuilder.build() → .ct XML
  → ScriptStore.save() → SQLite cache
```

Module dependency DAG (strict, no circular imports):
detector → dumper → resolver → analyzer → ce_wrapper → store → cli/gui

## Code Conventions

### Must Follow

- **Python 3.12+** — use modern type syntax (e.g., `type X = ...`, `int | None`)
- **Type annotations** required on all public functions
- **`__all__`** — every module must define its public API exports
- **Custom exceptions only** — always raise subclasses of `TrainerBaseError` from `src/exceptions.py`, never bare `Exception`
- **Logging** — use `logging` with `logger = logging.getLogger(__name__)`, never `print()`
- **Naming** — snake_case for functions/variables, PascalCase for classes
- **Docstrings** — English, Sphinx-compatible for public classes/functions
- **Inline comments** — Chinese for complex logic explanations
- **Line length** — 100 characters max (enforced by ruff)
- **Ruff rules** — E, F, I (isort), UP (pyupgrade), B (bugbear)

### Design Patterns

- **Factory pattern** for polymorphic selection: `get_dumper()`, `get_resolver()`, LLM backend selection
- **Strategy pattern** for engine-specific behavior (resolvers, dumpers)
- **Dataclasses** preferred for data models; use `frozen=True` where possible
- **MVVM** for the GUI — ViewModels are pure Python (no Qt dependency), testable independently

### Testing

- Every public function should have at least one happy-path test
- Tests use mocks, fixtures, and temporary directories — no real game processes required
- Use `QT_QPA_PLATFORM=offscreen` when running GUI-related tests on headless systems
- Integration tests are gated behind markers: `@pytest.mark.integration`, `@pytest.mark.windows_only`

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Build | setuptools + pyproject.toml |
| LLM | Anthropic Claude (primary), OpenAI (alt), Stub (testing) |
| GUI | PyQt6 (MVVM) |
| Database | SQLite3 (stdlib) |
| CLI | argparse |
| Testing | pytest + pytest-cov + pytest-mock |
| Lint/Format | ruff |
| Lua Validation | luaparser |
| Windows | pywin32 (COM), pymem (memory access) |

## Engine Resolution Strategies

| Engine | Strategy | AOB Count | Notes |
|--------|----------|-----------|-------|
| Unity Mono | `MONO_API` | 0 | Uses CE's built-in Mono bridge |
| Unity IL2CPP | `IL2CPP_PTR` | 1 | Single root pointer + static offsets |
| UE4 / UE5 | `UE_GOBJECTS` | 1 | Traverse GUObjectArray |
| Unknown | `AOB_WRITE` | N | One AOB per field (fallback) |

## Design Constraints

- Single-player games only — no online/server-validated games
- Does not bypass anti-cheat (EAC, BattlEye, etc.)
- CE COM interface is Windows-only; macOS/Linux functionality is limited
- Default LLM model: `claude-3-5-sonnet-20241022` in code
