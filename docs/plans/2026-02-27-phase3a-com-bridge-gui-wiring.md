# Phase 3A: CE COM Bridge + GUI Pipeline Wiring

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `ce_wrapper/com_bridge.py` (Windows CE COM automation with injectable mock for tests) and wire the GUI's Generate button to actually run the full pipeline in a background thread, routing logs and progress to `GeneratePage`.

**Architecture:** Four additive tasks, each independently committable. Task 1 adds the COM bridge (all-mock testing). Task 2 adds a `progress_cb` hook to `cmd_generate` (backward-compatible). Task 3 adds `GenerateWorker` (QObject that calls the pipeline in a QThread). Task 4 wires `MainWindow` to orchestrate Tasks 2–3 and adds `exe_path` to `ProcessInfo`.

**Tech Stack:** Python 3.12, PyQt6, `win32com.client` (mocked in tests via injectable factory), `QThread`, `pyqtSignal`, pytest with `QT_QPA_PLATFORM=offscreen`.

---

## Task 1: `ce_wrapper/com_bridge.py` — Windows CE COM Bridge

**Files:**
- Create: `src/ce_wrapper/com_bridge.py`
- Modify: `src/exceptions.py` (add `BridgeNotAvailableError`)
- Modify: `src/ce_wrapper/__init__.py` (export new symbols)
- Modify: `tests/unit/test_ce_wrapper.py` (add `TestCEBridge` class)

### What to build

`CEBridge` wraps the CE COM object (`Cheat Engine.Application`). On non-Windows it raises `BridgeNotAvailableError` immediately. For testability, the COM factory is an injectable callable — tests pass a lambda that returns a mock.

`BridgeNotAvailableError` is a new subclass of the existing `CEWrapperError` in `src/exceptions.py`.

### Step 1: Add `BridgeNotAvailableError` to `src/exceptions.py`

In `src/exceptions.py`, add after the existing `ScriptExecutionError` block (inside the `# ── CE Wrapper` section):

```python
class BridgeNotAvailableError(CEWrapperError):
    """Raised when the CE COM bridge is unavailable (non-Windows or CE not installed)."""
```

Also add `"BridgeNotAvailableError"` to the `__all__` list at the top of the file.

### Step 2: Write the failing tests

Add a new class `TestCEBridge` to `tests/unit/test_ce_wrapper.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# 4. CEBridge
# ─────────────────────────────────────────────────────────────────────────────

from unittest.mock import MagicMock, patch
from src.exceptions import BridgeNotAvailableError, BridgeError


class TestCEBridge:
    """CEBridge — thin COM wrapper, tested entirely via injectable mock factory."""

    def _make_app(self, *, pid=1234, name="Game.exe", scan_result=None):
        """Build a mock CE COM application object."""
        app = MagicMock()
        app.OpenedProcessID = pid
        app.OpenedProcessName = name
        app.AOBScan.return_value = scan_result or []
        return app

    def _make_bridge(self, app):
        """Return a CEBridge whose COM factory returns *app*."""
        from src.ce_wrapper.com_bridge import CEBridge
        return CEBridge(_com_factory=lambda: app)

    # ── connect ──────────────────────────────────────────────────────────

    def test_connect_returns_ce_process(self):
        """connect() reads pid and name from COM app and returns CEProcess."""
        app = self._make_app(pid=9999, name="MyGame.exe")
        bridge = self._make_bridge(app)

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", True):
            proc = bridge.connect()

        from src.ce_wrapper.models import CEProcess
        assert isinstance(proc, CEProcess)
        assert proc.pid == 9999
        assert proc.name == "MyGame.exe"

    def test_connect_raises_on_non_windows(self):
        """connect() raises BridgeNotAvailableError on non-Windows platforms."""
        from src.ce_wrapper.com_bridge import CEBridge
        bridge = CEBridge(_com_factory=lambda: MagicMock())

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", False):
            with pytest.raises(BridgeNotAvailableError):
                bridge.connect()

    # ── inject ───────────────────────────────────────────────────────────

    def test_inject_success(self):
        """inject() calls ExecuteScript and returns InjectionResult(success=True)."""
        app = self._make_app()
        bridge = self._make_bridge(app)

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", True):
            bridge.connect()

        script = _make_script(lua_code="writeFloat(0x1000, 9999)")
        from src.ce_wrapper.models import InjectionResult
        result = bridge.inject(script, MagicMock())

        assert isinstance(result, InjectionResult)
        assert result.success is True
        app.ExecuteScript.assert_called_once_with("writeFloat(0x1000, 9999)")

    def test_inject_failure_returns_result_not_raises(self):
        """If COM raises, inject() returns InjectionResult(success=False) without raising."""
        app = self._make_app()
        app.ExecuteScript.side_effect = RuntimeError("CE internal error")
        bridge = self._make_bridge(app)

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", True):
            bridge.connect()

        result = bridge.inject(_make_script(), MagicMock())
        assert result.success is False
        assert "CE internal error" in result.error

    def test_inject_raises_if_not_connected(self):
        """inject() raises BridgeError when called before connect()."""
        from src.ce_wrapper.com_bridge import CEBridge
        from src.exceptions import BridgeError
        bridge = CEBridge()
        with pytest.raises(BridgeError, match="Not connected"):
            bridge.inject(_make_script(), MagicMock())

    # ── validate_aob ─────────────────────────────────────────────────────

    def test_validate_aob_returns_hit_addresses(self):
        """validate_aob() returns the list of addresses from COM scan."""
        app = self._make_app(scan_result=[0xDEAD0000, 0xBEEF1234])
        bridge = self._make_bridge(app)

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", True):
            bridge.connect()

        hits = bridge.validate_aob(_make_aob("48 8B 05 ?? ?? ?? ??"), MagicMock())
        assert hits == [0xDEAD0000, 0xBEEF1234]

    def test_validate_aob_empty_on_no_hits(self):
        """validate_aob() returns [] when COM scan finds nothing."""
        app = self._make_app(scan_result=[])
        bridge = self._make_bridge(app)

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", True):
            bridge.connect()

        hits = bridge.validate_aob(_make_aob(), MagicMock())
        assert hits == []

    # ── context manager ──────────────────────────────────────────────────

    def test_context_manager_calls_close(self):
        """Using CEBridge as a context manager calls close() on exit."""
        from src.ce_wrapper.com_bridge import CEBridge
        app = self._make_app()
        bridge = CEBridge(_com_factory=lambda: app)

        with patch("src.ce_wrapper.com_bridge._IS_WINDOWS", True):
            with bridge as b:
                b.connect()
            assert bridge._app is None  # close() set it to None
```

