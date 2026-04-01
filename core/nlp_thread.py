﻿from __future__ import annotations

import multiprocessing as mp
import queue
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.algorithms import PolicyReportAnalyzer, initialize_runtime_environment
from core.analysis_errors import AnalysisExecutionError, build_analysis_error_status_text, coerce_analysis_error_info
from core.analysis_router import (
    ANALYSIS_MODE_HYBRID,
    ANALYSIS_MODE_OFFLINE,
    ANALYSIS_MODE_ONLINE,
    apply_route_metadata,
    normalize_analysis_mode,
    resolve_analysis_route,
)
from core.config import AppConfig, DEFAULT_CONFIG
from core.hybrid_pipeline import HybridPipelineService
from core.online_llm import OnlineLLMService

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

    try:
        analyzer = PolicyReportAnalyzer(_WORKER_CONFIG)
        analyzer._ensure_jieba_ready()
        analyzer._load_embedding_model()
    except Exception:
        pass


def _get_worker_analyzer() -> PolicyReportAnalyzer:
    global _WORKER_ANALYZER

    if _WORKER_ANALYZER is None:
        _WORKER_ANALYZER = PolicyReportAnalyzer(_WORKER_CONFIG or DEFAULT_CONFIG)
    return _WORKER_ANALYZER


def _push_progress(progress_queue: Any, percent: int, message: str) -> None:
    if progress_queue is None:
        return
    progress_queue.put({"percent": int(percent), "message": str(message)})


def _run_single_analysis(text: str, progress_queue: Any) -> dict[str, Any]:
    initialize_runtime_environment(_WORKER_CONFIG or DEFAULT_CONFIG)
    analyzer = _get_worker_analyzer()
    return analyzer.analyze_single_report(
        text,
        progress_callback=lambda percent, message: _push_progress(progress_queue, percent, message),
    )


def _run_compare_analysis(old_text: str, new_text: str, progress_queue: Any) -> dict[str, Any]:
    initialize_runtime_environment(_WORKER_CONFIG or DEFAULT_CONFIG)
    analyzer = _get_worker_analyzer()
    return analyzer.compare_reports(
        old_text,
        new_text,
        progress_callback=lambda percent, message: _push_progress(progress_queue, percent, message),
    )


def _run_batch_analysis(batch_inputs: list[dict[str, Any]], progress_queue: Any) -> dict[str, Any]:
    initialize_runtime_environment(_WORKER_CONFIG or DEFAULT_CONFIG)
    analyzer = _get_worker_analyzer()
    return analyzer.analyze_batch_reports(
        batch_inputs,
        progress_callback=lambda percent, message: _push_progress(progress_queue, percent, message),
    )


def _run_online_analysis(
    task_mode: str,
    primary_text: str,
    secondary_text: str,
    batch_inputs: list[dict[str, Any]],
    progress_queue: Any,
    config_data: dict[str, Any] | None,
) -> dict[str, Any]:
    config = _build_runtime_config(config_data)
    initialize_runtime_environment(config)
    _push_progress(progress_queue, 10, "正在检查在线分析能力")
    service = OnlineLLMService(config)
    if task_mode == ANALYSIS_MODE_SINGLE:
        response = service.analyze_single(primary_text)
    elif task_mode == ANALYSIS_MODE_COMPARE:
        response = service.analyze_compare(primary_text, secondary_text)
    else:
        response = service.analyze_batch(batch_inputs)
    return {
        "mode": task_mode,
        "summary_overview": {"headline": "在线分析已完成。"},
        "online_response": response.content,
    }


def _run_hybrid_analysis(
    task_mode: str,
    primary_text: str,
    secondary_text: str,
    batch_inputs: list[dict[str, Any]],
    progress_queue: Any,
    config_data: dict[str, Any] | None,
) -> dict[str, Any]:
    config = _build_runtime_config(config_data)
    initialize_runtime_environment(config)
    _push_progress(progress_queue, 10, "正在检查混合分析能力")
    service = HybridPipelineService(config)
    if task_mode == ANALYSIS_MODE_SINGLE:
        result = service.run_single(primary_text)
    elif task_mode == ANALYSIS_MODE_COMPARE:
        result = service.run_compare(primary_text, secondary_text)
    else:
        result = service.run_batch(batch_inputs)
    return {
        "mode": task_mode,
        "summary_overview": {"headline": "混合分析已完成。"},
        "hybrid_result": {
            "local_result": result.local_result,
            "online_result": result.online_result,
            "warnings": result.warnings,
        },
    }


