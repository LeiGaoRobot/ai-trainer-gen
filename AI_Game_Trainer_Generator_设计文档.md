# AI Game Trainer Generator — 设计文档 v0.1

> **用途**：本文档供 AI Agent 读取，用于理解项目背景、技术约束和实现策略，辅助代码生成、方案决策和任务拆解。

---

## 项目定义

**目标**：构建一个 AI 驱动的单机游戏修改器（Trainer）自动生成系统，以 Cheat Engine（CE）为执行内核，对外封装智能 Wrapper，覆盖主流游戏引擎（Unity、Unreal Engine）。

**核心价值主张**：传统修改器制作需要手工扫描内存、追踪指针、编写 AOB。本系统通过 AI 分析游戏引擎符号结构，自动生成可执行的 CE Lua 脚本，大幅降低制作门槛。

**明确不做**：
- 联机游戏 / 有服务端验证的游戏
- 绕过反作弊系统（EAC、BattlEye 等）
- DRM 破解或版权相关操作

---

## 可行性矩阵

| 游戏类型 | 可行性 | 自动化率 | 主要策略 |
|---|---|---|---|
| Unity Mono | ✅ 高 | ~85% | Mono API 枚举类/字段，直接定位地址 |
| Unity IL2CPP | ✅ 较高 | ~70% | IL2CPPDumper 导出符号，AI 解析偏移 |
| Unreal Engine 4/5 | ✅ 较高 | ~65% | UE4SS dump GObjects，AI 生成访问脚本 |
| 自定义引擎 | ⚠️ 低 | ~40% | 半自动，需人工辅助标注数据结构 |
| 联机/有AC游戏 | ❌ 不适用 | 0% | 超出范围 |

---

## 系统架构（5层）

```
Layer 1: 输入层     → Game Engine Detector + Structure Dumper
Layer 2: AI 层      → LLM Analyzer（脚本生成 + AOB 生成）
Layer 3: 执行层     → CE Wrapper（注入 + 执行 + 验证）
Layer 4: 存储层     → Script Store（SQLite 缓存）
Layer 5: 展示层     → Trainer GUI（PyQt6 开关界面）
```

### 数据流

```
用户输入: 游戏路径 + 期望功能（如"无限血量"）
    ↓
[Game Engine Detector]  → EngineType + 版本
    ↓
[Structure Dumper]      → StructureJSON（类名/字段名/类型/偏移）
    ↓
[LLM Analyzer]          → CE Lua 脚本 + AOB 特征码（经语法验证）
    ↓
[CE Wrapper]            → 注入目标进程，执行脚本，返回成功/失败
    ↓
[Script Store]          → 写入缓存（key: game_hash + feature_name）
    ↓
[Trainer GUI]           → 渲染开关列表，绑定快捷键
```

---

## 核心组件规格

### Game Engine Detector

- **输入**：游戏根目录路径（string）
- **输出**：`EngineInfo { type: EngineType, version: string, bitness: 32|64 }`
- **检测规则**（按优先级）：
  1. 文件存在检测：`UnityPlayer.dll` → Unity；`UE4Game.exe` / `UE4-*.dll` → UE4；`UE5-*.dll` → UE5
  2. 二进制特征：扫描主 exe 的 PE header imports
  3. 子类型判断：Unity 下检测 `GameAssembly.dll` 存在 → IL2CPP，否则 → Mono
- **EngineType 枚举**：`Unity_Mono | Unity_IL2CPP | UE4 | UE5 | Unknown`

---

### Structure Dumper（按引擎分支）

#### Unity Mono 分支
- 工具：`mono-dissector` 或直接调用 Mono API（`mono_domain_get`、`mono_assembly_foreach`）
- 输出字段：`class_name, namespace, fields[{name, type, offset}], methods[{name, rva}]`
- 注意：需目标进程正在运行（runtime dump），不支持静态分析

#### Unity IL2CPP 分支
- 工具：`IL2CPPDumper`（开源，MIT）
- 输入：`GameAssembly.dll` + `global-metadata.dat`
- 输出：`dummy .cs` 文件 → 解析为 StructureJSON
- 关键字段：`[FieldOffset(0xXX)]` 注解携带内存偏移

#### Unreal Engine 分支
- 工具：`UE4SS`（LGPL）或运行时注入调用 `GObjects` 遍历
- 输出：UObject 属性列表，含 `PropertyClass`、`Offset_Internal`
- UE 版本差异处理：维护 `ue_offsets_table.json`，key = UE 版本号

#### 统一输出格式（StructureJSON）