### Step 3: Run tests to see them fail

```bash
cd /Users/paulgao/AI/Workspace/CC/brainstorm/ai-trainer-gen
python -m pytest tests/unit/test_ce_wrapper.py::TestCEBridge -v
```

Expected: 8 errors — `ImportError: cannot import name 'CEBridge' from 'src.ce_wrapper.com_bridge'`

### Step 4: Create `src/ce_wrapper/com_bridge.py`

```python
"""
CEBridge — thin wrapper around the Cheat Engine COM automation interface.

Design
──────
• All real COM calls are gated behind _IS_WINDOWS so the module is fully
  importable (and testable) on macOS/Linux.
• The _com_factory parameter is an injectable callable → pass a lambda in
  tests; leave as None in production to use the real win32com.client.

Raises
──────
BridgeNotAvailableError  — non-Windows platform, or pywin32 not installed
BridgeError              — CE COM operation failed after connect()
"""

import logging
import platform
from typing import Any, Callable, List, Optional

from src.analyzer.models import AOBSignature, GeneratedScript
from src.ce_wrapper.models import CEProcess, InjectionResult
from src.exceptions import BridgeError, BridgeNotAvailableError

__all__ = ["CEBridge"]

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"
_CE_PROG_ID = "Cheat Engine.Application"


class CEBridge:
    """
    Wraps Cheat Engine COM automation.

    Usage (production)::

        with CEBridge() as bridge:
            proc = bridge.connect()
            result = bridge.inject(script, proc)
            hits = bridge.validate_aob(aob, proc)

    Usage (tests)::

        fake_app = MagicMock()
        bridge = CEBridge(_com_factory=lambda: fake_app)
    """

    def __init__(
        self,
        _com_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._com_factory = _com_factory
        self._app: Optional[Any] = None

    # ── Public API ─────────────────────────────────────────────────────────

    def connect(self, ce_path: str = "") -> CEProcess:
        """
        Connect to a running CE instance and return the attached process.

        Args:
            ce_path: Unused — reserved for future path-based CE launch.

        Returns:
            CEProcess describing the process CE is currently attached to.

        Raises:
            BridgeNotAvailableError: Not running on Windows, or pywin32 missing.
        """
        if not _IS_WINDOWS:
            raise BridgeNotAvailableError(
                "CE COM bridge requires Windows. "
                "On other platforms, use CTBuilder for offline .ct export only."
            )
        factory = self._com_factory or self._default_com_factory
        self._app = factory()
        pid  = self._app.OpenedProcessID
        name = self._app.OpenedProcessName
        logger.info("CEBridge: connected to %s (pid=%s)", name, pid)
        return CEProcess(pid=pid, name=name)

    def inject(self, script: GeneratedScript, process: CEProcess) -> InjectionResult:
        """
        Execute *script*.lua_code inside CE and return the result.

        Returns InjectionResult(success=False, ...) on COM errors — never raises.
        Raises BridgeError if connect() was not called first.
        """
        if self._app is None:
            raise BridgeError("Not connected. Call connect() first.")
        try:
            self._app.ExecuteScript(script.lua_code)
            logger.info("CEBridge: injected feature '%s'", script.feature.name)
            return InjectionResult(success=True, feature_id=script.feature.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CEBridge: inject failed — %s", exc)
            return InjectionResult(
                success=False,
                feature_id=script.feature.name,
                error=str(exc),
            )

    def validate_aob(
        self,
        aob: AOBSignature,
        process: CEProcess,
    ) -> List[int]:
        """
        Scan process memory for *aob* and return matching addresses.

        Returns an empty list on COM errors or no hits — never raises.
        Raises BridgeError if connect() was not called first.
        """
        if self._app is None:
            raise BridgeError("Not connected. Call connect() first.")
        try:
            hits = self._app.AOBScan(aob.pattern) or []
            logger.debug("CEBridge: AOB '%s' → %d hits", aob.pattern, len(hits))
            return list(hits)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CEBridge: AOBScan failed — %s", exc)
            return []

    def close(self) -> None:
        """Release the COM reference."""
        self._app = None

    # ── Context manager ────────────────────────────────────────────────────

    def __enter__(self) -> "CEBridge":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Private ────────────────────────────────────────────────────────────

    def _default_com_factory(self) -> Any:
        try:
            import win32com.client  # type: ignore[import]
            return win32com.client.Dispatch(_CE_PROG_ID)
        except ImportError as exc:
            raise BridgeNotAvailableError(
                "pywin32 is not installed. Install with: pip install pywin32"
            ) from exc
```

