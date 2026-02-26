# AI Game Trainer Generator — 开发者文档 v0.1

> **读者对象**：参与本项目开发的工程师 / AI Agent
> **前置阅读**：`AI_Game_Trainer_Generator_设计文档.md`

---

## 目录

1. [项目结构](#1-项目结构)
2. [开发环境搭建](#2-开发环境搭建)
3. [数据模型定义](#3-数据模型定义)
4. [模块接口规范](#4-模块接口规范)
5. [扩展指南](#5-扩展指南)
6. [测试策略](#6-测试策略)
7. [配置参考](#7-配置参考)
8. [常见问题与调试](#8-常见问题与调试)

---

## 1. 项目结构

```
ai-trainer-gen/
├── pyproject.toml                  # 项目元数据 & 依赖
├── requirements.txt                # pip 锁定依赖
├── config/
│   ├── settings.yaml               # 全局配置（LLM API key、CE 路径等）
│   └── ue_offsets_table.json       # UE 版本偏移映射表
├── src/
│   ├── detector/                   # 引擎检测模块
│   │   ├── engine_detector.py
│   │   └── models.py
│   ├── dumper/                     # 结构导出模块
│   │   ├── base.py                 # AbstractDumper 接口
│   │   ├── unity_mono.py
│   │   ├── il2cpp.py
│   │   ├── ue.py
│   │   └── models.py               # StructureJSON 数据模型
│   ├── analyzer/                   # LLM 分析模块
│   │   ├── llm_analyzer.py
│   │   ├── validator.py            # 脚本语法验证
│   │   └── prompts/
│   │       ├── base.py
│   │       └── feature_templates.py
│   ├── ce_wrapper/                 # CE 封装模块
│   │   ├── wrapper.py
│   │   ├── com_backend.py          # Windows COM（主）
│   │   ├── pymem_backend.py        # pymem 降级方案
│   │   └── models.py
│   ├── store/                      # 脚本缓存模块
│   │   ├── script_store.py
│   │   └── models.py
│   └── gui/                        # Trainer GUI
│       ├── main_window.py
│       ├── widgets.py
│       └── assets/
├── tests/
│   ├── unit/                       # 单元测试
│   ├── integration/                # 集成测试
│   └── fixtures/                   # 测试用游戏结构 JSON
├── tools/
│   └── il2cpp_dumper/              # 随包 IL2CPPDumper 二进制
└── scripts/
    └── generate_trainer.py         # CLI 入口
```

### 模块依赖关系

```
detector → dumper → analyzer → ce_wrapper
                       ↓
                     store
                       ↓
                      gui
```

各模块单向依赖，`store` 和 `gui` 是叶节点，不反向依赖上游。

---

## 2. 开发环境搭建

### 2.1 系统要求

| 依赖 | 最低版本 | 说明 |
|---|---|---|
| Windows | 10 / 11 (x64) | CE COM 接口仅支持 Windows |
| Python | 3.12 | 使用 `type` 新语法和 `tomllib` |
| Cheat Engine | 7.5 | 需安装并注册 COM 服务 |
| Node.js | 18+ | 仅文档生成用，非运行时依赖 |

### 2.2 步骤一：克隆与虚拟环境

```bash
git clone https://github.com/your-org/ai-trainer-gen.git
cd ai-trainer-gen

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS（受限功能）

pip install -e ".[dev]"
```

### 2.3 步骤二：注册 CE COM 接口

Cheat Engine 安装后需手动注册 COM 服务，否则 `CEWrapper` 无法连接：

```powershell
# 以管理员身份运行 PowerShell
& "C:\Program Files\Cheat Engine 7.5\cheatengine-x86_64.exe" /registerCOM
```

验证注册成功：

```python
import win32com.client
ce = win32com.client.Dispatch("CEServer.Application")  # 不报错即成功
```

### 2.4 步骤三：配置 LLM API Key

复制配置模板并填写：

```bash
cp config/settings.yaml.example config/settings.yaml
```

```yaml
# config/settings.yaml
llm:
  provider: anthropic          # anthropic | openai | local
  api_key: "sk-ant-xxxxx"      # 或通过环境变量 ANTHROPIC_API_KEY
  model: claude-opus-4-5-20251101
  max_tokens: 8192

ce:
  exe_path: "C:/Program Files/Cheat Engine 7.5/cheatengine-x86_64.exe"
  use_com: true                # false 则降级到 pymem backend

store:
  db_path: "~/.ai-trainer/scripts.db"
```

### 2.5 步骤四：端到端冒烟测试

```bash
python scripts/generate_trainer.py \
  --game "C:/Games/MyGame/MyGame.exe" \
  --features infinite_health infinite_gold \
  --dry-run                    # dry-run 只生成脚本，不注入
```

预期输出：

```
[INFO] Engine detected: Unity_IL2CPP 2022.3.10
[INFO] Dumping structure...  OK (234 classes)
[INFO] Calling LLM...        OK (script generated, 87 lines)
[INFO] AOB validation...     OK (3/3 patterns found)
[INFO] DRY RUN — script saved to: output/MyGame_trainer.lua
```

---

## 3. 数据模型定义

所有跨模块传递的数据结构在此定义，作为模块间的契约。

### 3.1 EngineInfo

```python
# src/detector/models.py
from dataclasses import dataclass
from enum import StrEnum

class EngineType(StrEnum):
    UNITY_MONO   = "Unity_Mono"
    UNITY_IL2CPP = "Unity_IL2CPP"
    UE4          = "UE4"
    UE5          = "UE5"
    UNKNOWN      = "Unknown"

@dataclass
class EngineInfo:
    type: EngineType
    version: str           # 例: "2022.3.10" 或 "4.27.2"
    bitness: int           # 32 或 64
    exe_path: str
    game_dir: str
    extra: dict            # 引擎特定附加信息（如 mono.dll 路径）
```

### 3.2 StructureJSON

```python
# src/dumper/models.py
from dataclasses import dataclass, field

@dataclass
class FieldInfo:
    name: str
    type: str              # "float" | "int32" | "bool" | "string" | "Vector3" | ...
    offset: str            # 十六进制字符串，如 "0x58"
    is_static: bool = False

@dataclass
class ClassInfo:
    name: str
    namespace: str
    fields: list[FieldInfo]
    parent_class: str | None = None

@dataclass
class StructureJSON:
    engine: str            # EngineType 字符串值
    version: str
    classes: list[ClassInfo]
    raw_dump_path: str     # 原始 dump 文件路径（调试用）

    def to_prompt_str(self, max_classes: int = 50) -> str:
        """序列化为适合送入 LLM Prompt 的紧凑字符串"""
        ...
```

### 3.3 GeneratedScript

```python
# src/analyzer/models.py
from dataclasses import dataclass

@dataclass
class AOBSignature:
    name: str              # 例: "player_health_write"
    pattern: str           # 例: "48 89 ?? ?? ?? 8B 87 ?? ?? ?? ??"
    offset: int            # 从扫描结果地址的偏移量

@dataclass
class TrainerFeature:
    id: str                # snake_case，例: "infinite_health"
    label: str             # 用户可见名称，例: "无限血量"
    hotkey: str | None     # 默认快捷键，例: "F1"

@dataclass
class GeneratedScript:
    features: list[TrainerFeature]
    lua_code: str
    aob_signatures: list[AOBSignature]
    validation: "ScriptValidation"

@dataclass
class ScriptValidation:
    syntax_ok: bool
    aob_found: dict[str, bool]  # sig_name → 是否在目标进程中找到
    scan_counts: dict[str, int] # sig_name → 扫描结果数量
    errors: list[str]
```

### 3.4 ScriptRecord（存储层）

```python
# src/store/models.py
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ScriptRecord:
    id: int | None
    game_hash: str         # SHA256(exe_path + file_size)
    game_name: str
    engine_type: str
    feature: str           # TrainerFeature.id
    lua_script: str
    aob_sigs: str          # JSON 序列化的 list[AOBSignature]
    created_at: datetime
    last_used: datetime | None
    success_count: int = 0
    fail_count: int = 0
```

### 3.5 ExecutionResult

```python
# src/ce_wrapper/models.py
from dataclasses import dataclass

@dataclass
class ExecutionResult:
    success: bool
    feature_id: str
    error: str | None = None
    address: int | None = None  # 找到的内存地址（调试用）
```

---

## 4. 模块接口规范

### 4.1 GameEngineDetector

```python
# src/detector/engine_detector.py

class GameEngineDetector:
    """
    检测游戏使用的引擎类型和版本。
    纯静态分析，不需要目标游戏运行。
    """

    def detect(self, game_exe_path: str) -> EngineInfo:
        """
        检测给定游戏可执行文件的引擎信息。

        Args:
            game_exe_path: 游戏主 .exe 文件的绝对路径

        Returns:
            EngineInfo 对象

        Raises:
            FileNotFoundError: game_exe_path 不存在
            DetectorError: 检测过程中出现不可恢复错误
        """
        ...

    def _detect_unity(self, game_dir: str) -> tuple[str, bool]:
        """返回 (unity_version, is_il2cpp)"""
        ...

    def _detect_ue(self, game_dir: str) -> tuple[str, int]:
        """返回 (ue_version_str, major_version)"""
        ...
```

**检测规则优先级**（代码中按序执行）：

| 优先级 | 检测条件 | 结论 |
|---|---|---|
| 1 | `GameAssembly.dll` 存在 | Unity_IL2CPP |
| 2 | `Mono/` 目录或 `mono.dll` 存在 | Unity_Mono |
| 3 | `UnityPlayer.dll` 存在（无 Mono/IL2CPP 特征）| Unity_Mono（保守） |
| 4 | `UE5-*.dll` 存在 | UE5 |
| 5 | `UE4-*.dll` 或 `UE4Game.exe` 存在 | UE4 |
| 6 | 均不匹配 | Unknown |

---

### 4.2 AbstractDumper & 具体实现

```python
# src/dumper/base.py
from abc import ABC, abstractmethod

class AbstractDumper(ABC):
    """所有 Dumper 的基类，定义统一接口。"""

    @abstractmethod
    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        """
        导出游戏结构信息。

        Args:
            engine_info: 由 GameEngineDetector 返回的引擎信息

        Returns:
            标准化的 StructureJSON

        Raises:
            DumperError: 导出失败（工具不存在、游戏未运行等）
            UnsupportedVersionError: 引擎版本不在支持范围内
        """
        ...

    @abstractmethod
    def supports(self, engine_info: EngineInfo) -> bool:
        """返回此 Dumper 是否支持给定引擎。工厂选择时调用。"""
        ...
```

```python
# src/dumper/unity_mono.py
class UnityMonoDumper(AbstractDumper):
    """
    通过 Mono 运行时 API 导出 Unity Mono 游戏的类结构。
    目标游戏必须正在运行。
    """

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        """
        1. 定位目标进程的 mono.dll
        2. 调用 mono_domain_get() 获取当前域
        3. 遍历 mono_domain_get_assemblies()
        4. 对每个 assembly 调用 mono_image_get_table_rows() 枚举类
        5. 对每个类调用 mono_class_get_fields() 枚举字段
        """
        ...

    def supports(self, engine_info: EngineInfo) -> bool:
        return engine_info.type == EngineType.UNITY_MONO
```

```python
# src/dumper/il2cpp.py
class IL2CPPDumper(AbstractDumper):
    """
    调用外部 IL2CPPDumper 工具，解析其输出的 dummy .cs 文件。
    纯静态分析，不需要目标游戏运行。
    """
    DUMPER_PATH = "tools/il2cpp_dumper/Il2CppDumper.exe"

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        """
        1. 定位 GameAssembly.dll 和 global-metadata.dat
        2. Shell 调用 IL2CPPDumper.exe，输出到临时目录
        3. 解析 DummyDll/*.cs 文件，提取 [FieldOffset(0xXX)] 注解
        4. 构建 StructureJSON
        """
        ...
```

```python
# src/dumper/ue.py
class UnrealDumper(AbstractDumper):
    """
    通过 UE4SS 导出 Unreal Engine 游戏的 UObject 属性树。
    """

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        """
        1. 注入 UE4SS 到目标进程
        2. 调用 UE4SS Lua API: UE4SS.dumpObjects()
        3. 解析输出的 ObjectDump.txt
        4. 通过 ue_offsets_table.json 补充版本特定偏移
        """
        ...
```

**Dumper 工厂**：

```python
# src/dumper/__init__.py

def get_dumper(engine_info: EngineInfo) -> AbstractDumper:
    """根据引擎类型选择并返回对应的 Dumper 实例。"""
    dumpers = [UnityMonoDumper(), IL2CPPDumper(), UnrealDumper()]
    for d in dumpers:
        if d.supports(engine_info):
            return d
    raise UnsupportedEngineError(f"No dumper for engine: {engine_info.type}")
```

---

### 4.3 LLMAnalyzer

```python
# src/analyzer/llm_analyzer.py

class LLMAnalyzer:
    """
    调用 LLM 分析游戏结构，生成 CE Lua 脚本。
    """

    def __init__(self, config: LLMConfig): ...

    def analyze(
        self,
        structure: StructureJSON,
        features: list[str],           # ["infinite_health", "infinite_gold"]
        game_name: str,
    ) -> GeneratedScript:
        """
        1. 构建 Prompt（base + structure + feature templates）
        2. 调用 LLM API
        3. 解析响应，提取 Lua 脚本和 AOB 签名
        4. 调用 ScriptValidator 验证
        5. 若验证失败，重试（最多 MAX_RETRIES=3 次）
        6. 返回 GeneratedScript

        Raises:
            LLMAPIError: API 调用失败
            ScriptGenerationError: 经过重试仍无法生成有效脚本
        """
        ...

    def _build_prompt(
        self,
        structure: StructureJSON,
        features: list[str],
        game_name: str,
    ) -> str:
        """组合 system prompt + 结构 JSON + 功能需求"""
        ...

    def _parse_response(self, raw: str) -> tuple[str, list[AOBSignature]]:
        """从 LLM 响应中提取 Lua 代码块和 AOB 表"""
        ...
```

**Prompt 结构**（模板组成）：

```
[system_base.txt]          # 角色定义、输出格式要求
    +
[structure_section]        # 序列化的 StructureJSON（结构 JSON）
    +
[feature_template_N]       # 每个请求功能的语义描述
    +
[output_constraints]       # 强制要求：AOB、错误处理、函数封装
```

---

### 4.4 ScriptValidator

```python
# src/analyzer/validator.py

class ScriptValidator:
    """
    对 LLM 生成的 CE Lua 脚本进行语法和运行时验证。
    """

    def validate_syntax(self, lua_code: str) -> tuple[bool, list[str]]:
        """
        使用 luaparser 库检查语法正确性。
        返回 (ok, error_messages)
        """
        ...

    def validate_aob_format(self, sigs: list[AOBSignature]) -> tuple[bool, list[str]]:
        """
        验证 AOB 格式：
        - 每个 byte 为 2 位十六进制或 "??"
        - 总长度 8-32 bytes
        - 通配符比例 ≤ 40%
        """
        ...

    def validate_aob_scan(
        self,
        sigs: list[AOBSignature],
        ce_wrapper: "CEWrapper",
    ) -> dict[str, bool]:
        """
        在目标进程中实际执行 AOB 扫描（只读，不写内存）。
        返回 {sig_name: found}
        """
        ...
```

---

### 4.5 CEWrapper

```python
# src/ce_wrapper/wrapper.py

class CEWrapper:
    """
    Cheat Engine 的 Python 封装层。
    自动选择 COM backend（Windows）或 pymem backend（降级）。
    """

    def __init__(self, config: CEConfig): ...

    def attach(self, process_name: str) -> bool:
        """
        附加到目标进程。

        Args:
            process_name: 进程名，如 "MyGame.exe"

        Returns:
            True 表示成功，False 表示进程未找到

        Raises:
            CEWrapperError: CE 未安装或 COM 注册失败
        """
        ...

    def detach(self) -> None:
        """安全脱离目标进程，还原所有已激活的修改。"""
        ...

    def execute_lua(self, script: str) -> ExecutionResult:
        """
        在附加进程的上下文中执行 Lua 脚本。
        脚本必须通过 ScriptValidator 验证后才能调用此方法。
        """
        ...

    def aob_scan(self, pattern: str) -> list[int]:
        """
        在目标进程内存中扫描 AOB 特征码。
        仅读操作，不修改内存。

        Returns:
            匹配地址列表（正常情况下应只有 1 个结果）
        """
        ...

    def read_float(self, address: int) -> float: ...
    def write_float(self, address: int, value: float) -> bool: ...
    def read_int32(self, address: int) -> int: ...
    def write_int32(self, address: int, value: int) -> bool: ...

    @property
    def is_attached(self) -> bool: ...
```

**Backend 选择逻辑**：

```python
# src/ce_wrapper/__init__.py
def create_wrapper(config: CEConfig) -> CEWrapper:
    if config.use_com and _is_ce_com_available():
        return CEWrapper(config, backend=COMBackend(config))
    else:
        import warnings
        warnings.warn("CE COM not available, falling back to pymem backend.")
        return CEWrapper(config, backend=PymemBackend())
```

---

### 4.6 ScriptStore

```python
# src/store/script_store.py

class ScriptStore:
    """
    本地 SQLite 缓存，避免同款游戏重复调用 LLM。
    """

    def __init__(self, db_path: str): ...

    def get(self, game_hash: str, feature: str) -> ScriptRecord | None:
        """查询缓存。未命中返回 None。"""
        ...

    def save(self, record: ScriptRecord) -> int:
        """保存脚本记录，返回 row id。"""
        ...

    def record_success(self, record_id: int) -> None:
        """脚本执行成功时调用，更新 success_count 和 last_used。"""
        ...

    def record_failure(self, record_id: int) -> None:
        """脚本执行失败时调用，更新 fail_count。"""
        ...

    def invalidate(self, game_hash: str) -> int:
        """游戏更新时使所有关联缓存失效，返回清除的记录数。"""
        ...

    def export_ct(self, record_id: int, output_path: str) -> None:
        """将脚本导出为 CE .ct 格式文件。"""
        ...
```

**SQLite Schema**（初始化 SQL）：

```sql
CREATE TABLE IF NOT EXISTS scripts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_hash     TEXT    NOT NULL,
    game_name     TEXT,
    engine_type   TEXT,
    feature       TEXT    NOT NULL,
    lua_script    TEXT    NOT NULL,
    aob_sigs      TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    last_used     TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game_hash, feature)
);
CREATE INDEX IF NOT EXISTS idx_game_feature ON scripts(game_hash, feature);
```

---

### 4.7 CLI 入口

```python
# scripts/generate_trainer.py

def main():
    """
    CLI 用法：
      generate_trainer.py --game <exe_path>
                          --features <f1> [f2 ...]
                          [--dry-run]
                          [--no-cache]
                          [--output <path>]
                          [--gui]

    参数说明：
      --game        游戏 .exe 路径（必填）
      --features    要生成的功能列表（支持: infinite_health, infinite_gold,
                    infinite_ammo, move_speed, invincible, one_hit_kill）
      --dry-run     生成脚本但不注入进程
      --no-cache    跳过 ScriptStore 缓存，强制重新生成
      --output      脚本输出路径（默认: output/<game_name>_trainer.lua）
      --gui         生成脚本后自动打开 Trainer GUI
    """
```

---

## 5. 扩展指南

### 5.1 新增引擎支持

以新增"Godot Engine"支持为例：

**Step 1**：在 `src/detector/engine_detector.py` 添加检测规则：

```python
# 在 _detect_engine() 方法的规则列表中添加
{"file": "godot.exe",          "type": EngineType.GODOT},
{"file": "libgodot.so",        "type": EngineType.GODOT},
```

**Step 2**：在 `EngineType` 枚举中添加值：

```python
GODOT = "Godot"
```

**Step 3**：创建 `src/dumper/godot.py`，继承 `AbstractDumper`：

```python
class GodotDumper(AbstractDumper):
    def supports(self, engine_info: EngineInfo) -> bool:
        return engine_info.type == EngineType.GODOT

    def dump(self, engine_info: EngineInfo) -> StructureJSON:
        # 实现 Godot 特有的结构导出逻辑
        ...
```

**Step 4**：在 `src/dumper/__init__.py` 的工厂中注册：

```python
dumpers = [UnityMonoDumper(), IL2CPPDumper(), UnrealDumper(), GodotDumper()]
```

**Step 5**：在 `tests/unit/test_detector.py` 添加检测测试用例。

---

### 5.2 新增功能类型（Feature）

以新增"一击必杀"为例：

**Step 1**：在 `src/analyzer/prompts/feature_templates.py` 添加模板：

```python
FEATURE_TEMPLATES = {
    # ... 现有模板 ...
    "one_hit_kill": """
功能: 一击必杀
目标: 找到伤害计算函数，将对敌人造成的伤害值乘以极大倍率（如 99999）
提示字段: damage / attackPower / dmg / atk
优先策略: 找到写入敌人 health 的指令，将写入值替换为 0
备选策略: 找到伤害乘数字段直接修改
CE 脚本要求: AOB 扫描 + 汇编注入（使用 writeBytes 或 auto-assemble）
""",
}
```

**Step 2**：在 CLI `--features` 的 help 文本中更新可选值列表。

**Step 3**：在 `tests/fixtures/` 添加对应的测试用 StructureJSON。

---

### 5.3 切换 LLM 后端

在 `config/settings.yaml` 修改 `llm.provider`：

| provider 值 | 使用的后端 | 说明 |
|---|---|---|
| `anthropic` | Anthropic API | 默认，推荐用于复杂结构分析 |
| `openai` | OpenAI API | GPT-4o，备选 |
| `local` | Ollama HTTP API | 离线场景，需本地运行 Ollama |

本地模式配置示例：

```yaml
llm:
  provider: local
  local_url: "http://localhost:11434/api/generate"
  model: "deepseek-coder:6.7b"
```

---

## 6. 测试策略

### 6.1 测试分层

```
tests/
├── unit/
│   ├── test_detector.py        # 引擎检测规则单测
│   ├── test_il2cpp_parser.py   # IL2CPP 符号解析单测
│   ├── test_aob_validator.py   # AOB 格式验证单测
│   └── test_script_store.py   # SQLite CRUD 单测
├── integration/
│   ├── test_unity_mono_flow.py # Unity Mono 端到端（需目标游戏）
│   └── test_ce_wrapper.py     # CE Wrapper 连接测试（需 CE）
└── fixtures/
    ├── unity_mono_sample.json  # 模拟结构 JSON（无需真实游戏）
    ├── il2cpp_sample.json
    └── ue4_sample.json
```

### 6.2 单元测试规范

```python
# 示例：test_aob_validator.py

def test_valid_aob():
    v = ScriptValidator()
    ok, errs = v.validate_aob_format([AOBSignature(
        name="test", pattern="48 8B 05 ?? ?? ?? ?? 48 85 C0", offset=0
    )])
    assert ok is True
    assert errs == []

def test_wildcard_too_many():
    v = ScriptValidator()
    ok, errs = v.validate_aob_format([AOBSignature(
        name="bad", pattern="?? ?? ?? ?? ?? ?? ?? ?? ?? ??", offset=0
    )])
    assert ok is False
    assert any("wildcard" in e for e in errs)
```

### 6.3 集成测试（需要真实游戏）

集成测试默认跳过，需设置环境变量才运行：

```bash
# 设置测试用游戏路径
export TRAINER_TEST_GAME="C:/Games/TestGame/TestGame.exe"
export TRAINER_TEST_FEATURES="infinite_health"

pytest tests/integration/ -v
```

### 6.4 LLM 调用 Mock

单测中不调用真实 LLM API，使用 fixture 替代：

```python
# tests/unit/conftest.py
import pytest
from unittest.mock import patch

@pytest.fixture
def mock_llm(tmp_path):
    sample_script = (Path("tests/fixtures") / "sample_lua.lua").read_text()
    with patch("src.analyzer.llm_analyzer.LLMAnalyzer._call_api") as m:
        m.return_value = sample_script
        yield m
```

### 6.5 运行测试

```bash
# 所有单元测试
pytest tests/unit/ -v

# 覆盖率报告
pytest tests/unit/ --cov=src --cov-report=html

# 特定模块
pytest tests/unit/test_detector.py -v -k "test_unity"
```

---

## 7. 配置参考

### 7.1 完整 settings.yaml 说明

```yaml
llm:
  provider: anthropic          # anthropic | openai | local
  api_key: ""                  # 也可通过 ANTHROPIC_API_KEY 环境变量传入
  model: claude-opus-4-5-20251101
  max_tokens: 8192
  temperature: 0.2             # 低温度，减少随机性
  max_retries: 3               # 生成失败最大重试次数

ce:
  exe_path: ""                 # 留空则自动探测常见安装路径
  use_com: true                # false 则强制使用 pymem backend
  timeout_sec: 30              # 脚本执行超时

store:
  db_path: "~/.ai-trainer/scripts.db"
  auto_invalidate: true        # 检测到游戏文件变更时自动清除缓存

dumper:
  il2cpp_dumper_path: "tools/il2cpp_dumper/Il2CppDumper.exe"
  ue4ss_path: ""               # UE4SS 安装路径，留空则提示用户
  dump_timeout_sec: 60         # 结构导出超时

gui:
  theme: dark                  # dark | light
  always_on_top: true
  hotkey_enable: true
```

### 7.2 ue_offsets_table.json 格式

```json
{
  "4.27": {
    "GObjects_offset": "0x0",
    "GNames_offset":   "0x0",
    "FNamePool":       false
  },
  "5.0": {
    "GObjects_offset": "0x0",
    "GNames_offset":   "0x0",
    "FNamePool":       true
  },
  "5.3": {
    "GObjects_offset": "0x0",
    "GNames_offset":   "0x0",
    "FNamePool":       true
  }
}
```

> 偏移值需从 UE 源码或已知分析结果填入，留 `"0x0"` 的条目表示"运行时动态探测"。

---

## 8. 常见问题与调试

### Q1：`DetectorError: Cannot determine engine type`

**原因**：游戏目录结构不标准，或游戏使用自定义打包工具。
**处理**：
```bash
# 手动指定引擎类型
python scripts/generate_trainer.py --game xxx.exe --engine Unity_IL2CPP
```

### Q2：`DumperError: mono.dll not found in process`

**原因**：游戏未运行，或 Mono 模式下 DLL 名称不标准（部分游戏使用 `MonoPosixHelper.dll`）。
**处理**：先启动游戏进入主菜单，再运行工具。

### Q3：`LLMAPIError: Rate limit exceeded`

**处理**：在 `settings.yaml` 中增加 `max_retries` 或切换到本地 LLM。

### Q4：AOB 扫描返回 0 个结果

**可能原因**：
1. 游戏版本更新后特征码失效 → 用 `--no-cache` 重新生成
2. LLM 生成的特征码错误 → 检查 `output/debug_aob.log`
3. 64位游戏但特征码按32位写的 → 检查 `engine_info.bitness`

### Q5：CE COM 连接失败

```powershell
# 验证 CE COM 注册状态
reg query "HKEY_CLASSES_ROOT\CEServer.Application"

# 重新注册
& "C:\Program Files\Cheat Engine 7.5\cheatengine-x86_64.exe" /registerCOM
```

### 调试模式

```bash
# 开启详细日志（保留所有中间产物）
python scripts/generate_trainer.py --game xxx.exe --features infinite_health --debug

# debug 模式额外输出：
# - output/debug_structure.json     （原始 StructureJSON）
# - output/debug_prompt.txt         （发送给 LLM 的完整 Prompt）
# - output/debug_llm_response.txt   （LLM 原始响应）
# - output/debug_aob.log            （AOB 扫描详细结果）
```

---

## 异常类层次

```
TrainerBaseError
├── DetectorError
│   └── UnsupportedEngineError
├── DumperError
│   ├── UnsupportedVersionError
│   └── DumpTimeoutError
├── LLMAnalyzerError
│   ├── LLMAPIError
│   └── ScriptGenerationError       # 重试耗尽
├── CEWrapperError
│   ├── ProcessNotFoundError
│   └── ScriptExecutionError
└── StoreError
```

---

## 代码风格约束（供 AI Agent 参考）

- **类型注解**：所有公开函数必须有完整类型注解（Python 3.12 新语法 `type X = ...` 优先）
- **`__all__`**：每个模块必须定义，只导出公开接口
- **异常**：使用本项目自定义异常类，不直接 `raise Exception`
- **日志**：使用 `logging`，不用 `print`；logger name = 模块 `__name__`
- **测试**：每个公开函数至少一个 happy path 单测
- **注释**：复杂逻辑用中文行内注释，docstring 用英文（兼容 Sphinx）
- **格式化**：`ruff format`（替代 black）；lint：`ruff check`

---

*文档版本：v0.1 | 日期：2026-02-24*
