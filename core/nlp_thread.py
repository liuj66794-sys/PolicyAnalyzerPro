from __future__ import annotations

import multiprocessing as mp
import queue
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.algorithms import PolicyReportAnalyzer, initialize_runtime_environment
from core.config import AppConfig, DEFAULT_CONFIG

ANALYSIS_MODE_SINGLE = "single"
ANALYSIS_MODE_COMPARE = "compare"
ANALYSIS_MODE_BATCH = "batch"

_WORKER_CONFIG: AppConfig | None = None
_WORKER_ANALYZER: PolicyReportAnalyzer | None = None


def _build_runtime_config(config_data: dict[str, Any] | None) -> AppConfig:
    config = DEFAULT_CONFIG.merge(config_data or {})
    config.process_pool_workers = 1
    config.torch_num_threads = 2
    config.local_files_only = True
    config.offline_env["HF_HUB_OFFLINE"] = "1"
    config.offline_env["TRANSFORMERS_OFFLINE"] = "1"
    return config


def _worker_initializer(config_data: dict[str, Any] | None) -> None:
    global _WORKER_ANALYZER, _WORKER_CONFIG

    _WORKER_CONFIG = _build_runtime_config(config_data)
    _WORKER_ANALYZER = None
    initialize_runtime_environment(_WORKER_CONFIG)


def _get_worker_analyzer() -> PolicyReportAnalyzer:
    global _WORKER_ANALYZER

    if _WORKER_ANALYZER is None:
        _WORKER_ANALYZER = PolicyReportAnalyzer(_WORKER_CONFIG or DEFAULT_CONFIG)
    return _WORKER_ANALYZER


def _push_progress(progress_queue: Any, percent: int, message: str) -> None:
    if progress_queue is None:
        return
    progress_queue.put(
        {
            "percent": int(percent),
            "message": str(message),
        }
    )


def _run_single_analysis(text: str, progress_queue: Any) -> dict[str, Any]:
    initialize_runtime_environment(_WORKER_CONFIG or DEFAULT_CONFIG)
    analyzer = _get_worker_analyzer()
    return analyzer.analyze_single_report(
        text,
        progress_callback=lambda percent, message: _push_progress(
            progress_queue,
            percent,
            message,
        ),
    )


def _run_compare_analysis(
    old_text: str,
    new_text: str,
    progress_queue: Any,
) -> dict[str, Any]:
    initialize_runtime_environment(_WORKER_CONFIG or DEFAULT_CONFIG)
    analyzer = _get_worker_analyzer()
    return analyzer.compare_reports(
        old_text,
        new_text,
        progress_callback=lambda percent, message: _push_progress(
            progress_queue,
            percent,
            message,
        ),
    )


def _run_batch_analysis(
    batch_inputs: list[dict[str, Any]],
    progress_queue: Any,
) -> dict[str, Any]:
    initialize_runtime_environment(_WORKER_CONFIG or DEFAULT_CONFIG)
    analyzer = _get_worker_analyzer()
    return analyzer.analyze_batch_reports(
        batch_inputs,
        progress_callback=lambda percent, message: _push_progress(
            progress_queue,
            percent,
            message,
        ),
    )


class NLPAnalysisThread(QThread):
    progress_changed = Signal(int, str)
    result_ready = Signal(object)
    error_occurred = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self,
        mode: str,
        primary_text: str,
        secondary_text: str = "",
        config: AppConfig | None = None,
        parent: Any | None = None,
        batch_inputs: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.primary_text = primary_text or ""
        self.secondary_text = secondary_text or ""
        self.config = _build_runtime_config((config or DEFAULT_CONFIG).to_dict())
        self.batch_inputs = [dict(item) for item in (batch_inputs or [])]
        self._cancel_requested = False
        self._last_progress = -1

    def request_cancel(self) -> None:
        """
        Best-effort cancellation. Running transformer work cannot be force-killed
        safely here, but queued jobs can still be cancelled before they start.
        """
        self._cancel_requested = True

    def run(self) -> None:
        if self.mode == ANALYSIS_MODE_BATCH:
            if not self.batch_inputs:
                self.error_occurred.emit("批量分析至少需要一份有效文本。")
                return
        else:
            if not self.primary_text.strip():
                self.error_occurred.emit("请输入待分析文本。")
                return

            if self.mode == ANALYSIS_MODE_COMPARE and not self.secondary_text.strip():
                self.error_occurred.emit("双篇比对需要同时提供旧稿和新稿。")
                return

        if self.mode not in {ANALYSIS_MODE_SINGLE, ANALYSIS_MODE_COMPARE, ANALYSIS_MODE_BATCH}:
            self.error_occurred.emit(f"不支持的分析模式：{self.mode}")
            return

        context = mp.get_context("spawn")
        manager = None
        executor = None
        future = None

        try:
            self.status_changed.emit("\u6b63\u5728\u521d\u59cb\u5316\u79bb\u7ebf\u5206\u6790\u5f15\u64ce")
            manager = context.Manager()
            progress_queue = manager.Queue()

            executor = ProcessPoolExecutor(
                max_workers=1,
                mp_context=context,
                initializer=_worker_initializer,
                initargs=(self.config.to_dict(),),
            )

            if self.mode == ANALYSIS_MODE_SINGLE:
                future = executor.submit(
                    _run_single_analysis,
                    self.primary_text,
                    progress_queue,
                )
            elif self.mode == ANALYSIS_MODE_COMPARE:
                future = executor.submit(
                    _run_compare_analysis,
                    self.primary_text,
                    self.secondary_text,
                    progress_queue,
                )
            else:
                future = executor.submit(
                    _run_batch_analysis,
                    self.batch_inputs,
                    progress_queue,
                )

            self.status_changed.emit("\u5206\u6790\u4efb\u52a1\u5df2\u63d0\u4ea4\u5230\u540e\u53f0\u5b50\u8fdb\u7a0b")

            while True:
                self._drain_progress_queue(progress_queue)
                if future.done():
                    break

                if self._cancel_requested:
                    if future.cancel():
                        self.status_changed.emit("\u5206\u6790\u4efb\u52a1\u5df2\u53d6\u6d88")
                        return
                    self.status_changed.emit("\u4efb\u52a1\u5df2\u5f00\u59cb\u6267\u884c\uff0c\u7b49\u5f85\u5f53\u524d\u6b65\u9aa4\u5b89\u5168\u7ed3\u675f")
                    self._cancel_requested = False

                self.msleep(80)

            self._drain_progress_queue(progress_queue)
            result = future.result()
            self.result_ready.emit(result)
            self.status_changed.emit("\u5206\u6790\u4efb\u52a1\u5b8c\u6210")
        except Exception as exc:
            self.error_occurred.emit(f"\u5206\u6790\u4efb\u52a1\u5931\u8d25\uff1a{exc}")
            self.status_changed.emit("\u5206\u6790\u4efb\u52a1\u5b8c\u6210")
        finally:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            if manager is not None:
                manager.shutdown()

    def _drain_progress_queue(self, progress_queue: Any) -> None:
        while True:
            try:
                item = progress_queue.get_nowait()
            except queue.Empty:
                break
            except (EOFError, OSError):
                break

            percent = int(item.get("percent", 0))
            message = str(item.get("message", ""))
            if percent == self._last_progress and not message:
                continue

            self._last_progress = percent
            self.progress_changed.emit(percent, message)
