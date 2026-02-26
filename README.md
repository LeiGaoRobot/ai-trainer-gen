# AI Game Trainer Generator

> Automatically generate Cheat Engine Lua trainer scripts for single-player PC games using an LLM pipeline.

**Input:** Game executable path + feature description (e.g. "infinite health")
**Output:** `.lua` script or `.ct` table ready to load in Cheat Engine

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-213%20passed-brightgreen)](./tests/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41cd52)](https://pypi.org/project/PyQt6/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](./LICENSE)

**Language / 语言 / 言語:**
[English](./README.md) · [中文](./README_zh.md) · [日本語](./README_ja.md)

---

## Features

- 🔍 **Automatic engine detection** — Unity Mono / Unity IL2CPP / Unreal Engine 4 & 5
- 🧠 **Engine-aware prompting** — tailored CE Lua addressing strategy per engine type
- 🤖 **Multiple LLM backends** — Anthropic Claude, OpenAI GPT, or offline Stub (no API key needed)
- 🔧 **AOB sandbox validation** — format checking and uniqueness verification for Array-of-Bytes patterns
- 📦 **SQLite persistence** — caches generated scripts with success / failure counters
- 🖥️ **PyQt6 GUI** — wizard-style four-page interface (process → features → generate → history)
- ⌨️ **CLI** — `generate` / `list` / `export` subcommands

---

## Pipeline Architecture

```
Game EXE / directory
        │
        ▼
┌───────────────┐
│   Detector    │  Fingerprint engine: Unity_Mono / Unity_IL2CPP / UE4 / UE5 / Unknown
└───────┬───────┘
        │ EngineInfo
        ▼
┌───────────────┐
│    Dumper     │  Parse runtime structures: class names, field names, offsets
└───────┬───────┘
        │ StructureJSON
        ▼
┌───────────────┐
│   Resolver    │  Choose addressing strategy: Mono API / IL2CPP static ptr / UE GObjects
└───────┬───────┘
        │ EngineContext (with FieldResolution list)
        ▼
┌───────────────┐
│   Analyzer    │  Call LLM with engine-aware prompt → generate CE Lua script
└───────┬───────┘
        │ GeneratedScript
        ▼
┌───────────────┐
│  CE Wrapper   │  AOB sandbox validation + serialize to .ct XML
└───────┬───────┘
        │
        ▼
┌───────────────┐
│     Store     │  SQLite CRUD + success/failure statistics
└───────┬───────┘
        │
        ▼
┌───────────────┐
│   GUI / CLI   │  PyQt6 wizard UI or command-line interface
└───────────────┘
```

---

## Quick Start

### Install Dependencies

```bash
pip install PyQt6 anthropic openai psutil
# For tests only (no LLM keys needed):
pip install pytest PyQt6
```

### Run Tests

```bash
QT_QPA_PLATFORM=offscreen pytest
# Expected: 213 passed
```

### CLI Usage

```bash
# List cached scripts
python -m src.cli.main list
python -m src.cli.main list --game "Hollow Knight"

# Export as .ct table
python -m src.cli.main export --id 1 --format ct --output ./out/

# Generate (full pipeline; uses Stub if no API key is set)
python -m src.cli.main generate --exe "/path/to/Game.exe" --feature "infinite_health"
```

### Launch GUI

```bash
python -c "
import sys
from PyQt6.QtWidgets import QApplication
from src.gui.main_window import MainWindow
app = QApplication(sys.argv)
win = MainWindow()
win.show()
sys.exit(app.exec())
"
```

### LLM Backend Configuration

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Use Claude (preferred)
export OPENAI_API_KEY="sk-..."          # Use GPT-4
# Neither set → automatic offline Stub (deterministic output, good for testing)
```

---

## Project Structure

```
ai-trainer-gen/
├── src/
│   ├── detector/          # Engine fingerprinting
│   ├── dumper/            # Runtime structure parsing (Mono / IL2CPP / UE)
│   ├── resolver/          # Addressing strategies (MonoAPI / IL2CPP_PTR / UE_GObjects / AOB_Write)
│   ├── analyzer/          # LLM calls + prompt building + script validation
│   ├── ce_wrapper/        # .ct XML builder + AOB sandbox
│   ├── store/             # SQLite CRUD (ScriptRecord)
│   ├── cli/               # argparse entry point
│   └── gui/               # PyQt6 MVVM interface
│       ├── viewmodels.py  # Pure-Python ViewModels (no Qt dependency)
│       ├── main_window.py # QMainWindow + QStackedWidget
│       └── pages/         # Four wizard pages
├── tests/unit/            # 213 unit tests
├── PROJECT_PLAN.md        # Detailed development plan (Chinese)
├── pyproject.toml
└── README.md
```

---

## Development Progress

| Phase | Content | Status | Tests |
|-------|---------|--------|-------|
| Week 1 | Detector + Dumper | ✅ | 86 |
| Week 2 | Analyzer + Resolver | ✅ | +47 = 133 |
| Week 3 | CE Wrapper | ✅ | +29 = 162 |
| Week 4 | Store + CLI | ✅ | +24 = 186 |
| Future | PyQt6 GUI | ✅ | +27 = **213** |

---

## Supported Engines & Addressing Strategies

| Engine | Strategy | AOB Count | Notes |
|--------|----------|-----------|-------|
| Unity Mono | `MONO_API` | 0 | Uses CE's built-in Mono runtime bridge |
| Unity IL2CPP | `IL2CPP_PTR` | 1 | Single root pointer + static offsets |
| UE4 / UE5 | `UE_GOBJECTS` | 1 | Traverse GUObjectArray |
| Unknown | `AOB_WRITE` | N | One AOB per field |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| GUI | PyQt6 |
| Database | SQLite (`sqlite3` stdlib) |
| CT serialization | `xml.etree.ElementTree` |
| CLI | `argparse` |
| Testing | `pytest` (213 tests) |
| LLM backends | Anthropic Claude / OpenAI GPT / Stub |

---

## Known Limitations

- The CE COM interface (`com_bridge.py`) requires Windows + a Cheat Engine installation
- The IL2CPP root AOB is a hardcoded template; real games may need adjustment
- The `generate` CLI subcommand's end-to-end pipeline is not yet fully wired

---

## License

MIT
