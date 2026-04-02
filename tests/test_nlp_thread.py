from __future__ import annotations

import queue
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from core.analysis_errors import build_analysis_error_status_text, build_analysis_error_text
from core.analysis_router import (
    ANALYSIS_MODE_HYBRID,
    ANALYSIS_MODE_OFFLINE,
    ANALYSIS_MODE_ONLINE,
    AnalysisCapabilitySnapshot,
    AnalysisRouteDecision,
)
from core.hybrid_pipeline.errors import HybridPipelineUnavailableError
from core.nlp_thread import ANALYSIS_MODE_SINGLE, NLPAnalysisThread
from core.online_llm.errors import OnlineLLMUnavailableError


class _ImmediateFuture:
    def __init__(self, result=None, exception: Exception | None = None) -> None:
        self._result = result
        self._exception = exception

    def done(self) -> bool:
        return True

    def cancel(self) -> bool:
        return True

    def result(self):
        if self._exception is not None:
            raise self._exception
        return self._result


class _FakeProcessExecutor:
    created = 0
    submit_calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        type(self).created += 1

    def submit(self, fn, *args):
        type(self).submit_calls.append(fn.__name__)
        return _ImmediateFuture({"mode": "single", "summary_overview": {"headline": "offline"}})

    def shutdown(self, wait=False, cancel_futures=True) -> None:
        return None


class _FakeThreadExecutor:
    created = 0
    submit_calls: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        type(self).created += 1

    def submit(self, fn, *args):
        type(self).submit_calls.append(fn.__name__)
        return _ImmediateFuture({"mode": "single", "summary_overview": {"headline": "remote"}})

    def shutdown(self, wait=False, cancel_futures=True) -> None:
        return None


class _FailingThreadExecutor:
    created = 0
    submit_calls: list[str] = []
    failure: Exception | None = None

    def __init__(self, *args, **kwargs) -> None:
        type(self).created += 1

    def submit(self, fn, *args):
        type(self).submit_calls.append(fn.__name__)
        return _ImmediateFuture(exception=type(self).failure)

    def shutdown(self, wait=False, cancel_futures=True) -> None:
        return None


class _FakeManager:
    def Queue(self):
        return queue.Queue()

    def shutdown(self) -> None:
        return None


class _FakeContext:
    def Manager(self):
        return _FakeManager()


class NlpThreadExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        _FakeProcessExecutor.created = 0
        _FakeProcessExecutor.submit_calls = []
        _FakeThreadExecutor.created = 0
        _FakeThreadExecutor.submit_calls = []
        _FailingThreadExecutor.created = 0
        _FailingThreadExecutor.submit_calls = []
        _FailingThreadExecutor.failure = None

    def _decision(self, executed_mode: str) -> AnalysisRouteDecision:
        return AnalysisRouteDecision(
            requested_mode=executed_mode,
            executed_mode=executed_mode,
            capability_snapshot=AnalysisCapabilitySnapshot(selected_mode=executed_mode),
        )

    def test_offline_mode_uses_process_pool_path(self) -> None:
        thread = NLPAnalysisThread(
            mode=ANALYSIS_MODE_SINGLE,
            primary_text="政策文本",
            analysis_mode=ANALYSIS_MODE_OFFLINE,
        )

        with patch("core.nlp_thread.resolve_analysis_route", return_value=self._decision(ANALYSIS_MODE_OFFLINE)), \
             patch("core.nlp_thread.ProcessPoolExecutor", _FakeProcessExecutor), \
             patch("core.nlp_thread.ThreadPoolExecutor", side_effect=AssertionError("thread executor should not be used for offline")), \
             patch("core.nlp_thread.mp.get_context", return_value=_FakeContext()):
            thread.run()

        self.assertEqual(_FakeProcessExecutor.created, 1)
        self.assertEqual(_FakeThreadExecutor.created, 0)
        self.assertIn("_run_single_analysis", _FakeProcessExecutor.submit_calls)

    def test_online_mode_uses_thread_pool_path(self) -> None:
        thread = NLPAnalysisThread(
            mode=ANALYSIS_MODE_SINGLE,
            primary_text="政策文本",
            analysis_mode=ANALYSIS_MODE_ONLINE,
        )

        with patch("core.nlp_thread.resolve_analysis_route", return_value=self._decision(ANALYSIS_MODE_ONLINE)), \
             patch("core.nlp_thread.ProcessPoolExecutor", side_effect=AssertionError("process executor should not be used for online")), \
             patch("core.nlp_thread.ThreadPoolExecutor", _FakeThreadExecutor), \
             patch("core.nlp_thread.mp.get_context", side_effect=AssertionError("mp context should not be used for online")):
            thread.run()

        self.assertEqual(_FakeProcessExecutor.created, 0)
        self.assertEqual(_FakeThreadExecutor.created, 1)
        self.assertIn("_run_online_analysis", _FakeThreadExecutor.submit_calls)

    def test_hybrid_mode_uses_thread_pool_path(self) -> None:
        thread = NLPAnalysisThread(
            mode=ANALYSIS_MODE_SINGLE,
            primary_text="政策文本",
            analysis_mode=ANALYSIS_MODE_HYBRID,
        )

        with patch("core.nlp_thread.resolve_analysis_route", return_value=self._decision(ANALYSIS_MODE_HYBRID)), \
             patch("core.nlp_thread.ProcessPoolExecutor", side_effect=AssertionError("process executor should not be used for hybrid")), \
             patch("core.nlp_thread.ThreadPoolExecutor", _FakeThreadExecutor), \
             patch("core.nlp_thread.mp.get_context", side_effect=AssertionError("mp context should not be used for hybrid")):
            thread.run()

        self.assertEqual(_FakeProcessExecutor.created, 0)
        self.assertEqual(_FakeThreadExecutor.created, 1)
        self.assertIn("_run_hybrid_analysis", _FakeThreadExecutor.submit_calls)

    def test_online_validation_error_keeps_online_contract(self) -> None:
        thread = NLPAnalysisThread(
            mode=ANALYSIS_MODE_SINGLE,
            primary_text="",
            analysis_mode=ANALYSIS_MODE_ONLINE,
        )
        errors: list[dict] = []
        thread.error_occurred.connect(errors.append)

        thread.run()

        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload["mode"], ANALYSIS_MODE_ONLINE)
        self.assertEqual(payload["title"], "在线分析失败")
        self.assertEqual(payload["stage"], "validation")
        self.assertIn("执行模式：在线分析", build_analysis_error_text(payload))

    def test_online_runtime_failure_emits_mode_isolated_payload(self) -> None:
        _FailingThreadExecutor.failure = OnlineLLMUnavailableError("在线能力骨架尚未启用正式 Provider。")
        thread = NLPAnalysisThread(
            mode=ANALYSIS_MODE_SINGLE,
            primary_text="政策文本",
            analysis_mode=ANALYSIS_MODE_ONLINE,
        )
        errors: list[dict] = []
        statuses: list[str] = []
        thread.error_occurred.connect(errors.append)
        thread.status_changed.connect(statuses.append)

        with patch("core.nlp_thread.resolve_analysis_route", return_value=self._decision(ANALYSIS_MODE_ONLINE)), \
             patch("core.nlp_thread.ProcessPoolExecutor", side_effect=AssertionError("process executor should not be used for online")), \
             patch("core.nlp_thread.ThreadPoolExecutor", _FailingThreadExecutor), \
             patch("core.nlp_thread.mp.get_context", side_effect=AssertionError("mp context should not be used for online")):
            thread.run()

        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload["mode"], ANALYSIS_MODE_ONLINE)
        self.assertEqual(payload["title"], "在线分析失败")
        self.assertEqual(payload["stage"], "capability_check")
        self.assertIn("失败阶段：能力检查", build_analysis_error_text(payload))
        self.assertTrue(statuses)
        self.assertIn("在线分析失败", build_analysis_error_status_text(payload))

    def test_hybrid_runtime_failure_emits_mode_isolated_payload(self) -> None:
        _FailingThreadExecutor.failure = HybridPipelineUnavailableError("混合分析骨架尚未启用正式在线增强执行。")
        thread = NLPAnalysisThread(
            mode=ANALYSIS_MODE_SINGLE,
            primary_text="政策文本",
            analysis_mode=ANALYSIS_MODE_HYBRID,
        )
        errors: list[dict] = []
        thread.error_occurred.connect(errors.append)

        with patch("core.nlp_thread.resolve_analysis_route", return_value=self._decision(ANALYSIS_MODE_HYBRID)), \
             patch("core.nlp_thread.ProcessPoolExecutor", side_effect=AssertionError("process executor should not be used for hybrid")), \
             patch("core.nlp_thread.ThreadPoolExecutor", _FailingThreadExecutor), \
             patch("core.nlp_thread.mp.get_context", side_effect=AssertionError("mp context should not be used for hybrid")):
            thread.run()

        self.assertEqual(len(errors), 1)
        payload = errors[0]
        self.assertEqual(payload["mode"], ANALYSIS_MODE_HYBRID)
        self.assertEqual(payload["title"], "混合分析失败")
        self.assertEqual(payload["stage"], "capability_check")
        self.assertIn("执行模式：混合分析", build_analysis_error_text(payload))


if __name__ == "__main__":
    unittest.main()
