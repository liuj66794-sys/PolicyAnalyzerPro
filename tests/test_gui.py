from __future__ import annotations

import copy
import os
import shutil
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.config import load_app_config
from core.nlp_thread import ANALYSIS_MODE_BATCH, ANALYSIS_MODE_SINGLE
from core.startup_checks import DeploymentCheck, StartupCheckReport
from ui.main_window import MainWindow


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args, **kwargs) -> None:
        for callback in list(self._callbacks):
            callback(*args, **kwargs)


class FakeAnalysisThread:
    created: list["FakeAnalysisThread"] = []

    def __init__(self, mode, primary_text, secondary_text="", config=None, parent=None, batch_inputs=None) -> None:
        self.mode = mode
        self.primary_text = primary_text
        self.secondary_text = secondary_text
        self.batch_inputs = copy.deepcopy(batch_inputs or [])
        self.progress_changed = _FakeSignal()
        self.result_ready = _FakeSignal()
        self.error_occurred = _FakeSignal()
        self.status_changed = _FakeSignal()
        self.finished = _FakeSignal()
        self._running = False
        self.cancel_requested = False
        FakeAnalysisThread.created.append(self)

    def isRunning(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True
        self.status_changed.emit("fake-thread-started")
        self.progress_changed.emit(40, "fake-thread-progress")
        self.result_ready.emit(self._build_result())
        self._running = False
        self.finished.emit()

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def wait(self, timeout: int) -> bool:
        return True

    def _build_result(self) -> dict:
        if self.mode == ANALYSIS_MODE_BATCH:
            documents = []
            for item in self.batch_inputs:
                documents.append(
                    {
                        "name": item.get("name", ""),
                        "source_path": item.get("source_path", ""),
                        "analysis": {
                            "metadata": {"meeting_labels": ["\u5341\u56db\u5c4a\u5168\u56fd\u4eba\u5927\u4e09\u6b21\u4f1a\u8bae"], "years": ["2025\u5e74"]},
                            "paragraph_count": 2,
                            "sentence_count": 4,
                            "summary_overview": {
                                "headline": f"{item.get('name', '')} \u5206\u6790\u5b8c\u6210\u3002",
                                "key_takeaways": [f"{item.get('name', '')} \u5df2\u5b8c\u6210\u63d0\u53d6\u3002"],
                            },
                            "new_terms": [{"term": "\u4eba\u5de5\u667a\u80fd", "weight": 1.0}],
                            "core_topics": [{"topic": "\u6570\u5b57\u7ecf\u6d4e", "weight": 0.9}],
                        },
                    }
                )
            return {
                "mode": "batch",
                "total_documents": len(documents),
                "total_paragraphs": sum(item["analysis"]["paragraph_count"] for item in documents),
                "total_sentences": sum(item["analysis"]["sentence_count"] for item in documents),
                "summary_overview": {
                    "headline": f"\u6279\u91cf\u5206\u6790\u5df2\u5b8c\u6210\uff0c\u5171 {len(documents)} \u4efd\u6587\u6863\u3002",
                    "key_findings": ["\u5df2\u5b8c\u6210\u6279\u91cf\u805a\u5408\u3002"],
                },
                "aggregate_new_terms": [{"term": "\u4eba\u5de5\u667a\u80fd", "weight": 2.0}],
                "aggregate_topics": [{"topic": "\u6570\u5b57\u7ecf\u6d4e", "weight": 1.8}],
                "documents": documents,
            }

        return {
            "mode": "single",
            "metadata": {"meeting_labels": ["\u5341\u56db\u5c4a\u5168\u56fd\u4eba\u5927\u4e09\u6b21\u4f1a\u8bae"], "years": ["2025\u5e74"]},
            "summary_overview": {
                "headline": "\u5355\u7bc7\u5206\u6790\u5df2\u5b8c\u6210\u3002",
                "key_takeaways": ["\u68c0\u6d4b\u5230\u91cd\u70b9\u8bae\u9898\u3002"],
            },
            "paragraph_count": 2,
            "sentence_count": 4,
            "new_terms": [{"term": "\u65b0\u8d28\u751f\u4ea7\u529b", "weight": 1.2}],
            "core_topics": [{"topic": "\u9ad8\u8d28\u91cf\u53d1\u5c55", "weight": 0.9}],
        }


def _healthy_report() -> StartupCheckReport:
    return StartupCheckReport(
        results=[
            DeploymentCheck(
                key="core_dependencies",
                title="\u6838\u5fc3\u5206\u6790\u4f9d\u8d56",
                status="ok",
                summary="\u6838\u5fc3\u5206\u6790\u4f9d\u8d56\u5df2\u5b89\u88c5\u3002",
            )
        ],
        checked_at="2026-03-24 12:00:00",
    )


class GuiInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp_root = Path("tests/_tmp_gui")
        cls.tmp_root.mkdir(parents=True, exist_ok=True)

    def setUp(self) -> None:
        FakeAnalysisThread.created.clear()
        self.window = MainWindow(config=load_app_config(), startup_report=_healthy_report())
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def _create_temp_dir(self) -> Path:
        temp_dir = self.tmp_root / f"case_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        return temp_dir

    def _create_text_file(self, directory: Path, name: str, content: str) -> str:
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_single_run_button_starts_analysis_and_renders_result(self) -> None:
        sample_text = "\u653f\u5e9c\u5de5\u4f5c\u62a5\u544a\u6b63\u6587"
        expected_heading = "\u5355\u7bc7\u5206\u6790\u7ed3\u679c"
        self.window.single_input.setPlainText(sample_text)
        with patch("ui.main_window.NLPAnalysisThread", FakeAnalysisThread):
            self.window.single_run_button.click()
            self.app.processEvents()

        self.assertTrue(FakeAnalysisThread.created)
        thread = FakeAnalysisThread.created[-1]
        self.assertEqual(thread.mode, ANALYSIS_MODE_SINGLE)
        self.assertEqual(thread.primary_text, sample_text)
        self.assertIn(expected_heading, self.window.result_view.toPlainText())
        self.assertTrue(self.window.export_markdown_button.isEnabled())

    def test_batch_import_run_and_remove_flow(self) -> None:
        temp_dir = self._create_temp_dir()
        first = self._create_text_file(temp_dir, "a.txt", "\u6587\u6863\u7532\u7b2c\u4e00\u6bb5\n\n\u6587\u6863\u7532\u7b2c\u4e8c\u6bb5")
        second = self._create_text_file(temp_dir, "b.txt", "\u6587\u6863\u4e59\u7b2c\u4e00\u6bb5\n\n\u6587\u6863\u4e59\u7b2c\u4e8c\u6bb5")
        expected_count = "\u5f53\u524d\u5df2\u9009\u62e9 2 \u4efd\u6587\u6863"
        expected_result = "\u6279\u91cf\u5206\u6790\u7ed3\u679c"

        with patch("ui.main_window.QFileDialog.getOpenFileNames", return_value=([first, second], "")):
            self.window.batch_add_button.click()
            self.app.processEvents()

        self.assertEqual(self.window.batch_list.count(), 2)
        self.assertIn(expected_count, self.window.batch_count_label.text())
        self.assertIn("TXT / \u6587\u672c", self.window.preview_status_label.text())

        self.window.batch_list.setCurrentRow(0)
        self.app.processEvents()

        with patch("ui.main_window.NLPAnalysisThread", FakeAnalysisThread):
            self.window.batch_run_button.click()
            self.app.processEvents()

        thread = FakeAnalysisThread.created[-1]
        self.assertEqual(thread.mode, ANALYSIS_MODE_BATCH)
        self.assertEqual(len(thread.batch_inputs), 2)
        self.assertIn(expected_result, self.window.result_view.toPlainText())

        self.window.batch_remove_button.click()
        self.app.processEvents()
        self.assertEqual(self.window.batch_list.count(), 1)

        self.window.batch_clear_button.click()
        self.app.processEvents()
        self.assertEqual(self.window.batch_list.count(), 0)
        self.assertIn("\u5bfc\u5165\u9884\u89c8", self.window.preview_view.toPlainText())

    def test_preview_badge_click_can_insert_hint_note(self) -> None:
        temp_dir = self._create_temp_dir()
        sample = self._create_text_file(temp_dir, "note.txt", "\u7b2c\u4e00\u6bb5\n\n\u7b2c\u4e8c\u6bb5")
        with patch("ui.main_window.QFileDialog.getOpenFileName", return_value=(sample, "")):
            self.window.single_load_button.click()
            self.app.processEvents()

        QTest.mouseClick(self.window.preview_hint_badge, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(self.window.preview_hint_popover.isVisible())

        self.window.preview_hint_popover.insert_button.click()
        self.app.processEvents()

        result_text = self.window.result_view.toPlainText()
        self.assertIn("\u5f85\u9644\u52a0\u8bf4\u660e", result_text)
        self.assertIn("\u8f7b\u63d0\u793a", result_text)


if __name__ == "__main__":
    unittest.main()
