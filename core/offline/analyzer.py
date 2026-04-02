from __future__ import annotations

import re
from typing import Any

from core.config import AppConfig, DEFAULT_CONFIG
from core.text_cleaner import TextCleaner

from .extraction import ExtractionMixin
from .summaries import SummaryMixin
from .types import ProgressCallback


class PolicyReportAnalyzer(ExtractionMixin, SummaryMixin):
    """Offline NLP analysis engine for long-form Chinese policy documents."""

    _metadata_patterns = [
        re.compile(
            r"([一二三四五六七八九十百零两]+届(?:全国)?(?:人民代表大会|人大|政协)(?:[一二三四五六七八九十百零两]+次会议)?)"
        ),
        re.compile(
            r"((?:全国)?政协第?[一二三四五六七八九十百零两]+届(?:委员会)?(?:第?[一二三四五六七八九十百零两]+次会议)?)"
        ),
        re.compile(
            r"([一二三四五六七八九十百零两]+届(?:中央委员会|中央纪委)(?:第?[一二三四五六七八九十百零两]+次全体会议)?)"
        ),
    ]

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG
        self.cleaner = TextCleaner(self.config)
        self._jieba = None
        self._jieba_analyse = None
        self._embedding_model = None
        self._blocked_terms = {
            term.strip()
            for term in (
                list(self.config.political_stopwords)
                + list(self.config.historical_baseline_terms)
            )
            if term.strip()
        }

    def analyze_single_report(
        self, text: str, progress_callback: ProgressCallback | None = None
    ) -> dict[str, Any]:
        self._emit_progress(progress_callback, 5, "正在清洗文本")
        prepared = self.prepare_text(text)

        self._emit_progress(progress_callback, 25, "正在提取元信息")
        metadata = prepared.metadata

        self._emit_progress(progress_callback, 45, "正在提取新提法")
        new_terms = self.extract_new_terms(prepared.cleaned_text)

        self._emit_progress(progress_callback, 65, "正在提取核心议题")
        core_topics = self.extract_core_topics(prepared.cleaned_text)

        self._emit_progress(progress_callback, 85, "正在分析文本结构")
        text_structure = self.analyze_text_structure(prepared)

        self._emit_progress(progress_callback, 95, "正在生成分析摘要")
        summary_overview = self._build_single_summary(
            prepared=prepared,
            new_terms=new_terms,
            core_topics=core_topics,
            text_structure=text_structure,
        )

        self._emit_progress(progress_callback, 100, "单篇分析完成")
        return {
            "mode": "single",
            "metadata": metadata,
            "summary_overview": summary_overview,
            "cleaned_text": prepared.cleaned_text,
            "paragraph_count": len(prepared.paragraphs),
            "sentence_count": len(prepared.sentences),
            "new_terms": new_terms,
            "core_topics": core_topics,
            "text_structure": text_structure,
        }

    def compare_reports(
        self,
        old_text: str,
        new_text: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        self._emit_progress(progress_callback, 5, "正在清洗两篇文本")
        old_report = self.prepare_text(old_text)
        new_report = self.prepare_text(new_text)

        self._emit_progress(progress_callback, 18, "正在提取元信息")
        metadata = {
            "old": old_report.metadata,
            "new": new_report.metadata,
        }

        self._emit_progress(progress_callback, 36, "正在提取新提法")
        new_terms = self.extract_new_terms(new_report.cleaned_text)

        self._emit_progress(progress_callback, 66, "正在分析措辞微调")
        wording_evolution = self.compare_wording_evolution(old_report, new_report)

        self._emit_progress(progress_callback, 88, "正在分析议题演变")
        topic_attenuation = self.monitor_topic_attenuation(old_report, new_report)

        self._emit_progress(progress_callback, 96, "正在生成对比摘要")
        summary_overview = self._build_compare_summary(
            metadata=metadata,
            new_terms=new_terms,
            wording_evolution=wording_evolution,
            topic_attenuation=topic_attenuation,
        )

        self._emit_progress(progress_callback, 100, "双篇对比完成")
        return {
            "mode": "compare",
            "metadata": metadata,
            "summary_overview": summary_overview,
            "new_terms": new_terms,
            "wording_evolution": wording_evolution,
            "topic_attenuation": topic_attenuation,
            "old_report": {
                "paragraph_count": len(old_report.paragraphs),
                "sentence_count": len(old_report.sentences),
                "cleaned_text": old_report.cleaned_text,
            },
            "new_report": {
                "paragraph_count": len(new_report.paragraphs),
                "sentence_count": len(new_report.sentences),
                "cleaned_text": new_report.cleaned_text,
            },
        }

    def analyze_batch_reports(
        self,
        reports: list[dict[str, Any]],
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        normalized_reports: list[dict[str, str]] = []
        for index, item in enumerate(reports, start=1):
            text = str(item.get("text", "") or "")
            if not text.strip():
                continue
            name = str(item.get("name", "") or item.get("title", "") or f"文档 {index}")
            normalized_reports.append(
                {
                    "name": name,
                    "source_path": str(item.get("source_path", "") or ""),
                    "text": text,
                }
            )

        if not normalized_reports:
            raise ValueError("批量分析至少需要一份有效文档。")

        document_results: list[dict[str, Any]] = []
        total_documents = len(normalized_reports)
        base_percent = 5.0
        progress_span = 90.0

        for index, item in enumerate(normalized_reports, start=1):
            name = item["name"]
            start_percent = base_percent + (index - 1) * progress_span / total_documents
            segment_span = progress_span / total_documents
            self._emit_progress(
                progress_callback,
                int(round(start_percent)),
                f"正在分析 {index}/{total_documents}：{name}",
            )

            def item_progress(
                percent: int,
                message: str,
                *,
                _index: int = index,
                _name: str = name,
                _start: float = start_percent,
                _span: float = segment_span,
            ) -> None:
                bounded_percent = max(0, min(100, int(percent)))
                overall_percent = int(round(_start + _span * bounded_percent / 100.0))
                prefix = f"[{_index}/{total_documents}] {_name}"
                detail = f"{prefix}：{message}" if message else prefix
                self._emit_progress(progress_callback, overall_percent, detail)

            analysis = self.analyze_single_report(item["text"], progress_callback=item_progress)
            document_results.append(
                {
                    "name": name,
                    "source_path": item["source_path"],
                    "analysis": analysis,
                }
            )

        aggregate_new_terms = self._aggregate_weighted_items(
            [item["analysis"].get("new_terms", []) for item in document_results],
            label_key="term",
            output_key="term",
        )
        aggregate_topics = self._aggregate_weighted_items(
            [item["analysis"].get("core_topics", []) for item in document_results],
            label_key="topic",
            output_key="topic",
        )
        summary_overview = self._build_batch_summary(
            document_results,
            aggregate_new_terms,
            aggregate_topics,
        )

        self._emit_progress(progress_callback, 100, "批量分析完成")
        return {
            "mode": "batch",
            "summary_overview": summary_overview,
            "documents": document_results,
            "aggregate_new_terms": aggregate_new_terms,
            "aggregate_topics": aggregate_topics,
            "total_documents": len(document_results),
            "total_paragraphs": sum(item["analysis"].get("paragraph_count", 0) for item in document_results),
            "total_sentences": sum(item["analysis"].get("sentence_count", 0) for item in document_results),
        }
