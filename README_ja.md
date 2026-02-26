# AI ゲームトレーナージェネレーター

> LLM パイプラインを使って、シングルプレイヤー PC ゲーム向けの Cheat Engine Lua トレーナースクリプトを自動生成するツール。

**入力：** ゲームの実行ファイルパス + 機能の説明（例：「無限体力」）
**出力：** Cheat Engine にそのままロードできる `.lua` スクリプトまたは `.ct` テーブル

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-213%20passed-brightgreen)](./tests/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41cd52)](https://pypi.org/project/PyQt6/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](./LICENSE)

**Language / 语言 / 言語:**
[English](./README.md) · [中文](./README_zh.md) · [日本語](./README_ja.md)

---

## 主な機能

- 🔍 **エンジン自動検出** — Unity Mono / Unity IL2CPP / Unreal Engine 4 & 5 を識別
- 🧠 **エンジン対応プロンプト** — エンジン種別に応じた CE Lua アドレッシング戦略を生成
- 🤖 **複数の LLM バックエンド** — Anthropic Claude、OpenAI GPT、または API キー不要のオフライン Stub
- 🔧 **AOB サンドボックス検証** — Array-of-Bytes パターンのフォーマットと一意性を自動検証
- 📦 **SQLite 永続化** — 生成済みスクリプトをキャッシュ、成功/失敗カウンター付き
- 🖥️ **PyQt6 GUI** — 4 ページのウィザード UI（プロセス選択 → 機能設定 → 生成モニター → 履歴管理）
- ⌨️ **CLI** — `generate` / `list` / `export` サブコマンド

---

## パイプラインアーキテクチャ

```
ゲームの EXE / ディレクトリ
        │
        ▼
┌───────────────┐
│   Detector    │  エンジン判定：Unity_Mono / Unity_IL2CPP / UE4 / UE5 / Unknown
└───────┬───────┘
        │ EngineInfo
        ▼
┌───────────────┐
│    Dumper     │  ランタイム構造解析：クラス名・フィールド名・オフセット
└───────┬───────┘
        │ StructureJSON
        ▼
┌───────────────┐
│   Resolver    │  アドレッシング戦略決定：Mono API / IL2CPP 静的オフセット / UE GObjects
└───────┬───────┘
        │ EngineContext（FieldResolution リスト付き）
        ▼
┌───────────────┐
│   Analyzer    │  エンジン対応プロンプトで LLM を呼び出し → CE Lua スクリプト生成
└───────┬───────┘
        │ GeneratedScript
        ▼
┌───────────────┐
│  CE Wrapper   │  AOB サンドボックス検証 + .ct XML へのシリアライズ
└───────┬───────┘
        │
        ▼
┌───────────────┐
│     Store     │  SQLite CRUD + 成功/失敗統計
└───────┬───────┘
        │
        ▼
┌───────────────┐
│   GUI / CLI   │  PyQt6 ウィザード UI またはコマンドライン
└───────────────┘
```

---

## クイックスタート

### 依存関係のインストール

```bash
pip install PyQt6 anthropic openai psutil
# テストのみ実行する場合（LLM API キー不要）:
pip install pytest PyQt6
```

### テストの実行

```bash
QT_QPA_PLATFORM=offscreen pytest
# 期待値: 213 tests passed
```

### CLI の使い方

```bash
# キャッシュ済みスクリプトの一覧
python -m src.cli.main list
python -m src.cli.main list --game "Hollow Knight"

# .ct テーブルとしてエクスポート
python -m src.cli.main export --id 1 --format ct --output ./out/

# 生成（API キーが未設定の場合は自動的に Stub を使用）
python -m src.cli.main generate --exe "/path/to/Game.exe" --feature "infinite_health"
```

### GUI の起動

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

### LLM バックエンドの設定

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude を使用（推奨）
export OPENAI_API_KEY="sk-..."          # GPT-4 を使用
# どちらも未設定 → オフライン Stub を自動使用（決定論的出力、テスト向け）
```

---

## プロジェクト構成

```
ai-trainer-gen/
├── src/
│   ├── detector/          # エンジンフィンガープリント
│   ├── dumper/            # ランタイム構造解析（Mono / IL2CPP / UE）
│   ├── resolver/          # アドレッシング戦略（MonoAPI / IL2CPP_PTR / UE_GObjects / AOB_Write）
│   ├── analyzer/          # LLM 呼び出し + プロンプト構築 + スクリプト検証
│   ├── ce_wrapper/        # .ct XML ビルダー + AOB サンドボックス
│   ├── store/             # SQLite CRUD（ScriptRecord）
│   ├── cli/               # argparse エントリーポイント
│   └── gui/               # PyQt6 MVVM インターフェース
│       ├── viewmodels.py  # 純粋 Python ViewModel（Qt 依存なし・単体テスト可能）
│       ├── main_window.py # QMainWindow + QStackedWidget
│       └── pages/         # 4 つのウィザードページ
├── tests/unit/            # 213 個のユニットテスト
├── PROJECT_PLAN.md        # 詳細な開発計画書（中国語）
├── pyproject.toml
└── README.md
```

---

## 開発進捗

| フェーズ | 内容 | 状態 | テスト数 |
|---------|------|------|---------|
| Week 1 | Detector + Dumper | ✅ | 86 |
| Week 2 | Analyzer + Resolver | ✅ | +47 = 133 |
| Week 3 | CE Wrapper | ✅ | +29 = 162 |
| Week 4 | Store + CLI | ✅ | +24 = 186 |
| Future | PyQt6 GUI | ✅ | +27 = **213** |

---

## 対応エンジンとアドレッシング戦略

| エンジン | 戦略 | AOB 数 | 説明 |
|---------|------|--------|------|
| Unity Mono | `MONO_API` | 0 | CE の内蔵 Mono ランタイムブリッジを使用 |
| Unity IL2CPP | `IL2CPP_PTR` | 1 | 単一のルートポインタ + 静的オフセット |
| UE4 / UE5 | `UE_GOBJECTS` | 1 | GUObjectArray をトラバース |
| Unknown | `AOB_WRITE` | N | フィールドごとに独立した AOB |

---

## 技術スタック

| コンポーネント | 技術 |
|--------------|------|
| 言語 | Python 3.10+ |
| GUI | PyQt6 |
| データベース | SQLite（標準ライブラリ `sqlite3`） |
| CT シリアライズ | `xml.etree.ElementTree` |
| CLI | `argparse` |
| テスト | `pytest`（213 テスト） |
| LLM バックエンド | Anthropic Claude / OpenAI GPT / Stub |

---

## 既知の制限事項

- CE COM インターフェース（`com_bridge.py`）は Windows + Cheat Engine インストール環境でのみ動作します
- IL2CPP のルート AOB は現在ハードコードされたテンプレートであり、実際のゲームに合わせた調整が必要な場合があります
- `generate` CLI サブコマンドのエンドツーエンドパイプラインは未接続です

---

## ライセンス

MIT
