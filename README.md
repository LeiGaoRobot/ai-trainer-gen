# AI Game Trainer Generator

> 用 LLM 自动为单机 PC 游戏生成 Cheat Engine Lua 训练器脚本。

输入：游戏可执行文件路径 + 功能描述（如"无限血量"）
输出：可直接加载到 Cheat Engine 的 `.lua` 脚本或 `.ct` 表

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-213%20passed-brightgreen)](./tests/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41cd52)](https://pypi.org/project/PyQt6/)

---

## 功能特性

- 🔍 **引擎自动检测**：识别 Unity Mono / Unity IL2CPP / Unreal Engine 4&5
- 🧠 **引擎感知 Prompt**：根据引擎类型生成不同的 CE Lua 寻址策略
- 🤖 **多 LLM 后端**：支持 Anthropic Claude、OpenAI GPT、以及无 API Key 的离线 Stub
- 🔧 **AOB 沙箱验证**：自动校验 Array-of-Bytes 模式格式与唯一性
- 📦 **SQLite 持久化**：缓存已生成脚本，支持成功/失败统计
- 🖥️ **PyQt6 GUI**：向导式四页面界面（进程选择 → 功能配置 → 生成监控 → 脚本管理）
- ⌨️ **CLI 入口**：`generate` / `list` / `export` 子命令

---

## 流水线架构

```
游戏 EXE / 目录
      │
      ▼
┌─────────────┐
│  Detector   │  识别引擎：Unity_Mono / Unity_IL2CPP / UE4 / UE5 / Unknown
└──────┬──────┘
       │ EngineInfo
       ▼
┌─────────────┐
│   Dumper    │  解析运行时结构：类名、字段名、偏移量
└──────┬──────┘
       │ StructureJSON
       ▼
┌─────────────┐
│  Resolver   │  确定寻址策略：Mono API / IL2CPP 静态偏移 / UE GObjects
└──────┬──────┘
       │ EngineContext（含 FieldResolution 列表）
       ▼
┌─────────────┐
│  Analyzer   │  调用 LLM，生成 CE Lua 脚本
└──────┬──────┘
       │ GeneratedScript
       ▼
┌─────────────┐
│ CE Wrapper  │  AOB 沙箱验证 + 序列化为 .ct XML
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    Store    │  SQLite 持久化（CRUD + 统计）
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  GUI / CLI  │  PyQt6 向导界面 或 命令行
└─────────────┘
```

---

## 快速开始

### 依赖安装

```bash
pip install PyQt6 anthropic openai psutil
# 如只需运行测试，不需要 anthropic / openai
pip install pytest PyQt6
```

### 运行测试

```bash
QT_QPA_PLATFORM=offscreen pytest
# 全部 213 个测试应通过
```

### CLI 使用

```bash
# 查看已缓存脚本
python -m src.cli.main list
python -m src.cli.main list --game "Hollow Knight"

# 导出为 .ct 表
python -m src.cli.main export --id 1 --format ct --output ./out/

# 生成（完整流水线，需要 LLM API Key 或自动使用 Stub）
python -m src.cli.main generate --exe "/path/to/Game.exe" --feature "infinite_health"
```

### 启动 GUI

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

### LLM 后端配置

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # 使用 Claude（优先）
export OPENAI_API_KEY="sk-..."          # 使用 GPT
# 均不设置 → 自动使用离线 Stub（确定性输出，适合测试）
```

---

## 项目结构

```
ai-trainer-gen/
├── src/
│   ├── detector/          # 引擎指纹识别
│   ├── dumper/            # 运行时结构解析（Mono / IL2CPP / UE）
│   ├── resolver/          # 寻址策略（MonoAPI / IL2CPP_PTR / UE_GObjects / AOB_Write）
│   ├── analyzer/          # LLM 调用 + Prompt 构建 + 脚本验证
│   ├── ce_wrapper/        # .ct XML 构建 + AOB 沙箱验证
│   ├── store/             # SQLite CRUD（ScriptRecord）
│   ├── cli/               # argparse 命令行入口
│   └── gui/               # PyQt6 界面（MVVM）
│       ├── viewmodels.py  # 纯 Python ViewModel（无 Qt 依赖）
│       ├── main_window.py # QMainWindow + QStackedWidget
│       └── pages/         # 4 个向导页面
├── tests/unit/            # 213 个单元测试
├── PROJECT_PLAN.md        # 详细开发规划文档
├── pyproject.toml
└── README.md
```

---

## 开发进度

| 阶段 | 内容 | 状态 | 测试数 |
|------|------|------|--------|
| Week 1 | Detector + Dumper | ✅ | 86 |
| Week 2 | Analyzer + Resolver | ✅ | +47 = 133 |
| Week 3 | CE Wrapper | ✅ | +29 = 162 |
| Week 4 | Store + CLI | ✅ | +24 = 186 |
| Future | PyQt6 GUI | ✅ | +27 = **213** |

---

## 支持的引擎与寻址策略

| 引擎 | 策略 | AOB 数量 | 说明 |
|------|------|---------|------|
| Unity Mono | `MONO_API` | 0 | CE 内置 Mono 运行时桥 |
| Unity IL2CPP | `IL2CPP_PTR` | 1 | 根指针 + 静态偏移 |
| UE4 / UE5 | `UE_GOBJECTS` | 1 | GUObjectArray 遍历 |
| Unknown | `AOB_WRITE` | N | 每字段独立 AOB |

---

## 技术栈

- **Python 3.10+**
- **PyQt6** — GUI 框架
- **SQLite** (stdlib `sqlite3`) — 脚本持久化
- **xml.etree.ElementTree** — .ct XML 序列化
- **argparse** — CLI
- **pytest** — 测试框架
- **Anthropic / OpenAI SDK** — LLM 后端（可选）

---

## 已知限制

- CE COM 接口（`com_bridge.py`）仅在 Windows + Cheat Engine 安装环境下可用
- IL2CPP 根 AOB 目前为模板硬编码，实际使用需针对目标游戏调整
- `generate` CLI 子命令的完整流水线尚待串联

---

## License

MIT