Also add `BridgeError` and `BridgeNotAvailableError` to `src/exceptions.py` `__all__` and body (see Step 1).

Also update `src/ce_wrapper/__init__.py` to export `CEBridge`:
```python
from src.ce_wrapper.com_bridge import CEBridge
from src.ce_wrapper.ct_builder import CTBuilder
from src.ce_wrapper.sandbox import Sandbox, SandboxResult
from src.ce_wrapper.models import CEProcess, InjectionResult
```

### Step 5: Run tests to verify they pass

```bash
python -m pytest tests/unit/test_ce_wrapper.py::TestCEBridge -v
```

Expected: 8 passed.

### Step 6: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all previous tests + 8 new = passing.

### Step 7: Commit

```bash
git add src/ce_wrapper/com_bridge.py src/ce_wrapper/__init__.py src/exceptions.py tests/unit/test_ce_wrapper.py
git commit -m "feat(ce_wrapper): add CEBridge COM automation wrapper with injectable factory"
```

---

## Task 2: Add `progress_cb` to `cmd_generate`

**Files:**
- Modify: `src/cli/main.py` (add `progress_cb` optional parameter, call at each step)
- Modify: `tests/unit/test_cli.py` (add 3 tests to `TestGenerateCommand`)

### What to build

Add `progress_cb: Optional[Callable[[float, str], None]] = None` to `cmd_generate`. Call it at the start of each of the 8 labeled pipeline steps. This is 100% backward-compatible (existing callers with no keyword arg continue to work).

### Step 1: Write the failing tests

Add to `TestGenerateCommand` in `tests/unit/test_cli.py`:

