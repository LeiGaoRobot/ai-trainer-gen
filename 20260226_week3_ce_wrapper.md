# 变更说明 — Week 3 CE Wrapper 实现

**日期**：2026-02-26
**阶段**：Week 3

---

## 变更概要

1. **修复** `EngineType.__str__` Python 3.12 兼容性问题（`str, Enum` 成员在 3.12 中 `str()` 返回 `EngineType.XXX` 而非字符串值，改用 `.value`）。
2. **修复** `pyproject.toml` 中 pytest 配置，固化 `-p no:langsmith_plugin`，绕过 `langsmith 0.3.10` + Python 3.12.11 不兼容的环境问题。
3. **新增** `src/ce_wrapper/` 模块，实现 CE Wrapper 核心组件。
4. **新增** 29 个单元测试，总测试数从 133 升至 162。

---

## 涉及文件

### 修改
| 文件 | 变更内容 |
|------|---------|
| `src/detector/models.py` | `EngineInfo.__str__` 改用 `self.type.value` 替代 `self.type` |
| `pyproject.toml` | pytest `addopts` 增加 `-p no:langsmith_plugin` |
| `PROJECT_PLAN.md` | 更新进度总览，Week 3 标记为完成，测试数 162 |

### 新增
| 文件 | 职责 |
|------|------|
| `src/ce_wrapper/__init__.py` | 模块公开 API：`CEProcess`, `InjectionResult`, `CTBuilder`, `Sandbox`, `SandboxResult` |
| `src/ce_wrapper/models.py` | `CEProcess`（进程描述符）、`InjectionResult`（注入结果） |
| `src/ce_wrapper/ct_builder.py` | `CTBuilder.build()` — 将 `GeneratedScript` 序列化为 `.ct` XML |
| `src/ce_wrapper/sandbox.py` | `Sandbox.validate_aob_pattern()`（纯格式校验）+ `Sandbox.check_aob_unique()`（唯一命中验证）+ `SandboxResult` |
| `tests/unit/test_ce_wrapper.py` | 29 个单元测试，覆盖上述所有模块 |

---

## 实现原理

### `models.py`

- `CEProcess(pid, name, is_64bit=True)` — 描述已附加进程，`is_64bit` 默认 True（现代游戏基本 64 位）
- `InjectionResult(success, feature_id, error?, address?)` — 统一注入结果，无论 COM / pymem / Mock 后端

### `ct_builder.py`

生成符合 CE 原生格式的 XML：

```xml
<CheatTable generated_by="ai-trainer-gen" engine="Unity_Mono">
  <CheatEntries>
    <CheatEntry>
      <Description>Infinite Health</Description>
      <Hotkey>F1</Hotkey>
      <AssemblerScript>[ENABLE]\n...[DISABLE]</AssemblerScript>
    </CheatEntry>
  </CheatEntries>
  <LuaScript>-- full lua code --</LuaScript>
  <AOBSignatures>
    <Signature Name="health_aob">
      <ByteArray>48 8B 05 ?? ?? ?? ??</ByteArray>
      <Offset>0</Offset>
      <Module>game.exe</Module>
    </Signature>
  </AOBSignatures>
</CheatTable>
```

### `sandbox.py`

**`validate_aob_pattern(pattern)`**（类方法，无状态）：
1. 非空且按空格分隔
2. 每个 token 为 2 位十六进制或 `??`
3. ≥ 4 个 token（最小有意义长度）
4. 通配符比例 ≤ 60%（允许 RIP 相对寻址的 `48 8B 05 ?? ?? ?? ??` 等常见模式）

**`check_aob_unique(hit_count, aob_name)`**（实例方法）：
- `0` → FAIL "0 matches — pattern not found"
- `1` → PASS "1 unique match"
- `>1` → FAIL "N multiple matches — pattern too generic"

---

## 测试变化

| 测试文件 | 之前 | 之后 | 新增 |
|---------|------|------|------|
| `test_detector.py` | 17 | 17 | — |
| `test_dumper_models.py` | 23 | 23 | — |
| `test_analyzer.py` | 47 | 47 | — |
| `test_resolver.py` | 46 | 46 | — |
| `test_ce_wrapper.py` | 0 | **29** | +29 |
| **合计** | **133** | **162** | **+29** |

---

## 下一步 — Week 4：Store + CLI

按 `PROJECT_PLAN.md` 第六节实现：

- `src/store/models.py` — `ScriptRecord` 数据类
- `src/store/db.py` — SQLite CRUD（save / load / search / delete）
- `src/store/migrations/schema.sql` — 建表 SQL
- `src/cli/main.py` — `generate` / `list` / `export` 子命令
- 新增测试 ≥ 20 个，总测试数目标 ≥ 182