class NLPAnalysisThread(QThread):
    progress_changed = Signal(int, str)
    result_ready = Signal(object)
    error_occurred = Signal(object)
    status_changed = Signal(str)

    def __init__(
        self,
        mode: str,
        primary_text: str,
        secondary_text: str = "",
        config: AppConfig | None = None,
        parent: Any | None = None,
        batch_inputs: list[dict[str, Any]] | None = None,
        analysis_mode: str = ANALYSIS_MODE_OFFLINE,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.primary_text = primary_text or ""
        self.secondary_text = secondary_text or ""
        self.config = _build_runtime_config((config or DEFAULT_CONFIG).to_dict())
        self.batch_inputs = [dict(item) for item in (batch_inputs or [])]
        self.analysis_mode = analysis_mode or self.config.analysis_mode
        self._cancel_requested = False
        self._last_progress = -1

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        requested_mode = normalize_analysis_mode(self.analysis_mode or self.config.analysis_mode)

        if self.mode == ANALYSIS_MODE_BATCH:
            if not self.batch_inputs:
                self._emit_analysis_error(
                    AnalysisExecutionError(
                        mode=requested_mode,
                        stage="validation",
                        category="input",
                        user_message="批量分析至少需要一份有效文本。",
                    ),
                    requested_mode=requested_mode,
                    executed_mode=requested_mode,
                    stage="validation",
                )
                return
        else:
            if not self.primary_text.strip():
                self._emit_analysis_error(
                    AnalysisExecutionError(
                        mode=requested_mode,
                        stage="validation",
                        category="input",
                        user_message="请输入待分析文本。",
                    ),
                    requested_mode=requested_mode,
                    executed_mode=requested_mode,
                    stage="validation",
                )
                return
            if self.mode == ANALYSIS_MODE_COMPARE and not self.secondary_text.strip():
                self._emit_analysis_error(
                    AnalysisExecutionError(
                        mode=requested_mode,
                        stage="validation",
                        category="input",
                        user_message="双篇比对需要同时提供旧稿和新稿。",
                    ),
                    requested_mode=requested_mode,
                    executed_mode=requested_mode,
                    stage="validation",
                )
                return

        if self.mode not in {ANALYSIS_MODE_SINGLE, ANALYSIS_MODE_COMPARE, ANALYSIS_MODE_BATCH}:
            self._emit_analysis_error(
                AnalysisExecutionError(
                    mode=requested_mode,
                    stage="validation",
                    category="input",
                    user_message=f"不支持的分析任务类型：{self.mode}",
                ),
                requested_mode=requested_mode,
                executed_mode=requested_mode,
                stage="validation",
            )
            return

        manager = None
        executor = None
        future = None
        progress_queue = None
        decision = None
        current_stage = "routing"

        try:
            decision = resolve_analysis_route(self.analysis_mode, config=self.config)
            self.status_changed.emit(decision.message)

            current_stage = "initialization"
            if decision.executed_mode == ANALYSIS_MODE_OFFLINE:
                self.status_changed.emit("正在初始化离线分析引擎")
                context = mp.get_context("spawn")
                manager = context.Manager()
                progress_queue = manager.Queue()
                executor = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=context,
                    initializer=_worker_initializer,
                    initargs=(self.config.to_dict(),),
                )
                future = self._submit_offline_job(executor, progress_queue)
                self.status_changed.emit("离线分析任务已提交到后台进程")
            else:
                if decision.executed_mode == ANALYSIS_MODE_ONLINE:
                    self.status_changed.emit("正在初始化在线分析链路")
                else:
                    self.status_changed.emit("正在初始化混合分析链路")
                progress_queue = queue.Queue()
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="policy-remote-analysis",
                )
                future = self._submit_remote_job(executor, decision.executed_mode, progress_queue)
                self.status_changed.emit("远程分析任务已提交到后台线程")

            current_stage = "execution"
            while True:
                self._drain_progress_queue(progress_queue)
                if future.done():
                    break
                if self._cancel_requested:
                    if future.cancel():
                        self.status_changed.emit("分析任务已取消")
                        return
                    self.status_changed.emit("任务已开始执行，等待当前步骤安全结束")
                    self._cancel_requested = False
                self.msleep(80)

            self._drain_progress_queue(progress_queue)
            current_stage = "result"
            result = future.result()
            self.result_ready.emit(apply_route_metadata(result, decision))
            self.status_changed.emit("分析任务完成")
        except Exception as exc:
            executed_mode = decision.executed_mode if decision is not None else requested_mode
            degraded = bool(decision.degraded) if decision is not None else False
            payload = self._emit_analysis_error(
                exc,
                requested_mode=requested_mode,
                executed_mode=executed_mode,
                stage=current_stage,
                degraded=degraded,
            )
            self.status_changed.emit(build_analysis_error_status_text(payload))
        finally:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)
            if manager is not None:
                manager.shutdown()

    def _submit_offline_job(self, executor: ProcessPoolExecutor, progress_queue: Any):
        if self.mode == ANALYSIS_MODE_SINGLE:
            return executor.submit(_run_single_analysis, self.primary_text, progress_queue)
        if self.mode == ANALYSIS_MODE_COMPARE:
            return executor.submit(_run_compare_analysis, self.primary_text, self.secondary_text, progress_queue)
        return executor.submit(_run_batch_analysis, self.batch_inputs, progress_queue)

    def _submit_remote_job(
        self,
        executor: ThreadPoolExecutor,
        executed_mode: str,
        progress_queue: Any,
    ):
        if executed_mode == ANALYSIS_MODE_ONLINE:
            return executor.submit(
                _run_online_analysis,
                self.mode,
                self.primary_text,
                self.secondary_text,
                self.batch_inputs,
                progress_queue,
                self.config.to_dict(),
            )
        return executor.submit(
            _run_hybrid_analysis,
            self.mode,
            self.primary_text,
            self.secondary_text,
            self.batch_inputs,
            progress_queue,
            self.config.to_dict(),
        )

    def _emit_analysis_error(
        self,
        error: Any,
        *,
        requested_mode: str,
        executed_mode: str,
        stage: str,
        degraded: bool = False,
    ) -> dict[str, Any]:
        payload = coerce_analysis_error_info(
            error,
            requested_mode=requested_mode,
            executed_mode=executed_mode,
            task_mode=self.mode,
            default_mode=executed_mode or requested_mode,
            default_stage=stage,
            degraded=degraded,
        ).to_dict()
        self.error_occurred.emit(payload)
        return payload

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
