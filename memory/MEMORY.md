# ai-trainer-gen 项目记忆

## 项目简介
AI 驱动的单机游戏修改器（Trainer）自动生成系统，以 Cheat Engine 为执行内核。
支持 Unity Mono、Unity IL2CPP、Unreal Engine 4/5。

## 技术栈
- Python 3.12，setuptools, pyproject.toml
- LLM：Anthropic Claude API（首选）/ OpenAI（备选）/ stub（测试）
- Cheat Engine COM Automation（Windows）/ pymem 降级方案
- SQLite（ScriptStore）、PyQt6（GUI）、luaparser（验证）
- 测试：pytest，no real game needed (mocks + tmp dirs)

## 项目结构（src 模块）
```
src/
  exceptions.py          # 自定义异常层次（TrainerBaseError 根）
  detector/              # 引擎检测（纯静态，不需要游戏运行）
    engine_detector.py   # GameEngineDetector.detect()
    models.py            # EngineType, EngineInfo
  dumper/                # 结构导出
    base.py              # AbstractDumper + get_dumper() 工厂
    models.py            # FieldInfo, ClassInfo, StructureJSON
    unity_mono.py        # UnityMonoDumper（Phase 2，walk_assemblies 待实现）
    il2cpp.py            # IL2CPPDumper（调用 IL2CPPDumper.exe，解析 dummy .cs）
    ue.py                # UnrealDumper（解析 ObjectDump.txt，UE4SS 待 Phase 2）
  resolver/              # 字段访问策略解析
    base.py              # AbstractResolver
    models.py            # ResolutionStrategy, FieldResolution, EngineContext
    factory.py           # get_resolver(engine_type)
    mono_resolver.py     # MonoResolver（MONO_API 策略）
    il2cpp_resolver.py   # IL2CPPResolver（IL2CPP_PTR 策略）
    unreal_resolver.py   # UnrealResolver（UE_GOBJECTS 策略）
  analyzer/              # LLM 分析 + 脚本生成
    llm_analyzer.py      # LLMAnalyzer, LLMConfig（stub/anthropic/openai 后端）
    models.py            # FeatureType, AOBSignature, TrainerFeature, GeneratedScript
    validator.py         # ScriptValidator（引擎感知 AOB 校验）
    prompts/builder.py   # PromptBuilder（engine-aware 系统提示 + resolver preamble）
  ce_wrapper/            # CE 封装
    models.py            # CEProcess, InjectionResult, SandboxResult
    sandbox.py           # AOB 格式/命中数沙箱验证（不需要真实 CE）
    ct_builder.py        # .ct 文件生成器（XML）
  store/                 # SQLite 缓存
    models.py            # ScriptRecord
    db.py                # ScriptStore CRUD + search + invalidate
  cli/                   # 命令行入口
    main.py              # generate/list/export 子命令
  gui/                   # PyQt6 GUI（ViewModel 模式）
    viewmodels.py        # TrainerViewModel
    main_window.py       # 主窗口
    pages/               # process_select, feature_config, generate, script_manager
```

## 当前实现状态（2026-02-27）
- **已完成（有测试覆盖）**：detector、dumper models、resolver（3种策略全实现）、
  analyzer（LLMAnalyzer + PromptBuilder + ScriptValidator）、ce_wrapper（models/sandbox/ct_builder）、
  store（ScriptStore SQLite CRUD）、cli（generate/list/export）、gui（viewmodels + pages）
- **待完成（Phase 2）**：
  - UnityMonoDumper._walk_assemblies()（MVP 返回空列表，需 pymem 远程调用）
  - UnrealDumper：自动注入 UE4SS（当前需手动生成 ObjectDump.txt）
  - 完整 GUI（有 viewmodels 和 pages，尚无端到端流程连接）
- **测试状态**：213 个单元测试，全部通过（0.52s）

## 设计约束
- 不支持联机游戏/有服务端验证的游戏
- 不绕过反作弊（EAC、BattlEye 等）
- CE COM 接口仅 Windows；macOS/Linux 功能受限
- LLM 默认模型：anthropic → claude-3-5-sonnet-20241022（代码里），文档建议 claude-opus-4-5

## 代码规范
- 类型注解完整（Python 3.12）
- 每模块有 `__all__`
- 日志用 `logging`（不用 print）
- 异常用自定义类（不用裸 Exception）
- 格式化：`ruff format`；lint：`ruff check`
- 中文行内注释 + 英文 docstring

## 数据流
```
GameEngineDetector → EngineInfo
  → get_dumper() → AbstractDumper.dump() → StructureJSON
  → EngineContext.from_engine_info() + get_resolver().resolve() → FieldResolution[]
  → LLMAnalyzer.analyze(structure, feature, engine_context) → GeneratedScript
  → ScriptValidator.validate() → ScriptValidation
  → CTBuilder.build() → .ct XML 文件
  → ScriptStore.save() → SQLite cache
```