```json
{
  "engine": "Unity_IL2CPP",
  "version": "2021.3.15",
  "classes": [
    {
      "name": "PlayerController",
      "namespace": "Game.Player",
      "fields": [
        { "name": "health", "type": "float", "offset": "0x58" },
        { "name": "maxHealth", "type": "float", "offset": "0x5C" },
        { "name": "gold", "type": "int32", "offset": "0x64" },
        { "name": "moveSpeed", "type": "float", "offset": "0x70" }
      ]
    }
  ]
}
```

---

### LLM Analyzer

#### Prompt 模板（功能分类）

```
系统角色：你是一个 Cheat Engine Lua 脚本专家，专注于单机游戏内存修改。

输入：
- 游戏名称：{game_name}
- 引擎类型：{engine_type}
- 结构信息：{structure_json}
- 目标功能：{feature_list}

输出要求：
1. 生成完整可运行的 CE Lua 脚本（.lua 格式）
2. 必须使用 AOB 扫描（mem.scan），禁止硬编码内存地址
3. 每个功能封装为独立函数，可单独开关
4. 包含错误处理（地址未找到时输出日志而非崩溃）
5. 脚本末尾附上 AOB 特征码的来源说明注释

功能类型映射规则：
- 无限血量 → 找 health/hp/hitpoint/life 相关字段，写入 maxHealth 值或极大值
- 无限金币 → 找 gold/money/coin/currency 相关字段
- 无限弹药 → 找 ammo/bullet/magazine 相关字段
- 移动速度 → 找 moveSpeed/speed/velocity 相关字段，乘以倍率
- 无敌模式 → 找伤害计算函数，NOP 掉扣血指令
```

#### 输出验证流程

```
LLM 输出脚本
    ↓
语法检查（Lua parser）→ 失败则重试（最多 3 次）
    ↓
AOB 格式验证（正则：([0-9A-F]{2}|\?){8,}）
    ↓
沙箱 AOB 扫描（CE API，不写内存）→ 验证特征码能扫到结果
    ↓
评分 { syntax_ok, aob_found, scan_count }
    ↓
写入 Script Store
```

---

### CE Wrapper

#### 接口设计（Python）

```python
class CEWrapper:
    def attach(self, process_name: str) -> bool: ...
    def execute_lua(self, script: str) -> ExecutionResult: ...
    def aob_scan(self, pattern: str) -> list[int]: ...
    def read_memory(self, address: int, size: int) -> bytes: ...
    def write_memory(self, address: int, data: bytes) -> bool: ...
    def detach(self) -> None: ...
```

#### CE 调用方式（优先级）

1. **CE COM Automation**（首选，Windows）：通过 `win32com.client` 调用 CE 暴露的 COM 接口
2. **CE Lua 文件 + CLI**：生成 `.ct` 文件，调用 `cheatengine.exe --lua-script=xxx.ct`
3. **cemu-ce**（无界面 CE）：用于无 GUI 场景或 CI 测试

---

### Script Store（SQLite Schema）

```sql
CREATE TABLE scripts (
    id          INTEGER PRIMARY KEY,
    game_hash   TEXT NOT NULL,       -- SHA256(exe path + file size)
    game_name   TEXT,
    engine_type TEXT,
    feature     TEXT NOT NULL,       -- "infinite_health" | "infinite_gold" | ...
    lua_script  TEXT NOT NULL,
    aob_sigs    TEXT,                -- JSON array of AOB patterns used
    created_at  DATETIME,
    last_used   DATETIME,
    success_count INTEGER DEFAULT 0,
    fail_count    INTEGER DEFAULT 0
);

CREATE INDEX idx_game_feature ON scripts(game_hash, feature);
```

---

### Trainer GUI

- **框架**：PyQt6
- **核心 Widget**：每个 feature → `QCheckBox` + `QKeySequenceEdit`（快捷键）
- **状态**：Attached（绿）/ Detached（灰）/ Error（红）
- **操作流程**：启动游戏 → 工具自动检测进程 → 加载对应脚本库 → 展示功能开关

---

## 技术选型

| 组件 | 选型 | 备注 |
|---|---|---|
| 主语言 | Python 3.12 | 主逻辑 + CE Wrapper |
| LLM 后端 | Claude API（首选）/ GPT-4o（备选）| 长上下文处理结构 JSON |
| 本地模型 | Mistral 7B / DeepSeek Coder（可选）| 离线场景，降低成本 |
| CE 接口 | COM Automation（Windows）| 需 CE 7.5+ 预装 |
| GUI | PyQt6 | 跨平台，生态成熟 |
| 数据库 | SQLite | 轻量无服务端 |
| 打包 | PyInstaller | 单文件可执行 |
| IL2CPP 解析 | IL2CPPDumper（MIT）| 随包附带 |
| UE 结构导出 | UE4SS（LGPL）| 用户侧安装 |

---

## 实现难度与风险

