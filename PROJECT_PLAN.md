# AI Game Trainer Generator — 项目规划文档

> **用途**：供 AI 续写开发时加载，快速恢复项目上下文，了解已完成内容与待实现计划。
> **最后更新**：2026-02-26
> **当前测试数**：213 个全部通过

---

## 一、项目简介

为单机 PC 游戏自动生成 Cheat Engine (CE) Lua 脚本的工具链。
输入：游戏可执行文件路径 + 用户想修改的功能描述（如"无限血量"）
输出：可直接加载到 CE 的 `.lua` 脚本（或 `.ct` 表）

### 技术栈
- Python 3.10+
- Cheat Engine COM Automation (win32com) — Windows 运行时注入
- LLM 后端：Anthropic Claude / OpenAI（可切换，也有离线 Stub）
- 测试：pytest
- 打包：pyproject.toml (setuptools)

---

## 二、整体流水线

```
EXE / 游戏目录
      │
      ▼
┌─────────────┐
│  Detector   │  识别引擎类型：Unity_Mono / Unity_IL2CPP / UE4 / UE5 / Unknown
└──────┬──────┘
       │ EngineInfo
       ▼
┌─────────────┐
│   Dumper    │  解析运行时结构：类名、字段名、字段类型、偏移量
└──────┬──────┘
       │ StructureJSON
       ▼
┌─────────────┐
│  Resolver   │  决定寻址策略：Mono API / IL2CPP 静态偏移 / UE GObjects
└──────┬──────┘
       │ EngineContext（含 FieldResolution 列表）
       ▼
┌─────────────┐
│  Analyzer   │  调用 LLM，注入引擎感知 Prompt，生成 CE Lua 脚本
└──────┬──────┘
       │ GeneratedScript
       ▼
┌─────────────┐
│ CE Wrapper  │  通过 COM / pymem 注入 CE，沙箱验证 AOB，输出 .ct 表  ← 待实现
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    Store    │  SQLite 脚本库 + CLI 入口                              ← 待实现
└──────┬──────┘
       │
       ▼
┌─────────────┐
│     GUI     │  PyQt6：进程选择 → 功能勾选 → 一键生成                 ← 待实现
└─────────────┘
```

---

## 三、进度总览

| 阶段 | 内容 | 状态 | 测试数 |
|------|------|------|--------|
| Week 1 | Detector + Dumper | ✅ 完成 | 86 |
| Week 2 | Analyzer（模型 + PromptBuilder + Validator + LLMAnalyzer） | ✅ 完成 | +47 = 133 |
| 架构重构 | Resolver 模块 + 引擎感知 Prompt/Validator | ✅ 完成 | 包含在上方 |
| Week 3 | CE Wrapper（COM 注入 + .ct 生成 + 沙箱验证） | ✅ 完成 | +29 = 162 |
| Week 4 | Store（SQLite）+ CLI 入口 + 打包 | ✅ 完成 | +24 = 186 |
| Future | PyQt6 GUI（ViewModels + 4 Pages + MainWindow） | ✅ 完成 | +27 = 213 |

---

## 四、已完成模块详细说明

### 4.1 `src/detector/` — 引擎检测

| 文件 | 职责 |
|------|------|
| `models.py` | `EngineInfo(engine_type, version, bitness, exe_path, mono_path, il2cpp_path)` |
| `engine_detector.py` | `EngineDetector.detect(exe_path) -> EngineInfo`；扫描目录特征文件（mono.dll / GameAssembly.dll / UnrealEngine 标记）|

**检测逻辑**：
1. 扫描 `<exe_dir>` 和 `<exe_dir>/../` 下的 DLL
2. 发现 `mono.dll` / `mono-2.0-bdwgc.dll` → `Unity_Mono`
3. 发现 `GameAssembly.dll` → `Unity_IL2CPP`
4. 发现 `UE4-*.dll` 或 `UE4Editor*` → `UE4`；`UE5-*` → `UE5`
5. 否则 → `Unknown`

---

### 4.2 `src/dumper/` — 结构解析

| 文件 | 职责 |
|------|------|
| `models.py` | `ClassInfo`, `FieldInfo`, `StructureJSON` |
| `base.py` | `AbstractDumper` ABC；`dump(exe_path, engine_info) -> StructureJSON` |
| `unity_mono.py` | 解析 `Assembly-CSharp.dll`（反射 or dnSpy 输出） |
| `il2cpp.py` | 解析 `il2cpp_dump.cs`（il2CppDumper 工具输出） |
| `ue.py` | 解析 UE4SS `Dump/` 目录下的 `*.hpp` |

**关键字段优先级排序**：CamelCase tokenizer 避免子串误匹配（如 `Health` 不会命中 `HealthRegenRate`）

