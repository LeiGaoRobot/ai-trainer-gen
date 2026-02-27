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
log_emitted(str)       — one log line per pipeline step
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

    def run(self) -> None:
        """Entry point — connect QThread.started to this slot."""
        # Multiple selected features are joined into one request string;
        # cmd_generate's LLM will treat it as a combined custom feature.
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
