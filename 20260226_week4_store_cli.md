# 变更说明 — Week 4 Store + CLI 实现

**日期**：2026-02-26
**阶段**：Week 4

---

## 变更概要

实现 `src/store/`（SQLite 持久化层）和 `src/cli/`（CLI 入口），新增 24 个单元测试，总测试数从 162 升至 186。

---

## 涉及文件

### 新增
| 文件 | 职责 |
|------|------|
| `src/store/__init__.py` | 公开 `ScriptRecord`, `ScriptStore` |
| `src/store/models.py` | `ScriptRecord` 数据类（持久化字段 + 计数器） |
| `src/store/db.py` | `ScriptStore` SQLite CRUD（save / get / search / invalidate / record_success / record_failure / delete） |
| `src/store/migrations/schema.sql` | 建表 DDL（含唯一约束 + 索引） |
| `src/cli/__init__.py` | 公开 `build_parser`, `cmd_list`, `cmd_export`, `main` |
| `src/cli/main.py` | argparse 解析器 + 三个子命令实现 |
| `tests/unit/test_store.py` | 16 个 store 单元测试 |
| `tests/unit/test_cli.py` | 8 个 CLI 单元测试 |

### 修改
| 文件 | 变更内容 |
|------|---------|
| `PROJECT_PLAN.md` | 更新测试数（186）、Week 4 标记完成 |

---

## 实现原理

### `src/store/`

**ScriptRecord** 字段：
- `(game_hash, feature)` 联合唯一键，用于缓存命中检测
- `success_count / fail_count` 追踪脚本可靠性
- `last_used` 追踪使用时间，可按此淘汰过期缓存
- `aob_sigs` JSON 字符串，存储 AOBSignature 列表

**ScriptStore** 关键设计决策：
- 每次操作使用独立连接（`with self._connect()`），安全用于单进程
- `INSERT OR REPLACE` 自动处理 upsert，同一 `(game_hash, feature)` 更新而非报错
- `search(game_name="")` 空字符串返回全部，使用 `LIKE '%pattern%'`
- Schema 首次 open 时自动应用（`CREATE TABLE IF NOT EXISTS`）

### `src/cli/`

**子命令架构**：
```
build_parser()   → argparse.ArgumentParser
  ├── generate   --exe PATH --feature ID [--output DIR] [--no-cache]
  ├── list       [--game NAME]
  └── export     --id INT --format {ct,lua} [--output DIR]

cmd_list(store, game)               → stdout 表格
cmd_export(store, id, fmt, out_dir) → Path（写入文件）
main(argv)                          → int（退出码）
```

**cmd_export** 同时支持：
- `--format ct` → 调用 `CTBuilder.build()` 生成 `.ct` XML
- `--format lua` → 直接写出 `lua_script` 文本

**generate 子命令**目前输出 placeholder 消息（全管道接入将在后续迭代完成，不属于本周验收范围）。

---

## 测试变化

| 测试文件 | 之前 | 之后 | 新增 |
|---------|------|------|------|
| `test_detector.py` | 17 | 17 | — |
| `test_dumper_models.py` | 23 | 23 | — |
| `test_analyzer.py` | 47 | 47 | — |
| `test_resolver.py` | 46 | 46 | — |
| `test_ce_wrapper.py` | 29 | 29 | — |
| `test_store.py` | 0 | **16** | +16 |
| `test_cli.py` | 0 | **8** | +8 |
| **合计** | **162** | **186** | **+24** |

---

## 下一步 — Future：PyQt6 GUI

按 `PROJECT_PLAN.md` 第七节实现：

- 主窗口（`src/gui/main_window.py`）
- 四个页面：进程选择 / 功能配置 / 生成日志 / 脚本管理
- 技术选型：PyQt6（Windows 平台）
- 与 Store + CE Wrapper 集成

**当前已知技术债**（见 PROJECT_PLAN.md 第九节）：
- CE COM 接口完全未经 Windows 真实环境验证（High 优先级）
- IL2CPP 根 AOB 硬编码模板（Low）
- Unreal UE5 AOB 未经真实游戏验证（Medium）
