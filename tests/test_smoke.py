import os
import shutil
import unittest
from pathlib import Path

from core.algorithms import PolicyReportAnalyzer
from core.config import load_app_config
from core.import_preview import (
    ImportPreviewState,
    build_import_preview_hint_report_text,
    build_import_preview_hint_style,
    build_import_preview_hint_text,
    build_import_preview_hint_tooltip,
    build_import_preview_markdown,
    build_import_preview_status_style,
    build_import_preview_status_text,
)
from core.result_formatter import AnalysisResultFormatter
from core.startup_checks import (
    DeploymentCheck,
    ModelRuntimeProfile,
    StartupCheckReport,
    build_diagnostic_report_html,
    build_diagnostic_report_markdown,
    build_model_performance_summary_text,
    check_model_directory,
    check_model_trial_load,
    check_model_warmup_benchmark,
    check_ocr_languages,
    check_ocr_pipeline,
    compare_startup_reports,
    extract_model_performance_metrics,
    get_model_performance_level,
    get_model_performance_level_text,
    mark_startup_wizard_completed,
    should_show_startup_wizard,
    summarize_transitions,
)
from core.text_cleaner import TextCleaner
from importers.document_loader import DocumentImportError, DocumentLoader, OcrLoadResult, PdfImportOptions


class FakeOcrDocumentLoader(DocumentLoader):
    def _extract_pdf_text_layer(self, path: Path) -> list[str]:
        return []

    def _get_pdf_page_count(self, path: Path) -> int:
        return 3

    def _perform_pdf_ocr(self, path: Path, pdf_options: PdfImportOptions | None = None) -> OcrLoadResult:
        return OcrLoadResult(
            text="[OCR \u7b2c 1 \u9875]\n\u626b\u63cf\u4ef6\u5185\u5bb9",
            page_numbers=[1],
            page_range_label="1",
            cache_hit=False,
        )


class CachedOcrDocumentLoader(DocumentLoader):
    def __init__(self, config=None) -> None:
        super().__init__(config=config)
        self.ocr_calls = 0

    def _extract_pdf_text_layer(self, path: Path) -> list[str]:
        return []

    def _get_pdf_page_count(self, path: Path) -> int:
        return 8

    def _perform_pdf_ocr_uncached(self, path: Path, page_numbers: list[int]) -> str:
        self.ocr_calls += 1
        return "\n\n".join(
            f"[OCR \u7b2c {page_number} \u9875]\n\u626b\u63cf\u4ef6\u5185\u5bb9 {page_number}"
            for page_number in page_numbers
        )