---

### 4.3 `src/resolver/` — 寻址策略（架构重构核心）

| 文件 | 职责 |
|------|------|
| `models.py` | `ResolutionStrategy` 枚举、`FieldResolution` 数据类、`EngineContext` |
| `base.py` | `AbstractResolver` ABC |
| `mono_resolver.py` | 生成 `_monoOffset("ns","Class","field")` 表达式；preamble 提供 CE Mono API 辅助函数 |
| `il2cpp_resolver.py` | 静态偏移 + 一个根 AOB；preamble 提供 `_resolveRIP()` / `_findRoot()` |
| `unreal_resolver.py` | 单一 GUObjectArray AOB + `_findActor(className)`；遍历 UObject 数组 |
| `factory.py` | `get_resolver(engine_type) -> AbstractResolver` |

**ResolutionStrategy 枚举**：

| 策略 | 适用场景 | AOB 数量 |
|------|---------|---------|
| `MONO_API` | Unity Mono | 0（CE 内置运行时桥） |
| `IL2CPP_PTR` | Unity IL2CPP | 1（根指针） |
| `UE_GOBJECTS` | UE4 / UE5 | 1（GUObjectArray） |
| `AOB_WRITE` | 未知引擎 fallback | N（每字段一个） |

---

### 4.4 `src/analyzer/` — LLM 脚本生成

| 文件 | 职责 |
|------|------|
| `models.py` | `AOBSignature`, `TrainerFeature`, `GeneratedScript`, `ScriptValidation` |
| `prompts/builder.py` | `PromptBuilder`；`_ENGINE_ADDENDUM` 按引擎注入不同 CE API 指导；`_resolution_table()` 将 FieldResolution 格式化为 Markdown 表格给 LLM |
| `validator.py` | `ScriptValidator`；按 `resolution_strategy` 跳过/减轻 AOB 检查 |
| `llm_analyzer.py` | `LLMAnalyzer`；支持 Anthropic / OpenAI / Stub 后端；含重试逻辑 |

**引擎感知 Prompt 策略**：
- `Unity_Mono`：禁止 LLM 生成 AOB，强制使用 `mono_findClass` / `mono_getClassField` / `mono_getFieldOffset`
- `Unity_IL2CPP`：只允许一个根 AOB，字段用静态偏移 `readFloat(base + 0xXX)`
- `UE4/UE5`：只允许 GUObjectArray AOB，字段通过 `_findActor()` + 静态偏移访问

---

## 五、Week 3 实现计划 — `src/ce_wrapper/`

### 目标
通过 CE COM Automation 接口将生成的 Lua 脚本注入 CE，验证 AOB 命中并输出 `.ct` 表。

### 文件结构
```
src/ce_wrapper/
├── __init__.py
├── models.py          # CEProcess, InjectionResult, CTTable
├── com_bridge.py      # win32com 封装：connectCE(), executeScript(), getAddresses()
├── pymem_fallback.py  # 无 CE 环境时用 pymem 直接读写内存（测试用）
├── ct_builder.py      # 将 GeneratedScript 序列化为 .ct XML
└── sandbox.py         # 沙箱验证：AOB 命中率 / 地址有效性 / 写入反弹测试
```

### 关键接口
```python
class CEBridge:
    def connect(self, ce_path: str) -> bool: ...
    def inject(self, script: GeneratedScript, process_name: str) -> InjectionResult: ...
    def validate_aob(self, aob: str, module: str) -> list[int]: ...  # 返回命中地址列表

class CTBuilder:
    def build(self, script: GeneratedScript, engine_ctx: EngineContext) -> str: ...  # XML string
```

### 验收条件
- `InjectionResult.success == True` 且 AOB 命中数 == 1（唯一命中）
- `.ct` 文件可被 CE 直接加载
- 无 CE 环境下 pymem fallback 可运行沙箱测试
- 新增测试 ≥ 25 个，总测试数 ≥ 158

---

## 六、Week 4 实现计划 — Store + CLI

### 目标
持久化生成历史，提供 CLI 入口，打包为 wheel。

### 文件结构
```
src/store/
├── __init__.py
├── models.py      # ScriptRecord(id, game, engine, feature, script, created_at, rating)
├── db.py          # SQLite CRUD：save / load / search / delete
└── migrations/    # schema.sql

src/cli/
├── __init__.py
└── main.py        # `python -m ai_trainer_gen` 入口；argparse 子命令：generate / list / export
```

### CLI 使用示例
```bash
# 生成脚本
python -m ai_trainer_gen generate \
  --exe "C:/Games/MyGame/MyGame.exe" \
  --feature "infinite health" \
  --output ./out/

# 查看历史
python -m ai_trainer_gen list --game "MyGame"

# 导出 .ct 表
python -m ai_trainer_gen export --id 42 --format ct
```