| 模块 | 难度 | 预估工时 | 主要风险 |
|---|---|---|---|
| Unity Mono 结构解析 | ★★☆☆☆ | 1 周 | 依赖第三方工具稳定性 |
| IL2CPP 结构解析 | ★★★☆☆ | 2 周 | 版本差异大（Dumper 兼容性） |
| UE4/UE5 SDK 解析 | ★★★☆☆ | 2 周 | 不同 UE 版本偏移不同 |
| LLM Prompt 工程 | ★★☆☆☆ | 1 周 | 需游戏样本调优，存在幻觉风险 |
| AOB 特征码自动生成 | ★★★★☆ | 3 周 | 游戏更新后失效，泛化性差 |
| 动态指针链追踪 | ★★★★☆ | 3 周 | 运行时路径变化，自动化挑战大 |
| CE Wrapper 封装 | ★★☆☆☆ | 1 周 | COM API 文档有限 |
| Trainer GUI | ★★☆☆☆ | 1 周 | 技术成熟 |
| 自定义引擎支持 | ★★★★★ | 不定 | 几乎无法完全自动化 |

### 关键风险缓解策略

1. **LLM 幻觉**：强制脚本经过沙箱 AOB 验证，不通过验证的脚本不入库
2. **AOB 失效**：游戏版本变更时触发重新生成，Script Store 记录版本关联
3. **IL2CPP 碎片化**：维护 Dumper 版本映射表，自动选择对应版本
4. **CE 依赖**：提供降级方案（纯 Python 内存操作库 `pymem` 作为备选）

---

## 开发路线图

### MVP（第 1-4 周）
- **目标**：支持 Unity Mono 游戏的命令行工具
- Week 1：Engine Detector + Unity Mono Structure Dumper
- Week 2：LLM Analyzer Prompt 工程 + 基础脚本生成
- Week 3：CE Wrapper + 端到端测试（5 款 Unity Mono 游戏）
- Week 4：修复打包，命令行 demo 可用
- **成功指标**：10 款 Unity Mono 游戏中 ≥ 7 款成功生成「无限血量」

### Beta（第 5-10 周）
- IL2CPP 支持 + UE 支持
- Trainer GUI（PyQt6）
- Script Store（SQLite）
- **成功指标**：20 款主流引擎游戏覆盖率 ≥ 60%

### v1.0（第 11-16 周）
- 脚本库 + 社区共享功能
- 游戏版本自适应（版本变更自动重新生成）
- 完整文档 + 安装包
- **成功指标**：脚本库收录 ≥ 100 款游戏

### v2.0（后续）
- 自定义引擎半自动化工作流
- 专用小模型 Fine-tuning
- 在线脚本库平台

---

## AI Agent 使用指引

> 本节专为 AI 代码生成 Agent 准备，描述在各子任务中应遵循的约束。

### 生成 Structure Dumper 代码时
- Unity Mono：优先使用 ctypes 调用 mono.dll 原生 API，避免依赖第三方 Python 库
- IL2CPP：Shell 调用 IL2CPPDumper，解析其输出的 `DummyDll/*.cs` 文件，使用正则提取 `[FieldOffset(0xXX)]`
- 输出必须严格符合 StructureJSON schema（见上方定义）

### 生成 LLM Prompt 时
- 字段名匹配使用模糊语义（health/hp/hitpoint 都指血量），不要硬匹配
- 生成的 Lua 脚本必须包含 `if address == 0 then print("AOB not found") return end` 保护
- AOB 特征码长度建议 12-24 字节，通配符（`??`）不超过 40%

### 生成 CE Wrapper 时
- Windows 平台使用 `pywin32`（`win32com.client`）
- 所有内存写操作前必须验证进程 PID 有效性
- 禁止写入进程主模块（.exe section）以外的区域

### 生成 GUI 时
- 每个功能 toggle 状态变更必须异步执行（`QThreadPool`），不阻塞主线程
- 进程未附加时所有 toggle 置灰

### 代码风格约束
- 类型注解完整（Python 3.12 `type alias` 语法）
- 每个模块包含 `__all__` 导出列表
- 错误处理使用自定义异常类（`CEWrapperError`, `DumperError`, `LLMAnalyzerError`）

---

## 外部依赖清单

| 工具 | 许可证 | 获取方式 | 用途 |
|---|---|---|---|
| Cheat Engine 7.5+ | Freeware | 用户预装 | 核心执行引擎 |
| IL2CPPDumper | MIT | 随包附带 | IL2CPP 符号导出 |
| UE4SS | LGPL-3.0 | 用户侧安装 | UE 结构导出 |
| pymem | MIT | pip install | CE 缺失时的备用内存操作 |
| pywin32 | PSF | pip install | CE COM 接口调用 |
| PyQt6 | GPL/商业 | pip install | GUI 框架 |

---

*文档版本：v0.1 | 日期：2026-02-24 | 状态：初始草稿*