```python
def test_progress_cb_called_at_each_step(self, fake_il2cpp_exe, fake_structure, fake_script, tmp_path):
    """progress_cb is invoked once per pipeline step with increasing pct."""
    store = ScriptStore(tmp_path / "s.db")
    calls: list[tuple[float, str]] = []

    with patch("src.cli.main.GameEngineDetector") as mock_det, \
         patch("src.cli.main.get_dumper") as mock_get_dumper, \
         patch("src.cli.main.get_resolver") as mock_res_f, \
         patch("src.cli.main.LLMAnalyzer") as mock_llm:
        mock_det.return_value.detect.return_value = _make_engine_info(str(fake_il2cpp_exe))
        mock_get_dumper.return_value.dump.return_value = fake_structure
        mock_res_f.return_value.resolve.return_value = []
        mock_llm.return_value.analyze.return_value = fake_script

        cmd_generate(
            exe_path=str(fake_il2cpp_exe),
            feature="infinite_health",
            output_dir=str(tmp_path),
            no_cache=False,
            store=store,
            progress_cb=lambda pct, msg: calls.append((pct, msg)),
        )

    # At least 3 calls: detect, dump, generate
    assert len(calls) >= 3
    percentages = [pct for pct, _ in calls]
    assert percentages == sorted(percentages), "progress should be non-decreasing"
    assert percentages[-1] == pytest.approx(1.0)

def test_progress_cb_none_does_not_raise(self, fake_il2cpp_exe, fake_structure, fake_script, tmp_path):
    """cmd_generate with progress_cb=None (default) runs without error."""
    store = ScriptStore(tmp_path / "s.db")

    with patch("src.cli.main.GameEngineDetector") as mock_det, \
         patch("src.cli.main.get_dumper") as mock_get_dumper, \
         patch("src.cli.main.get_resolver") as mock_res_f, \
         patch("src.cli.main.LLMAnalyzer") as mock_llm:
        mock_det.return_value.detect.return_value = _make_engine_info(str(fake_il2cpp_exe))
        mock_get_dumper.return_value.dump.return_value = fake_structure
        mock_res_f.return_value.resolve.return_value = []
        mock_llm.return_value.analyze.return_value = fake_script

        # No progress_cb → default None → no error
        result = cmd_generate(
            exe_path=str(fake_il2cpp_exe),
            feature="infinite_health",
            output_dir=str(tmp_path),
            no_cache=False,
            store=store,
        )
    assert result.suffix == ".lua"

def test_progress_cb_final_value_is_1(self, fake_il2cpp_exe, fake_structure, fake_script, tmp_path):
    """The last progress_cb call always has pct == 1.0."""
    store = ScriptStore(tmp_path / "s.db")
    last_pct: list[float] = []

    with patch("src.cli.main.GameEngineDetector") as mock_det, \
         patch("src.cli.main.get_dumper") as mock_get_dumper, \
         patch("src.cli.main.get_resolver") as mock_res_f, \
         patch("src.cli.main.LLMAnalyzer") as mock_llm:
        mock_det.return_value.detect.return_value = _make_engine_info(str(fake_il2cpp_exe))
        mock_get_dumper.return_value.dump.return_value = fake_structure
        mock_res_f.return_value.resolve.return_value = []
        mock_llm.return_value.analyze.return_value = fake_script

        cmd_generate(
            exe_path=str(fake_il2cpp_exe),
            feature="infinite_health",
            output_dir=str(tmp_path),
            no_cache=False,
            store=store,
            progress_cb=lambda pct, msg: last_pct.append(pct),
        )

    assert last_pct[-1] == pytest.approx(1.0)
```

You also need a helper `_make_engine_info` — add it near the top of `TestGenerateCommand`:

```python
def _make_engine_info(exe_path: str):
    """Build a minimal EngineInfo for test use."""
    from src.detector.models import EngineInfo, EngineType
    import os
    return EngineInfo(
        type=EngineType.UNITY_IL2CPP,
        version="2022.3",
        bitness=64,
        exe_path=exe_path,
        game_dir=os.path.dirname(exe_path),
    )
```

### Step 2: Run to confirm failure

```bash
python -m pytest tests/unit/test_cli.py::TestGenerateCommand::test_progress_cb_called_at_each_step -v
```

Expected: FAIL — `cmd_generate() got an unexpected keyword argument 'progress_cb'`

### Step 3: Modify `src/cli/main.py`

Add the parameter and emit calls. The 8 steps each get a `(fraction, label)` pair:

```
Step 1: Engine detection        → pct = 1/8 = 0.125
Step 2: Cache lookup            → pct = 2/8 = 0.25
Step 3: Structure dump          → pct = 4/8 = 0.50   (cache miss path only)
Step 4: Field resolution        → pct = 5/8 = 0.625
Step 5: Script generation       → pct = 7/8 = 0.875
Step 6: Cache save              → pct = 8/8 = 1.0
```

Change the function signature:

```python
def cmd_generate(
    exe_path: str,
    feature: str,
    output_dir: Optional[str],
    no_cache: bool,
    store: ScriptStore,
    backend: str = "stub",
    model: str = "",
    api_key: str = "",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Path:
```

Add `from typing import Callable` to the imports at the top of the file (it may already be there — check first).

Inside `cmd_generate`, add a helper before the first step:

```python
    def _report(pct: float, msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            progress_cb(pct, msg)
```

Then replace each `logger.info(...)` call at key steps with `_report(...)`:

```python
    # Step 1
    _report(0.125, f"Detecting engine for: {exe_path}")
    engine_info = GameEngineDetector().detect(exe_path)
    _report(0.25, f"Detected: {engine_info}")

    # ... cache lookup (no progress call needed — fast) ...

    # Step 2 (cache hit path)
    if not no_cache:
        cached = store.get(game_hash, feature)
        if cached:
            _report(1.0, f"Cache hit: {game_name} / {feature}")
            return _write_output(cached.lua_script, game_name, feature, output_dir)

    # Step 3
    _report(0.375, f"Dumping structure via {type(get_dumper(engine_info)).__name__}")
    dumper = get_dumper(engine_info)
    structure = dumper.dump(engine_info)

    # Step 4
    _report(0.5, "Resolving field accesses")
    context = EngineContext.from_engine_info(engine_info)
    resolver = get_resolver(engine_info.type.value)
    resolutions = resolver.resolve(structure, context)
    context.resolutions = resolutions

    # Step 5
    _report(0.75, f"Generating script for feature '{feature}'")
    trainer_feature = TrainerFeature(name=feature, feature_type=_parse_feature_type(feature))
    config = LLMConfig(backend=backend, model=model, api_key=api_key)
    script = LLMAnalyzer(config).analyze(structure, trainer_feature, context)

    # Step 6
    _report(0.875, "Persisting to cache")
    # ... aob_json + store.save(record) ...

    _report(1.0, f"Script written to {out_path}")
    return out_path
```