class FakeSettings:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def value(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def setValue(self, key: str, value: str) -> None:
        self._data[key] = value


class SmokeTests(unittest.TestCase):
    def test_load_app_config(self) -> None:
        config = load_app_config()
        self.assertEqual(config.app_name, "PolicyAnalyzerPro")
        self.assertEqual(config.analysis_mode, "offline")
        self.assertFalse(config.policy_source_enabled)
        self.assertEqual(config.llm_provider, "")
        self.assertFalse(config.cloud_fallback_enabled)
        self.assertEqual(config.process_pool_workers, 1)
        self.assertEqual(config.offline_env["HF_HUB_OFFLINE"], "1")
        self.assertTrue(config.enable_pdf_ocr)
        self.assertTrue(config.enable_model_trial_load_check)
        self.assertTrue(config.enable_model_warmup_benchmark_check)
        self.assertEqual(config.model_benchmark_batch_size, 4)
        self.assertTrue(config.enable_ocr_result_cache)
        self.assertEqual(config.ocr_cache_dir, "cache/ocr")

    def test_text_cleaner_removes_news_noise(self) -> None:
        cleaner = TextCleaner()
        text = "新华社北京3月1日电\n责任编辑：张三\n十四届全国人大二次会议政府工作报告。"
        cleaned = cleaner.clean_text(text)
        self.assertNotIn("新华社", cleaned)
        self.assertNotIn("责任编辑", cleaned)
        self.assertIn("十四届全国人大二次会议政府工作报告", cleaned)

    def test_prepare_text_extracts_meeting_metadata(self) -> None:
        analyzer = PolicyReportAnalyzer()
        prepared = analyzer.prepare_text("十四届全国人大二次会议政府工作报告。")
        self.assertIn("十四届全国人大二次会议", prepared.metadata["meeting_labels"])

    def test_analyze_text_structure(self) -> None:
        analyzer = PolicyReportAnalyzer()
        text = "第一段内容。\n\n第二段内容，这是一个更长的段落，包含更多的文字。\n\n第三段内容。"
        prepared = analyzer.prepare_text(text)
        structure = analyzer.analyze_text_structure(prepared)
        
        self.assertEqual(len(structure["paragraph_lengths"]), 3)
        self.assertEqual(len(structure["sentence_lengths"]), 3)
        self.assertGreater(structure["avg_paragraph_length"], 0)
        self.assertGreater(structure["avg_sentence_length"], 0)
        self.assertGreater(structure["longest_paragraph_length"], 0)
        self.assertGreater(structure["longest_sentence_length"], 0)

    def test_document_loader_reads_text_file(self) -> None:
        loader = DocumentLoader()
        temp_root = Path("tests/_tmp_text")
        temp_root.mkdir(parents=True, exist_ok=True)
        sample_path = temp_root / "sample.txt"
        try:
            sample_path.write_text("政策文本内容", encoding="utf-8")
            content = loader.load_text_from_path(sample_path)
            self.assertEqual(content, "政策文本内容")
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)

    def test_document_loader_rejects_unknown_extension(self) -> None:
        loader = DocumentLoader()
        temp_root = Path("tests/_tmp_unknown")
        temp_root.mkdir(parents=True, exist_ok=True)
        sample_path = temp_root / "sample.xyz"
        try:
            sample_path.write_text("x", encoding="utf-8")
            with self.assertRaises(DocumentImportError):
                loader.load_text_from_path(sample_path)
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)

    def test_document_loader_can_fallback_to_ocr(self) -> None:
        loader = FakeOcrDocumentLoader()
        temp_root = Path("tests/_tmp_pdf")
        temp_root.mkdir(parents=True, exist_ok=True)
        sample_path = temp_root / "scan.pdf"
        try:
            sample_path.write_bytes(b"%PDF-1.4")
            content = loader.load_text_from_path(sample_path)
            self.assertIn("扫描件内容", content)
            self.assertIn("OCR", content)
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)

    def test_document_loader_tracks_ocr_page_range_and_cache(self) -> None:
        config = load_app_config().merge({"ocr_cache_dir": "tests/_tmp_ocr_cache"})
        loader = CachedOcrDocumentLoader(config=config)
        temp_root = Path("tests/_tmp_ocr_pdf")
        temp_root.mkdir(parents=True, exist_ok=True)
        sample_path = temp_root / "scan.pdf"
        try:
            sample_path.write_bytes(b"%PDF-1.4")
            options = PdfImportOptions(ocr_page_spec="2-4,6", use_ocr_cache=True)
            first = loader.load_text_from_path(sample_path, pdf_options=options)
            self.assertIn("[OCR \u7b2c 2 \u9875]", first)
            self.assertEqual(loader.ocr_calls, 1)
            self.assertEqual(loader.last_load_state.ocr_page_range, "2-4,6")
            self.assertEqual(loader.last_load_state.ocr_page_count, 4)
            self.assertFalse(loader.last_load_state.ocr_cache_hit)

            second = loader.load_text_from_path(sample_path, pdf_options=options)
            self.assertEqual(first, second)
            self.assertEqual(loader.ocr_calls, 1)
            self.assertTrue(loader.last_load_state.ocr_cache_hit)
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)
            cache_root = Path(config.resolved_ocr_cache_dir)
            if cache_root.exists():
                shutil.rmtree(cache_root)

    def test_document_loader_rejects_invalid_ocr_page_range(self) -> None:
        loader = CachedOcrDocumentLoader(config=load_app_config())
        temp_root = Path("tests/_tmp_ocr_invalid")
        temp_root.mkdir(parents=True, exist_ok=True)
        sample_path = temp_root / "scan.pdf"
        try:
            sample_path.write_bytes(b"%PDF-1.4")
            with self.assertRaises(DocumentImportError):
                loader.load_text_from_path(
                    sample_path,
                    pdf_options=PdfImportOptions(ocr_page_spec="9-10", use_ocr_cache=False),
                )
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)

    def test_document_loader_cleans_pdf_text_layer_artifacts(self) -> None:
        loader = DocumentLoader()
        raw_page = "\n".join(
            [
                "政 　 府 　 工 　 作 　 报 　 告政 　 府 　 工 　 作 　 报 　 告",
                "各 位 代 表 ：各 位 代 表 ：现在，我代表国务院，向大会报告政府工作，请予审议。",
                "一 、 2 0 2 4 年 工 作 回 顾一 、 2 0 2 4 年 工 作 回 顾",
                "2026/3/23 21:07 政府⽉作报告 __ 中国政府⽹",
                "https://www.gov.cn/gongbao/2025/issue_11946/202503/content_7015861.html 1/15",
            ]
        )

        cleaned = loader._clean_pdf_text_layer_page(raw_page, page_number=1, total_pages=15)

        self.assertIn("政府工作报告", cleaned)
        self.assertEqual(cleaned.count("政府工作报告"), 1)
        self.assertIn("各位代表：现在，我代表国务院", cleaned)
        self.assertIn("一、2024年工作回顾", cleaned)
        self.assertNotIn("gov.cn", cleaned)
        self.assertNotIn("2026/3/23 21:07", cleaned)

    def test_document_loader_tracks_last_load_state_for_text(self) -> None:
        loader = DocumentLoader()
        temp_root = Path("tests/_tmp_text_state")
        temp_root.mkdir(parents=True, exist_ok=True)
        sample_path = temp_root / "sample.txt"
        try:
            sample_path.write_text("\u7b2c\u4e00\u6bb5\n\n\n\u7b2c\u4e8c\u6bb5", encoding="utf-8")
            loader.load_text_from_path(sample_path)
            state = loader.last_load_state
            self.assertEqual(state.extraction_mode, "text_file")
            self.assertEqual(state.source_suffix, ".txt")
            self.assertEqual(state.cleaned_paragraph_count, 2)
            self.assertTrue(state.abnormal_blank_lines)
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root)

    def test_import_preview_status_text_summarizes_state(self) -> None:
        state = ImportPreviewState(
            source_path="D:/chapter1/samples/report.pdf",
            source_suffix=".pdf",
            extraction_mode="pdf_text_layer",
            raw_char_count=1200,
            non_empty_line_count=30,
            cleaned_paragraph_count=12,
            abnormal_blank_lines=False,
        )
        text = build_import_preview_status_text(state)
        self.assertNotIn("\u8f7b\u63d0\u793a", text)
        self.assertIn("\u6587\u5b57\u5c42 PDF", text)
        self.assertIn("\u6e05\u6d17\u540e\u6bb5\u843d\uff1a12", text)
        self.assertIn("\u672a\u53d1\u73b0\u5f02\u5e38\u7a7a\u884c", text)

    def test_import_preview_hint_text_summarizes_state(self) -> None:
        state = ImportPreviewState(
            source_path="D:/chapter1/samples/report.pdf",
            source_suffix=".pdf",
            extraction_mode="pdf_text_layer",
        )
        text = build_import_preview_hint_text(state)
        tooltip = build_import_preview_hint_tooltip(state)
        self.assertEqual(text, "轻提示：文字层直读")
        self.assertIn("PDF 自带文字层", tooltip)
        self.assertIn("比 OCR 更稳定", tooltip)

    def test_import_preview_status_text_prioritizes_blank_line_warning(self) -> None:
        state = ImportPreviewState(
            source_path="D:/chapter1/samples/report.pdf",
            source_suffix=".pdf",
            extraction_mode="pdf_ocr",
            raw_char_count=980,
            non_empty_line_count=18,
            cleaned_paragraph_count=5,
            abnormal_blank_lines=True,
        )
        text = build_import_preview_status_text(state)
        hint_text = build_import_preview_hint_text(state)
        tooltip = build_import_preview_hint_tooltip(state)
        self.assertEqual(hint_text, "轻提示：空行异常")
        self.assertIn("OCR", text)
        self.assertIn("检测到异常空行", text)
        self.assertIn("连续三个及以上空行", tooltip)
        self.assertIn("OCR / PDF 提取结果不稳定", tooltip)

    def test_import_preview_hint_tooltip_explains_ocr_review(self) -> None:
        tooltip = build_import_preview_hint_tooltip(
            ImportPreviewState(source_path="a.pdf", extraction_mode="pdf_ocr")
        )
        self.assertIn("\u004f\u0043\u0052 \u590d\u6838", tooltip)
        self.assertIn("\u5f53\u524d\u6587\u672c\u6765\u81ea OCR \u8bc6\u522b", tooltip)
        self.assertIn("\u5efa\u8bae\uff1a\u5148\u68c0\u67e5\u7f16\u8f91\u533a\u7b2c 1-3 \u6bb5\u3002", tooltip)

    def test_import_preview_hint_report_text_is_copy_ready(self) -> None:
        report_text = build_import_preview_hint_report_text(
            ImportPreviewState(
                source_path="a.pdf",
                extraction_mode="pdf_ocr",
                cleaned_paragraph_count=8,
                abnormal_blank_lines=False,
            )
        )
        self.assertIn("\u68c0\u6d4b\u5230\uff1aOCR", report_text)
        self.assertIn("\u8f7b\u63d0\u793a\uff1aOCR \u590d\u6838", report_text)
        self.assertIn("\u5224\u5b9a\u8bf4\u660e\uff1a", report_text)
        self.assertIn("\u5efa\u8bae\uff1a\u5148\u68c0\u67e5\u7f16\u8f91\u533a\u7b2c 1-3 \u6bb5\u3002", report_text)

    def test_import_preview_hint_tooltip_defaults_when_no_document(self) -> None:
        tooltip = build_import_preview_hint_tooltip(None)
        self.assertIn("尚未导入文档", tooltip)
        self.assertIn("badge", tooltip)

    def test_import_preview_hint_style_uses_expected_colors(self) -> None:
        blue_style = build_import_preview_hint_style(
            ImportPreviewState(source_path="a.pdf", extraction_mode="pdf_text_layer")
        )
        yellow_style = build_import_preview_hint_style(
            ImportPreviewState(source_path="a.pdf", extraction_mode="pdf_ocr")
        )
        orange_style = build_import_preview_hint_style(
            ImportPreviewState(source_path="a.pdf", extraction_mode="pdf_ocr", abnormal_blank_lines=True)
        )

        self.assertIn("#eff6ff", blue_style)
        self.assertIn("#fffbeb", yellow_style)
        self.assertIn("#fff7ed", orange_style)
        self.assertIn("QLabel:hover", blue_style)
        self.assertIn("QLabel:hover", yellow_style)
        self.assertIn("QLabel:hover", orange_style)

    def test_import_preview_status_style_is_neutral_text(self) -> None:
        default_style = build_import_preview_status_style(None)
        loaded_style = build_import_preview_status_style(
            ImportPreviewState(source_path="a.pdf", extraction_mode="pdf_text_layer")
        )

        self.assertIn("#667085", default_style)
        self.assertIn("#344054", loaded_style)
        self.assertNotIn("#eff6ff", loaded_style)

    def test_document_loader_formats_pdf_cover_lines(self) -> None:
        loader = DocumentLoader()
        pages = [
            "\n".join(
                [
                    "政府工作报告",
                    "——2025年3月5日在第十四届全国人民代表大会第三次会议上国务院总理李强",
                    "各位代表：现在，我代表国务院，向大会报告政府工作，请予审议。",
                ]
            )
        ]

        cleaned = loader._clean_pdf_text_layer_document(pages)
        lines = [line for line in cleaned.splitlines() if line.strip()]

        self.assertEqual(lines[0], "政府工作报告")
        self.assertEqual(lines[1], "——2025年3月5日在第十四届全国人民代表大会第三次会议上")
        self.assertEqual(lines[2], "国务院总理 李强")
        self.assertTrue(lines[3].startswith("各位代表："))

    def test_import_preview_markdown_shows_cover_and_body(self) -> None:
        sample_text = "\n".join(
            [
                "\u653f\u5e9c\u5de5\u4f5c\u62a5\u544a",
                "\u2014\u20142025\u5e743\u67085\u65e5\u5728\u7b2c\u5341\u56db\u5c4a\u5168\u56fd\u4eba\u6c11\u4ee3\u8868\u5927\u4f1a\u7b2c\u4e09\u6b21\u4f1a\u8bae\u4e0a",
                "\u56fd\u52a1\u9662\u603b\u7406 \u674e\u5f3a",
                "\u5404\u4f4d\u4ee3\u8868\uff1a\u73b0\u5728\uff0c\u6211\u4ee3\u8868\u56fd\u52a1\u9662\uff0c\u5411\u5927\u4f1a\u62a5\u544a\u653f\u5e9c\u5de5\u4f5c\uff0c\u8bf7\u4e88\u5ba1\u8bae\u3002",
                "\u8fc7\u53bb\u4e00\u5e74\uff0c\u6211\u56fd\u53d1\u5c55\u5386\u7a0b\u5f88\u4e0d\u5e73\u51e1\u3002",
                "\u4e00\u30012024\u5e74\u5de5\u4f5c\u56de\u987e",
            ]
        )
        markdown = build_import_preview_markdown(
            sample_text,
            source_path="D:/chapter1/samples/report.pdf",
            target_label="单篇分析",
        )

        self.assertIn("# 导入预览", markdown)
        self.assertIn("- 文件名：report.pdf", markdown)
        self.assertIn("> 政府工作报告", markdown)
        self.assertIn("> 国务院总理 李强", markdown)
        self.assertIn("1. 各位代表：现在，我代表国务院", markdown)
        self.assertNotIn("1. 政府工作报告", markdown)
        self.assertNotIn("1. 一、2024年工作回顾", markdown)

    def test_import_preview_status_text_includes_ocr_range_and_cache(self) -> None:
        state = ImportPreviewState(
            source_path="D:/chapter1/samples/scan.pdf",
            source_suffix=".pdf",
            extraction_mode="pdf_ocr",
            cleaned_paragraph_count=6,
            abnormal_blank_lines=False,
            ocr_page_range="2-4,6",
            ocr_page_count=4,
            ocr_cache_hit=True,
        )
        text = build_import_preview_status_text(state)
        markdown = build_import_preview_markdown(
            "[OCR \u7b2c 2 \u9875]\n\u626b\u63cf\u4ef6\u5185\u5bb9\n\n[OCR \u7b2c 3 \u9875]\n\u626b\u63cf\u4ef6\u5185\u5bb9",
            source_path=state.source_path,
            target_label="\u6279\u91cf\u5206\u6790",
            preview_state=state,
        )
        tooltip = build_import_preview_hint_tooltip(state)

        self.assertIn("OCR \u9875\u7801\uff1a2-4,6", text)
        self.assertIn("OCR \u9875\u6570\uff1a4", text)
        self.assertIn("OCR \u7f13\u5b58\uff1a\u547d\u4e2d", text)
        self.assertIn("- OCR \u9875\u7801\u8303\u56f4\uff1a2-4,6", markdown)
        self.assertIn("- OCR \u7f13\u5b58\uff1a\u547d\u4e2d", markdown)
        self.assertIn("\u672c\u6b21 OCR \u7ed3\u679c\u76f4\u63a5\u6765\u81ea\u672c\u5730\u7f13\u5b58", tooltip)

    def test_main_window_source_contains_pdf_import_options_wiring(self) -> None:
        source = Path("ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("class PdfImportOptionsDialog(QDialog):", source)
        self.assertIn("def _collect_pdf_import_options(self, file_path: Path)", source)
        self.assertIn("pdf_options = self._collect_pdf_import_options(file_path)", source)
        self.assertIn("self._document_loader.load_text_from_path(file_path, pdf_options=pdf_options)", source)
        self.assertIn("\\u542f\\u7528 OCR \\u7ed3\\u679c\\u7f13\\u5b58", source)

    def test_environment_ui_sources_reference_performance_metrics(self) -> None:
        startup_source = Path("ui/startup_wizard.py").read_text(encoding="utf-8")
        main_source = Path("ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("def _build_performance_metrics_html(self, check: DeploymentCheck)", startup_source)
        self.assertIn("extract_model_performance_metrics(check, self.config)", startup_source)
        self.assertIn("\\u6027\\u80fd\\u7b49\\u7ea7", startup_source)
        self.assertIn("self.environment_performance_badge = QLabel(container)", main_source)
        self.assertIn("def _build_environment_performance_summary_html(self)", main_source)
        self.assertIn('self.environment_performance_badge.setText(f"\u6a21\u578b\u6027\u80fd {badge_text}")', main_source)


    def test_startup_wizard_source_supports_html_and_pdf_diagnostic_export(self) -> None:
        startup_source = Path("ui/startup_wizard.py").read_text(encoding="utf-8")
        self.assertIn("build_diagnostic_report_html", startup_source)
        self.assertIn("def _resolve_diagnostic_export_target(self, raw_path: str, selected_filter: str)", startup_source)
        self.assertIn("HTML 文件 (*.html)", startup_source)
        self.assertIn("PDF 文件 (*.pdf)", startup_source)
        self.assertIn("QPrinter.OutputFormat.PdfFormat", startup_source)
        self.assertIn("document.print_(printer)", startup_source)


    def test_policy_report_analyzer_batch_aggregates_documents(self) -> None:
        analyzer = PolicyReportAnalyzer()
        fake_results = {
            "文本甲": {
                "mode": "single",
                "metadata": {"meeting_labels": ["十四届全国人大三次会议"], "years": ["2025年"]},
                "summary_overview": {
                    "headline": "文档甲分析完成。",
                    "key_takeaways": ["文档甲包含产业升级信号。"],
                },
                "paragraph_count": 3,
                "sentence_count": 8,
                "new_terms": [{"term": "人工智能", "weight": 1.4}],
                "core_topics": [{"topic": "数字经济", "weight": 1.2}],
            },
            "文本乙": {
                "mode": "single",
                "metadata": {"meeting_labels": ["十四届全国人大三次会议"], "years": ["2025年"]},
                "summary_overview": {
                    "headline": "文档乙分析完成。",
                    "key_takeaways": ["文档乙强调消费提振。"],
                },
                "paragraph_count": 2,
                "sentence_count": 5,
                "new_terms": [{"term": "人工智能", "weight": 0.9}, {"term": "扩大内需", "weight": 0.8}],
                "core_topics": [{"topic": "数字经济", "weight": 0.7}, {"topic": "消费", "weight": 0.6}],
            },
        }

        def fake_single(text_value: str, progress_callback=None):
            if progress_callback is not None:
                progress_callback(100, "单篇分析完成")
            return fake_results[text_value]

        analyzer.analyze_single_report = fake_single  # type: ignore[assignment]
        progress_events: list[tuple[int, str]] = []
        batch_result = analyzer.analyze_batch_reports(
            [
                {"name": "文档甲", "text": "文本甲", "source_path": "a.txt"},
                {"name": "文档乙", "text": "文本乙", "source_path": "b.txt"},
            ],
            progress_callback=lambda percent, message: progress_events.append((percent, message)),
        )

        self.assertEqual(batch_result["mode"], "batch")
        self.assertEqual(batch_result["total_documents"], 2)
        self.assertEqual(batch_result["total_paragraphs"], 5)
        self.assertEqual(batch_result["total_sentences"], 13)
        self.assertEqual(batch_result["documents"][0]["name"], "文档甲")
        self.assertEqual(batch_result["aggregate_new_terms"][0]["term"], "人工智能")
        self.assertEqual(batch_result["aggregate_topics"][0]["topic"], "数字经济")
        self.assertIn("共分析 2 份文档", batch_result["summary_overview"]["key_findings"][0])
        self.assertEqual(progress_events[-1][0], 100)
        self.assertIn("批量分析完成", progress_events[-1][1])

    def test_formatter_builds_batch_markdown_and_html(self) -> None:
        formatter = AnalysisResultFormatter()
        result = {
            "mode": "batch",
            "total_documents": 2,
            "total_paragraphs": 5,
            "total_sentences": 13,
            "summary_overview": {
                "headline": "批量分析共覆盖 2 份文档。",
                "key_findings": ["高频议题集中在数字经济和消费。"],
            },
            "aggregate_new_terms": [
                {"term": "人工智能", "weight": 2.3},
                {"term": "扩大内需", "weight": 0.8},
            ],
            "aggregate_topics": [
                {"topic": "数字经济", "weight": 1.9},
                {"topic": "消费", "weight": 0.6},
            ],
            "documents": [
                {
                    "name": "文档甲",
                    "source_path": "a.txt",
                    "analysis": {
                        "metadata": {"meeting_labels": ["十四届全国人大三次会议"], "years": ["2025年"]},
                        "paragraph_count": 3,
                        "sentence_count": 8,
                        "summary_overview": {
                            "headline": "文档甲分析完成。",
                            "key_takeaways": ["文档甲包含产业升级信号。"],
                        },
                        "new_terms": [{"term": "人工智能", "weight": 1.4}],
                        "core_topics": [{"topic": "数字经济", "weight": 1.2}],
                    },
                },
                {
                    "name": "文档乙",
                    "source_path": "b.txt",
                    "analysis": {
                        "metadata": {"meeting_labels": ["十四届全国人大三次会议"], "years": ["2025年"]},
                        "paragraph_count": 2,
                        "sentence_count": 5,
                        "summary_overview": {
                            "headline": "文档乙分析完成。",
                            "key_takeaways": ["文档乙强调消费提振。"],
                        },
                        "new_terms": [{"term": "扩大内需", "weight": 0.8}],
                        "core_topics": [{"topic": "消费", "weight": 0.6}],
                    },
                },
            ],
            "import_preview_notes": ["\u8f7b\u63d0\u793a\uff1a\u6587\u5b57\u5c42\u76f4\u8bfb\n\u68c0\u6d4b\u5230\uff1a\u6587\u5b57\u5c42 PDF"],
        }

        markdown = formatter.to_markdown(result)
        html = formatter.to_html_report(result)

        self.assertIn("# 批量分析结果", markdown)
        self.assertIn("## 文档概览", markdown)
        self.assertIn("文档甲", markdown)
        self.assertIn("导入提示说明", markdown)
        self.assertIn("PolicyAnalyzerPro - 批量分析", html)
        self.assertIn("批量分析报告", html)
        self.assertIn("文档概览", html)
        self.assertIn("batch-doc-card", html)

    def test_main_window_source_contains_batch_mode_wiring(self) -> None:
        source = Path("ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("ANALYSIS_MODE_BATCH", source)
        self.assertIn("def _build_batch_tab(self)", source)
        self.assertIn("self.batch_add_button = QPushButton", source)
        self.assertIn("self.batch_run_button.clicked.connect(self._start_batch_analysis)", source)
        self.assertIn("def _load_batch_documents(self)", source)
        self.assertIn("batch_inputs=batch_inputs", source)


if __name__ == "__main__":
    unittest.main()