### 验收条件
- `generate` 子命令端到端跑通（Stub LLM 模式）
- SQLite 可持久化并检索
- `python -m build` 生成 wheel 无报错
- 新增测试 ≥ 20 个，总测试数 ≥ 178

---

## 七、Future — GUI（`src/gui/`）✅ 已完成

### 技术选型：PyQt6

### 实现结构
```
src/gui/
├── __init__.py           # 公开 MainWindow
├── viewmodels.py         # 纯 Python MVVM ViewModels（无 Qt 依赖，可独立测试）
├── main_window.py        # QMainWindow + QStackedWidget，管理页面导航
└── pages/
    ├── __init__.py
    ├── process_select.py # ProcessSelectPage：进程列表 + 过滤 + 刷新
    ├── feature_config.py # FeatureConfigPage：功能复选框 + 自定义描述 + Generate 按钮
    ├── generate.py       # GeneratePage：QPlainTextEdit 日志 + QProgressBar + Back 按钮
    └── script_manager.py # ScriptManagerPage：QTableWidget 历史 + 搜索 + Export 按钮
```

### ViewModels（`src/gui/viewmodels.py`）
| 类 | 职责 |
|----|------|
| `ProcessInfo` | 轻量进程描述符（pid, name） |
| `ProcessListViewModel` | 进程列表 + 文本过滤 + 选中状态 |
| `FeatureConfigViewModel` | 标准功能列表 + toggle() + 自定义描述 |
| `GenerateState` | IDLE / RUNNING / DONE / ERROR 枚举 |
| `GenerateViewModel` | 日志行 + 进度（0-1）+ 状态转换 |
| `ScriptManagerViewModel` | ScriptRecord 列表 + 搜索过滤 |

### 主要页面
1. **ProcessSelectPage**：列出运行中进程，支持名称过滤，Refresh / Select 按钮
2. **FeatureConfigPage**：复选框选择功能（8 种标准功能），自定义描述文本框，Generate 按钮
3. **GeneratePage**：实时日志流（QPlainTextEdit）+ 进度条（QProgressBar），Back 按钮
4. **ScriptManagerPage**：历史脚本表格（ID / Game / Feature / OK·Fail），搜索 + Export 按钮

### 测试策略
- **ViewModel 测试**（17 个）：纯 Python，无需显示设备，`test_gui_viewmodels.py`
- **Widget 测试**（10 个）：`QT_QPA_PLATFORM=offscreen`，`test_gui_widgets.py`

---

## 八、代码规范与开发规则

### 开发规则（每次 AI 续写必须遵守）
1. **每次修改或新增代码后**，在 `brainstorm/ai-trainer-gen/` 下生成 `YYYYMMDD_<描述>.md` 变更说明文档
2. **文档格式**：变更概要 → 涉及文件 → 实现原理 → 测试变化 → 下一步
3. **所有文档使用 Markdown**，不使用 Word
4. **测试先行**：新模块至少配套 unit test，`pytest` 全部通过才算完成
5. **Python 3.10 兼容**：用 `(str, Enum)` 不用 `StrEnum`；类型提示用 `Optional[X]` 不用 `X | None`

### 目录约定
```
ai-trainer-gen/
├── src/                  # 源码
├── tests/unit/           # 单元测试
├── tests/integration/    # 集成测试（Week 3+ 引入）
├── PROJECT_PLAN.md       # 本文件：项目规划，AI 续写时首先加载
├── DEVELOPMENT.md        # 开发者环境搭建
└── YYYYMMDD_*.md         # 各次变更说明文档
```

### LLM 后端配置（环境变量）
```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # 使用 Claude
export OPENAI_API_KEY="sk-..."          # 使用 GPT
# 均不设置 → 自动使用离线 Stub 后端（确定性输出，用于测试）
```

---

## 九、已知问题 / 技术债

| 问题 | 优先级 | 说明 |
|------|--------|------|
| Dumper 目前无法连接真实 CE 进程，只解析离线 dump 文件 | Medium | Week 3 CE Wrapper 会解决运行时部分 |
| IL2CPPResolver 的根 AOB 是硬编码模板 | Low | 应从实际游戏 binary 动态搜索 |
| UnrealResolver UE5 AOB 未经真实游戏验证 | Medium | 需要真实 UE5 游戏测试 |
| StubBackend 输出固定，不测试 LLM 实际响应质量 | Low | 需要 integration test + 真实 LLM 调用 |
| 无 Windows 运行时，CE COM 接口完全未测试 | High | Week 3 需要 Windows 环境或 Mock |

---

*本文档由 AI 自动维护，每次开发迭代后更新进度总览和待实现计划。*