### Step 4: Run tests

```bash
python -m pytest tests/unit/test_cli.py -v
```

Expected: all existing tests + 3 new = all pass.

### Step 5: Run full suite

```bash
python -m pytest tests/ -q
```

### Step 6: Commit

```bash
git add src/cli/main.py tests/unit/test_cli.py
git commit -m "feat(cli): add progress_cb hook to cmd_generate for GUI progress reporting"
```

---

## Task 3: `gui/worker.py` — GenerateWorker QObject

**Files:**
- Create: `src/gui/worker.py`
- Modify: `tests/unit/test_gui_widgets.py` (add `TestGenerateWorker` class)

### What to build

`GenerateWorker` is a `QObject` (not a `QThread` subclass — this is the correct Qt pattern). It is moved to a `QThread` by the caller. Its `run()` slot calls `cmd_generate()` with a `progress_cb` that emits Qt signals. On success it emits `finished(lua_path: str)`; on error it emits `failed(error: str)`.

### Step 1: Write the failing tests

Add to `tests/unit/test_gui_widgets.py`:

```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ... existing imports ...

from unittest.mock import patch, MagicMock


class TestGenerateWorker:
    """GenerateWorker — runs cmd_generate in a QThread, emits signals."""

    @pytest.fixture(autouse=True)
    def qt_app(self, qapp):
        """Ensure QApplication exists (pytest-qt fixture)."""
        return qapp

    def _make_worker(self, exe_path="/game/Game.exe", features=None, backend="stub"):
        from src.gui.worker import GenerateWorker
        from src.store.db import ScriptStore
        import tempfile, os
        store = ScriptStore(os.path.join(tempfile.mkdtemp(), "test.db"))
        return GenerateWorker(
            exe_path=exe_path,
            features=features or ["infinite_health"],
            store=store,
            backend=backend,
        )

    def test_worker_emits_finished_on_success(self, tmp_path):
        """On successful cmd_generate, worker emits finished(lua_path)."""
        worker = self._make_worker()
        results = []
        worker.finished.connect(lambda p: results.append(p))

        with patch("src.gui.worker.cmd_generate", return_value=tmp_path / "out.lua"):
            worker.run()

        assert len(results) == 1
        assert results[0].endswith(".lua")

    def test_worker_emits_failed_on_exception(self):
        """When cmd_generate raises, worker emits failed(error_msg)."""
        worker = self._make_worker()
        errors = []
        worker.failed.connect(lambda e: errors.append(e))

        with patch("src.gui.worker.cmd_generate", side_effect=RuntimeError("boom")):
            worker.run()

        assert len(errors) == 1
        assert "boom" in errors[0]

    def test_worker_emits_progress_updates(self, tmp_path):
        """progress_cb passed to cmd_generate causes progress_updated signals."""
        worker = self._make_worker()
        progress_values = []
        worker.progress_updated.connect(lambda v: progress_values.append(v))

        def fake_generate(*args, **kwargs):
            cb = kwargs.get("progress_cb")
            if cb:
                cb(0.25, "step A")
                cb(1.0,  "done")
            return tmp_path / "out.lua"

        with patch("src.gui.worker.cmd_generate", side_effect=fake_generate):
            worker.run()

        assert 0.25 in progress_values
        assert 1.0  in progress_values

    def test_worker_emits_log_for_progress_cb(self, tmp_path):
        """progress_cb messages are forwarded as log_emitted signals."""
        worker = self._make_worker()
        log_lines = []
        worker.log_emitted.connect(lambda m: log_lines.append(m))

        def fake_generate(*args, **kwargs):
            cb = kwargs.get("progress_cb")
            if cb:
                cb(0.5, "halfway there")
            return tmp_path / "out.lua"

        with patch("src.gui.worker.cmd_generate", side_effect=fake_generate):
            worker.run()

        assert any("halfway there" in line for line in log_lines)
```

### Step 2: Run to confirm failure

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_gui_widgets.py::TestGenerateWorker -v
```

Expected: 4 errors — `ModuleNotFoundError: No module named 'src.gui.worker'`

### Step 3: Create `src/gui/worker.py`

```python
"""
GenerateWorker — runs the full ai-trainer-gen pipeline in a background thread.

Usage (MainWindow)::

    self._thread = QThread()
    self._worker = GenerateWorker(exe_path, features, store)
    self._worker.moveToThread(self._thread)
    self._thread.started.connect(self._worker.run)
    self._worker.finished.connect(self._thread.quit)
    self._worker.failed.connect(self._thread.quit)
    self._worker.log_emitted.connect(self._page_generate.append_log)
    self._worker.progress_updated.connect(self._page_generate.set_progress)
    self._thread.start()

Signals
───────
log_emitted(str)       — one log line, including step label
progress_updated(float)— 0.0 – 1.0, emitted at each pipeline step
finished(str)          — absolute path to the written .lua file
failed(str)            — human-readable error message
"""

import logging
from typing import List

from PyQt6.QtCore import QObject, pyqtSignal

from src.cli.main import cmd_generate

__all__ = ["GenerateWorker"]

logger = logging.getLogger(__name__)


class GenerateWorker(QObject):
    """
    Wraps cmd_generate for execution in a QThread.

    All interaction with the GUI must go through signals — never touch
    Qt widgets from inside run().
    """

    log_emitted      = pyqtSignal(str)    # one log line per pipeline step
    progress_updated = pyqtSignal(float)  # 0.0 – 1.0
    finished         = pyqtSignal(str)    # path to written .lua file
    failed           = pyqtSignal(str)    # error message

    def __init__(
        self,
        exe_path: str,
        features: List[str],
        store,
        backend: str = "stub",
        model:   str = "",
        api_key: str = "",
    ) -> None:
        super().__init__()
        self._exe_path = exe_path
        self._features = features
        self._store    = store
        self._backend  = backend
        self._model    = model
        self._api_key  = api_key

    # ── Slot ───────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Entry point — connect QThread.started to this slot."""
        feature = ", ".join(self._features) if self._features else "general"

        def on_progress(pct: float, msg: str) -> None:
            self.log_emitted.emit(f"[{int(pct * 100):3d}%] {msg}")
            self.progress_updated.emit(pct)

        try:
            out_path = cmd_generate(
                exe_path=self._exe_path,
                feature=feature,
                output_dir=None,
                no_cache=False,
                store=self._store,
                backend=self._backend,
                model=self._model,
                api_key=self._api_key,
                progress_cb=on_progress,
            )
            self.finished.emit(str(out_path))
        except Exception as exc:  # noqa: BLE001
            logger.exception("GenerateWorker.run() failed")
            self.failed.emit(str(exc))
```

### Step 4: Run tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_gui_widgets.py::TestGenerateWorker -v
```

Expected: 4 passed.

### Step 5: Run full suite

```bash
python -m pytest tests/ -q
```

### Step 6: Commit

```bash
git add src/gui/worker.py tests/unit/test_gui_widgets.py
git commit -m "feat(gui): add GenerateWorker QObject — runs pipeline in QThread with progress signals"
```

---

## Task 4: Wire MainWindow — Connect GUI to Pipeline

**Files:**
- Modify: `src/gui/viewmodels.py` (add `exe_path: str = ""` to `ProcessInfo`)
- Modify: `src/gui/pages/process_select.py` (populate `exe_path` via psutil when available)
- Modify: `src/gui/main_window.py` (add `_store`, wire `_on_generate_clicked`, handle worker signals)
- Modify: `tests/unit/test_gui_widgets.py` (add `TestMainWindowWiring` class)

### What to build

1. `ProcessInfo` gets an `exe_path` field so `MainWindow` can pass the exe path to the worker.
2. `ProcessSelectPage._refresh()` populates `exe_path` from psutil if available (guarded by try/except).
3. `MainWindow` holds a shared `ScriptStore`, creates a `QThread + GenerateWorker` on every Generate click, connects signals to `GeneratePage` and navigation.

### Step 1: Add `exe_path` to `ProcessInfo`

In `src/gui/viewmodels.py`, find the `ProcessInfo` dataclass and add the field:

```python
@dataclass
class ProcessInfo:
    """Lightweight descriptor for a running OS process."""
    pid:      int
    name:     str
    exe_path: str = ""   # ← ADD THIS

    def __str__(self) -> str:
        return f"{self.name} (pid={self.pid})"
```

### Step 2: Write the failing tests

Add to `tests/unit/test_gui_widgets.py`:

```python
class TestMainWindowWiring:
    """MainWindow — Generate button launches worker, signals route to pages."""

    @pytest.fixture(autouse=True)
    def qt_app(self, qapp):
        return qapp

    def _make_window(self, tmp_path):
        from src.gui.main_window import MainWindow
        win = MainWindow()
        win._store._db_path = str(tmp_path / "test.db")  # redirect to temp
        return win

    def test_generate_navigates_to_generate_page(self, tmp_path, qtbot):
        """Clicking Generate button navigates to GeneratePage (index 2)."""
        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        # Pre-select a fake process so exe_path is not empty
        from src.gui.viewmodels import ProcessInfo
        win._page_process._vm.selected = ProcessInfo(pid=1, name="Game.exe", exe_path="/fake/Game.exe")
        win._page_features._vm.toggle("infinite_health")

        with patch("src.gui.main_window.GenerateWorker") as MockWorker:
            mock_w = MagicMock()
            MockWorker.return_value = mock_w
            mock_w.finished = MagicMock()
            mock_w.failed   = MagicMock()
            mock_w.log_emitted     = MagicMock()
            mock_w.progress_updated = MagicMock()

            win._page_features._generate_btn.click()

        assert win._stack.currentIndex() == 2  # PAGE_GENERATE

    def test_generate_resets_generate_page(self, tmp_path, qtbot):
        """Clicking Generate calls reset() on GeneratePage before starting."""
        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        from src.gui.viewmodels import ProcessInfo
        win._page_process._vm.selected = ProcessInfo(pid=1, name="Game.exe", exe_path="/fake/Game.exe")

        with patch("src.gui.main_window.GenerateWorker") as MockWorker:
            mock_w = MagicMock()
            MockWorker.return_value = mock_w
            for sig in ("finished", "failed", "log_emitted", "progress_updated"):
                setattr(mock_w, sig, MagicMock())

            win._page_generate._log_view.appendPlainText("old log")  # dirty state
            win._page_features._generate_btn.click()

        assert win._page_generate._log_view.toPlainText() == ""  # was reset

    def test_worker_finished_navigates_to_script_manager(self, tmp_path, qtbot):
        """On worker finished signal, MainWindow navigates to ScriptManagerPage (index 3)."""
        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        from src.gui.viewmodels import ProcessInfo
        win._page_process._vm.selected = ProcessInfo(pid=1, name="Game.exe", exe_path="/fake/Game.exe")

        captured_worker = []

        def capture(exe, features, store, **kw):
            w = MagicMock()
            for sig in ("finished", "failed", "log_emitted", "progress_updated"):
                setattr(w, sig, MagicMock())
            captured_worker.append(w)
            return w

        with patch("src.gui.main_window.GenerateWorker", side_effect=capture):
            win._page_features._generate_btn.click()

        # Simulate the worker emitting finished
        win._on_generate_finished("/output/Game_infinite_health.lua")
        assert win._stack.currentIndex() == 3  # PAGE_SCRIPT_MANAGER

    def test_worker_failed_stays_on_generate_page(self, tmp_path, qtbot):
        """On worker failed signal, MainWindow stays on GeneratePage (index 2)."""
        win = self._make_window(tmp_path)
        qtbot.addWidget(win)

        from src.gui.viewmodels import ProcessInfo
        win._page_process._vm.selected = ProcessInfo(pid=1, name="Game.exe", exe_path="/fake/Game.exe")

        with patch("src.gui.main_window.GenerateWorker") as MockWorker:
            mock_w = MagicMock()
            for sig in ("finished", "failed", "log_emitted", "progress_updated"):
                setattr(mock_w, sig, MagicMock())
            MockWorker.return_value = mock_w
            win._page_features._generate_btn.click()

        win._on_generate_failed("Engine detection failed: file not found")
        assert win._stack.currentIndex() == 2  # still on GeneratePage
```

### Step 3: Run to confirm failure

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_gui_widgets.py::TestMainWindowWiring -v
```

Expected: failures — `MainWindow has no attribute '_store'`, `_on_generate_finished` not defined, etc.

### Step 4: Modify `src/gui/main_window.py`

Full rewrite of the wiring section (keep UI construction the same):

```python
"""
MainWindow — top-level application window for ai-trainer-gen GUI.
...
"""

import logging
import tempfile
import os

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QMainWindow, QStackedWidget, QWidget

from src.gui.pages.process_select import ProcessSelectPage
from src.gui.pages.feature_config  import FeatureConfigPage
from src.gui.pages.generate        import GeneratePage
from src.gui.pages.script_manager  import ScriptManagerPage
from src.gui.worker                import GenerateWorker
from src.store.db                  import ScriptStore

__all__ = ["MainWindow"]

logger = logging.getLogger(__name__)

PAGE_PROCESS_SELECT = 0
PAGE_FEATURE_CONFIG = 1
PAGE_GENERATE       = 2
PAGE_SCRIPT_MANAGER = 3


class MainWindow(QMainWindow):
    """Root window: hosts the QStackedWidget and wires page navigation."""

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Trainer Generator")
        self.resize(640, 480)

        # Shared script store — persisted to a temp dir by default;
        # tests can override _store._db_path after construction.
        _db_path = os.path.join(tempfile.gettempdir(), "ai_trainer_gen.db")
        self._store = ScriptStore(_db_path)

        # Worker / thread references kept on self to prevent GC during run
        self._thread: QThread | None = None
        self._worker: GenerateWorker | None = None

        self._build_ui()
        self._connect_navigation()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._page_process  = ProcessSelectPage()
        self._page_features = FeatureConfigPage()
        self._page_generate = GeneratePage()
        self._page_scripts  = ScriptManagerPage()

        self._stack.addWidget(self._page_process)   # 0
        self._stack.addWidget(self._page_features)  # 1
        self._stack.addWidget(self._page_generate)  # 2
        self._stack.addWidget(self._page_scripts)   # 3

        self._stack.setCurrentIndex(PAGE_PROCESS_SELECT)

    # ── Navigation wiring ──────────────────────────────────────────────────

    def _connect_navigation(self) -> None:
        # ProcessSelectPage → FeatureConfigPage
        self._page_process._select_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

        # FeatureConfigPage → GeneratePage (triggers pipeline)
        self._page_features._generate_btn.clicked.connect(
            self._on_generate_clicked
        )

        # GeneratePage ← back to FeatureConfigPage
        self._page_generate._back_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

        # ScriptManagerPage ← back to FeatureConfigPage
        self._page_scripts._back_btn.clicked.connect(
            lambda: self.go_to(PAGE_FEATURE_CONFIG)
        )

    # ── Generate pipeline orchestration ───────────────────────────────────

    def _on_generate_clicked(self) -> None:
        """Navigate to GeneratePage and launch the generation worker."""
        # Collect exe path from selected process
        proc    = self._page_process._vm.selected
        exe_path = proc.exe_path if proc else ""

        # Collect features
        features = list(self._page_features._vm.selected_features)
        custom   = self._page_features._vm.custom_description.strip()
        if custom:
            features.append(custom)

        # Navigate and reset the page
        self.go_to(PAGE_GENERATE)
        self._page_generate.reset()

        # Create worker and thread
        self._worker = GenerateWorker(
            exe_path=exe_path,
            features=features,
            store=self._store,
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        # Wire signals
        self._thread.started.connect(self._worker.run)
        self._worker.log_emitted.connect(self._page_generate.append_log)
        self._worker.progress_updated.connect(self._page_generate.set_progress)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.failed.connect(self._on_generate_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)

        self._thread.start()

    def _on_generate_finished(self, lua_path: str) -> None:
        """Called when the worker emits finished(lua_path)."""
        self._page_generate.append_log(f"✓ Script saved: {lua_path}")
        self._page_generate.set_progress(1.0)
        self.go_to(PAGE_SCRIPT_MANAGER)

    def _on_generate_failed(self, error: str) -> None:
        """Called when the worker emits failed(error)."""
        self._page_generate.append_log(f"✗ Error: {error}")
        # Stay on GeneratePage so user can read the error

    # ── Public API ─────────────────────────────────────────────────────────

    def go_to(self, page_index: int) -> None:
        """Switch the visible page to *page_index*."""
        self._stack.setCurrentIndex(page_index)
```

### Step 5: Update `ProcessSelectPage._on_refresh` to populate `exe_path`

In `src/gui/pages/process_select.py`, find the `_on_refresh` method and update the psutil scan to populate `exe_path`:

```python
def _on_refresh(self) -> None:
    """Refresh the process list using psutil if available."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = p.info
                procs.append(ProcessInfo(
                    pid=info["pid"],
                    name=info["name"] or "",
                    exe_path=info.get("exe") or "",
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        self._vm.set_processes(procs)
    except ImportError:
        # psutil not available — show placeholder entries
        from src.gui.viewmodels import ProcessInfo
        self._vm.set_processes([
            ProcessInfo(pid=0, name="(psutil not installed)", exe_path=""),
        ])
    self._refresh_list()
```

### Step 6: Run tests

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/unit/test_gui_widgets.py::TestMainWindowWiring -v
```

Expected: 4 passed.

### Step 7: Run full suite

```bash
python -m pytest tests/ -q
```

Expected: all tests pass (target ≥ 255 total).

### Step 8: Commit

```bash
git add src/gui/viewmodels.py src/gui/main_window.py src/gui/pages/process_select.py tests/unit/test_gui_widgets.py
git commit -m "feat(gui): wire Generate button to pipeline via GenerateWorker + QThread"
```

---

## Summary

| Task | New file / key change | Tests added |
|------|----------------------|-------------|
| 1. CEBridge | `src/ce_wrapper/com_bridge.py` | +8 |
| 2. progress_cb | `src/cli/main.py` (optional param + calls) | +3 |
| 3. GenerateWorker | `src/gui/worker.py` | +4 |
| 4. MainWindow wiring | `src/gui/main_window.py` + viewmodels + process page | +4 |

**Total new tests: ~19 → suite grows from 236 → ~255**

After all 4 tasks, `python -m ai_trainer_gen generate --exe <path> --feature infinite_health` and the GUI Generate button both produce a real `.lua` file and CE can receive it via `CEBridge.inject()`.
