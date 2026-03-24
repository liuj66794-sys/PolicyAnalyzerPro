from __future__ import annotations

import os
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any, Callable

from core.config import AppConfig, DEFAULT_CONFIG
from core.text_cleaner import TextCleaner

ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class PreparedText:
    raw_text: str
    cleaned_text: str
    paragraphs: list[str]
    sentences: list[str]
    metadata: dict[str, Any]


def initialize_runtime_environment(config: AppConfig | None = None) -> None:
    """
    Enforce fully offline transformer loading and keep CPU usage predictable.
    This helper is safe to call from both the main process and worker processes.
    """
    cfg = config or DEFAULT_CONFIG

    for key, value in cfg.offline_env.items():
        os.environ[key] = str(value)

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    try:
        import torch
    except ImportError:
        return

    try:
        torch.set_num_threads(cfg.torch_num_threads)
    except Exception:
        pass

    if hasattr(torch, "set_num_interop_threads"):
        try:
            torch.set_num_interop_threads(1)
        except Exception:
            pass


class PolicyReportAnalyzer:
    """
    Offline NLP analysis engine for long-form Chinese policy documents.
    """

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

        self._emit_progress(progress_callback, 55, "正在提取新提法")
        new_terms = self.extract_new_terms(prepared.cleaned_text)

        self._emit_progress(progress_callback, 80, "正在提取核心议题")
        core_topics = self.extract_core_topics(prepared.cleaned_text)

        self._emit_progress(progress_callback, 95, "正在生成分析摘要")
        summary_overview = self._build_single_summary(
            prepared=prepared,
            new_terms=new_terms,
            core_topics=core_topics,
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

            def item_progress(percent: int, message: str, *, _index: int = index, _name: str = name, _start: float = start_percent, _span: float = segment_span) -> None:
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

    def prepare_text(self, text: str) -> PreparedText:
        cleaned = self.cleaner.clean_text(text)
        paragraphs = [line.strip() for line in cleaned.splitlines() if line.strip()]
        sentences = self._split_sentences_from_cleaned(cleaned)
        metadata = self.extract_metadata(cleaned)
        return PreparedText(
            raw_text=text,
            cleaned_text=cleaned,
            paragraphs=paragraphs,
            sentences=sentences,
            metadata=metadata,
        )

    def extract_metadata(self, text: str) -> dict[str, Any]:
        if not text:
            return {"meeting_labels": [], "years": []}

        meeting_labels: list[str] = []
        seen_labels: set[str] = set()

        for pattern in self._metadata_patterns:
            for match in pattern.finditer(text):
                label = match.group(1).strip()
                if label not in seen_labels:
                    seen_labels.add(label)
                    meeting_labels.append(label)

        years: list[str] = []
        seen_years: set[str] = set()
        for match in re.finditer(r"(20\d{2}年)", text):
            year = match.group(1)
            if year not in seen_years:
                seen_years.add(year)
                years.append(year)

        return {
            "meeting_labels": meeting_labels,
            "years": years,
        }

    def extract_new_terms(self, text: str, top_k: int | None = None) -> list[dict[str, Any]]:
        cleaned = self.cleaner.clean_text(text)
        if not cleaned:
            return []

        self._ensure_jieba_ready()
        limit = top_k or self.config.tfidf_top_k
        raw_keywords = self._jieba_analyse.extract_tags(
            cleaned,
            topK=max(limit * 5, 50),
            withWeight=True,
            allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "eng"),
        )

        results: list[dict[str, Any]] = []
        seen_terms: set[str] = set()
        for term, weight in raw_keywords:
            normalized_term = term.strip()
            if normalized_term in seen_terms:
                continue
            if not self._is_valid_candidate_term(normalized_term):
                continue

            seen_terms.add(normalized_term)
            results.append(
                {
                    "term": normalized_term,
                    "weight": round(float(weight), 4),
                }
            )
            if len(results) >= limit:
                break

        return results

    def extract_core_topics(self, text: str, top_k: int | None = None) -> list[dict[str, Any]]:
        cleaned = self.cleaner.clean_text(text)
        if not cleaned:
            return []

        self._ensure_jieba_ready()
        limit = top_k or self.config.textrank_top_k
        raw_topics = self._jieba_analyse.textrank(
            cleaned,
            topK=max(limit * 3, 15),
            withWeight=True,
            allowPOS=("n", "nr", "ns", "nt", "nz", "vn", "v", "eng"),
        )

        topics: list[dict[str, Any]] = []
        seen_topics: set[str] = set()
        for topic, weight in raw_topics:
            normalized_topic = topic.strip()
            if normalized_topic in seen_topics:
                continue
            if not self._is_valid_candidate_term(normalized_topic):
                continue

            seen_topics.add(normalized_topic)
            topics.append(
                {
                    "topic": normalized_topic,
                    "weight": round(float(weight), 4),
                }
            )
            if len(topics) >= limit:
                break

        return topics

    def compare_wording_evolution(
        self,
        old_report: PreparedText | str,
        new_report: PreparedText | str,
        max_pairs: int = 20,
    ) -> dict[str, Any]:
        old_prepared = self._coerce_prepared_text(old_report)
        new_prepared = self._coerce_prepared_text(new_report)

        old_sentences = self._filter_comparable_sentences(old_prepared.sentences)
        new_sentences = self._filter_comparable_sentences(new_prepared.sentences)
        if not old_sentences or not new_sentences:
            return {
                "matched_pairs": [],
                "average_intensity": 0.0,
                "count": 0,
            }

        model = self._load_embedding_model()
        old_embeddings = model.encode(
            old_sentences,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        new_embeddings = model.encode(
            new_sentences,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        similarity_matrix = old_embeddings @ new_embeddings.T
        lower = self.config.sentence_similarity_lower
        upper = self.config.sentence_similarity_upper

        candidates: list[tuple[float, int, int]] = []
        for old_index, row in enumerate(similarity_matrix):
            for new_index, score in enumerate(row):
                similarity = float(score)
                if similarity < lower or similarity >= upper:
                    continue
                if old_sentences[old_index] == new_sentences[new_index]:
                    continue
                candidates.append((similarity, old_index, new_index))

        candidates.sort(key=lambda item: item[0], reverse=True)

        matched_pairs: list[dict[str, Any]] = []
        used_old: set[int] = set()
        used_new: set[int] = set()
        for similarity, old_index, new_index in candidates:
            if old_index in used_old or new_index in used_new:
                continue

            used_old.add(old_index)
            used_new.add(new_index)
            intensity = self._calculate_evolution_intensity(similarity)
            matched_pairs.append(
                {
                    "old_sentence": old_sentences[old_index],
                    "new_sentence": new_sentences[new_index],
                    "similarity": round(similarity, 4),
                    "evolution_intensity": round(intensity * 100, 2),
                    "strength_label": self._label_evolution_intensity(intensity),
                }
            )
            if len(matched_pairs) >= max_pairs:
                break

        average_intensity = (
            round(mean(pair["evolution_intensity"] for pair in matched_pairs), 2)
            if matched_pairs
            else 0.0
        )
        return {
            "matched_pairs": matched_pairs,
            "average_intensity": average_intensity,
            "count": len(matched_pairs),
        }

    def monitor_topic_attenuation(
        self,
        old_report: PreparedText | str,
        new_report: PreparedText | str,
    ) -> dict[str, Any]:
        old_prepared = self._coerce_prepared_text(old_report)
        new_prepared = self._coerce_prepared_text(new_report)

        old_topics = self.extract_core_topics(
            old_prepared.cleaned_text,
            top_k=self.config.textrank_top_k,
        )
        new_topics = self.extract_core_topics(
            new_prepared.cleaned_text,
            top_k=self.config.textrank_top_k,
        )
        if not old_topics and not new_topics:
            return {
                "core_topics_old": [],
                "core_topics_new": [],
                "changes": [],
                "added_topics": [],
                "retained_topics": [],
                "strengthened_topics": [],
                "removed_count": 0,
                "weakened_count": 0,
                "strengthened_count": 0,
            }

        old_token_count = max(self._estimate_token_count(old_prepared.cleaned_text), 1)
        new_token_count = max(self._estimate_token_count(new_prepared.cleaned_text), 1)

        old_topic_names = {item["topic"] for item in old_topics}
        changes: list[dict[str, Any]] = []
        added_topics: list[dict[str, Any]] = []
        retained_topics: list[dict[str, Any]] = []
        strengthened_topics: list[dict[str, Any]] = []
        removed_count = 0
        weakened_count = 0
        strengthened_count = 0

        for topic in old_topics:
            keyword = topic["topic"]
            old_density = self._calculate_term_density(
                old_prepared.cleaned_text,
                keyword,
                old_token_count,
            )
            new_density = self._calculate_term_density(
                new_prepared.cleaned_text,
                keyword,
                new_token_count,
            )

            if old_density <= 0:
                continue

            decay_ratio = max(0.0, 1.0 - (new_density / old_density))
            amplification_ratio = max(0.0, (new_density / old_density) - 1.0)
            status = "保留"
            if new_density == 0:
                status = "彻底删减"
                removed_count += 1
            elif decay_ratio >= self.config.weakening_ratio_threshold:
                status = "明显弱化"
                weakened_count += 1
            elif new_density > old_density * 1.2:
                status = "明显强化"
                strengthened_count += 1

            item = {
                "topic": keyword,
                "textrank_weight": topic["weight"],
                "old_density": round(old_density, 6),
                "new_density": round(new_density, 6),
                "decay_ratio": round(decay_ratio * 100, 2),
                "amplification_ratio": round(amplification_ratio * 100, 2),
                "status": status,
            }
            changes.append(item)

            if status in {"保留", "明显强化"} and new_density > 0:
                retained_topics.append(item)
            if status == "明显强化":
                strengthened_topics.append(item)

        for topic in new_topics:
            keyword = topic["topic"]
            if keyword in old_topic_names:
                continue

            old_density = self._calculate_term_density(
                old_prepared.cleaned_text,
                keyword,
                old_token_count,
            )
            new_density = self._calculate_term_density(
                new_prepared.cleaned_text,
                keyword,
                new_token_count,
            )
            if new_density <= 0:
                continue

            added_topics.append(
                {
                    "topic": keyword,
                    "new_weight": topic["weight"],
                    "old_density": round(old_density, 6),
                    "new_density": round(new_density, 6),
                    "delta_density": round(max(0.0, new_density - old_density), 6),
                    "status": "新增议题",
                }
            )

        changes.sort(key=lambda item: item["decay_ratio"], reverse=True)
        added_topics.sort(
            key=lambda item: (item["delta_density"], item["new_weight"]),
            reverse=True,
        )
        retained_topics.sort(
            key=lambda item: (item["new_density"], item["textrank_weight"]),
            reverse=True,
        )
        strengthened_topics.sort(
            key=lambda item: (item["amplification_ratio"], item["new_density"]),
            reverse=True,
        )

        return {
            "core_topics_old": old_topics,
            "core_topics_new": new_topics,
            "changes": changes,
            "added_topics": added_topics,
            "retained_topics": retained_topics,
            "strengthened_topics": strengthened_topics,
            "removed_count": removed_count,
            "weakened_count": weakened_count,
            "strengthened_count": strengthened_count,
        }

    def _build_single_summary(
        self,
        prepared: PreparedText,
        new_terms: list[dict[str, Any]],
        core_topics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        meeting_text = self._join_labels(
            prepared.metadata.get("meeting_labels", []),
            default="未识别会议规格",
        )
        headline = (
            f"本篇文本共 {len(prepared.paragraphs)} 段、{len(prepared.sentences)} 句，"
            f"识别会议规格为 {meeting_text}。"
        )

        takeaways: list[str] = []
        if new_terms:
            takeaways.append(
                f"高权重新提法集中在：{self._join_labels([item['term'] for item in new_terms[:5]], default='未识别')}。"
            )
        else:
            takeaways.append("未抽取到显著的新提法，文本可能以延续性表述为主。")

        if core_topics:
            takeaways.append(
                f"核心议题聚焦：{self._join_labels([item['topic'] for item in core_topics[:5]], default='未识别')}。"
            )
        else:
            takeaways.append("未抽取到稳定核心议题，建议检查文本长度或分词词典。")

        return {
            "headline": headline,
            "key_takeaways": takeaways,
            "top_new_terms": new_terms[:5],
            "top_topics": core_topics[:5],
        }

    def _build_compare_summary(
        self,
        metadata: dict[str, Any],
        new_terms: list[dict[str, Any]],
        wording_evolution: dict[str, Any],
        topic_attenuation: dict[str, Any],
    ) -> dict[str, Any]:
        changes = topic_attenuation.get("changes", [])
        added_topics = topic_attenuation.get("added_topics", [])
        retained_topics = topic_attenuation.get("retained_topics", [])
        strengthened_topics = topic_attenuation.get("strengthened_topics", [])
        removed_topics = [item for item in changes if item.get("status") == "彻底删减"]
        weakened_topics = [item for item in changes if item.get("status") == "明显弱化"]
        top_evolution_pairs = sorted(
            wording_evolution.get("matched_pairs", []),
            key=lambda item: float(item.get("evolution_intensity", 0.0)),
            reverse=True,
        )[:5]

        signal_score = min(
            100.0,
            len(removed_topics) * 24.0
            + len(weakened_topics) * 14.0
            + len(added_topics[:5]) * 9.0
            + len(strengthened_topics[:5]) * 6.0
            + min(wording_evolution.get("count", 0), 5) * 6.0,
        )
        if signal_score >= 65:
            signal_level = "高"
        elif signal_score >= 30:
            signal_level = "中"
        else:
            signal_level = "低"

        headline = (
            f"新稿识别到 {len(new_terms)} 个新增提法，"
            f"{topic_attenuation.get('removed_count', 0)} 项彻底删减，"
            f"{topic_attenuation.get('weakened_count', 0)} 项明显弱化，"
            f"{len(added_topics)} 个新增议题，"
            f"共捕获 {wording_evolution.get('count', 0)} 组措辞演变句对。"
        )

        key_findings: list[str] = []
        if removed_topics:
            key_findings.append(
                f"删减信号最强的议题包括：{self._join_labels([item['topic'] for item in removed_topics[:3]], default='未识别')}。"
            )
        if weakened_topics:
            key_findings.append(
                f"显著弱化的议题包括：{self._join_labels([item['topic'] for item in weakened_topics[:3]], default='未识别')}。"
            )
        if added_topics:
            key_findings.append(
                f"新增议题主要集中在：{self._join_labels([item['topic'] for item in added_topics[:3]], default='未识别')}。"
            )
        if retained_topics:
            key_findings.append(
                f"持续保留的议题包括：{self._join_labels([item['topic'] for item in retained_topics[:3]], default='未识别')}。"
            )
        if new_terms:
            key_findings.append(
                f"新增提法最突出的关键词为：{self._join_labels([item['term'] for item in new_terms[:5]], default='未识别')}。"
            )
        if top_evolution_pairs:
            strongest = top_evolution_pairs[0]
            key_findings.append(
                "措辞微调最明显的句对演变强度为 "
                f"{strongest.get('evolution_intensity', 0.0)}%，"
                f"相似度 {strongest.get('similarity', 0.0)}。"
            )

        old_meetings = metadata.get("old", {}).get("meeting_labels", [])
        new_meetings = metadata.get("new", {}).get("meeting_labels", [])
        if old_meetings != new_meetings:
            key_findings.append(
                f"新旧文本会议规格存在差异：旧稿为 {self._join_labels(old_meetings, default='未识别')}，新稿为 {self._join_labels(new_meetings, default='未识别')}。"
            )

        if not key_findings:
            key_findings.append("本轮对比未出现强烈的结构性变化信号。")

        return {
            "signal_score": round(signal_score, 2),
            "signal_level": signal_level,
            "headline": headline,
            "key_findings": key_findings,
            "top_removed_topics": removed_topics[:5],
            "top_weakened_topics": weakened_topics[:5],
            "top_added_topics": added_topics[:5],
            "top_retained_topics": retained_topics[:5],
            "top_strengthened_topics": strengthened_topics[:5],
            "top_new_terms": new_terms[:5],
            "top_evolution_pairs": top_evolution_pairs,
        }

    def _build_batch_summary(
        self,
        document_results: list[dict[str, Any]],
        aggregate_new_terms: list[dict[str, Any]],
        aggregate_topics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_documents = len(document_results)
        total_paragraphs = sum(item["analysis"].get("paragraph_count", 0) for item in document_results)
        total_sentences = sum(item["analysis"].get("sentence_count", 0) for item in document_results)

        meeting_counts: dict[str, int] = {}
        for item in document_results:
            metadata = item["analysis"].get("metadata", {})
            for label in metadata.get("meeting_labels", []):
                meeting_counts[label] = meeting_counts.get(label, 0) + 1
        top_meetings = [
            label
            for label, _ in sorted(
                meeting_counts.items(),
                key=lambda pair: (pair[1], pair[0]),
                reverse=True,
            )[:3]
        ]

        longest_documents = sorted(
            document_results,
            key=lambda item: item["analysis"].get("paragraph_count", 0),
            reverse=True,
        )[:3]

        key_findings: list[str] = [
            f"共分析 {total_documents} 份文档，累计 {total_paragraphs} 段，{total_sentences} 句。"
        ]
        if top_meetings:
            key_findings.append(
                f"出现频率最高的会议规格包括：{self._join_labels(top_meetings, default='未识别')}。"
            )
        if aggregate_new_terms:
            key_findings.append(
                f"批量高频新提法包括：{self._join_labels([item['term'] for item in aggregate_new_terms[:5]], default='未识别')}。"
            )
        if aggregate_topics:
            key_findings.append(
                f"批量高频核心议题包括：{self._join_labels([item['topic'] for item in aggregate_topics[:5]], default='未识别')}。"
            )
        if longest_documents:
            key_findings.append(
                "篇幅较长的文档包括："
                + self._join_labels(
                    [
                        f"{item['name']}（{item['analysis'].get('paragraph_count', 0)} 段）"
                        for item in longest_documents
                    ],
                    default='未识别',
                )
                + "。"
            )

        headline = (
            f"批量分析共覆盖 {total_documents} 份文档，"
            f"聚合出 {len(aggregate_new_terms)} 个高频新提法和 {len(aggregate_topics)} 个高频核心议题。"
        )
        return {
            "headline": headline,
            "key_findings": key_findings,
            "top_new_terms": aggregate_new_terms[:5],
            "top_topics": aggregate_topics[:5],
        }

    def _aggregate_weighted_items(
        self,
        item_groups: list[list[dict[str, Any]]],
        label_key: str,
        output_key: str,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        totals: dict[str, float] = {}
        document_counts: dict[str, int] = {}

        for group in item_groups:
            seen_in_document: set[str] = set()
            for item in group:
                label = str(item.get(label_key, "") or "").strip()
                if not label:
                    continue
                weight = float(
                    item.get(
                        "weight",
                        item.get("textrank_weight", item.get("new_weight", 0.0)),
                    )
                    or 0.0
                )
                totals[label] = totals.get(label, 0.0) + weight
                if label not in seen_in_document:
                    document_counts[label] = document_counts.get(label, 0) + 1
                    seen_in_document.add(label)

        results = [
            {
                output_key: label,
                "weight": round(total_weight, 4),
                "document_count": document_counts.get(label, 0),
            }
            for label, total_weight in totals.items()
        ]
        results.sort(
            key=lambda item: (item["weight"], item["document_count"], item[output_key]),
            reverse=True,
        )
        return results[:top_k]

    def _ensure_jieba_ready(self) -> None:
        if self._jieba is not None and self._jieba_analyse is not None:
            return

        try:
            import jieba
            import jieba.analyse
        except ImportError as exc:
            raise RuntimeError("缺少 jieba 依赖，请先安装 jieba。") from exc

        self._jieba = jieba
        self._jieba_analyse = jieba.analyse

        user_dict_path = self.config.resolved_custom_dictionary_path
        if os.path.exists(user_dict_path):
            try:
                self._jieba.load_userdict(user_dict_path)
            except Exception:
                pass

    def _load_embedding_model(self):
        if self._embedding_model is not None:
            return self._embedding_model

        initialize_runtime_environment(self.config)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "缺少 sentence-transformers 依赖，请先安装 sentence-transformers。"
            ) from exc

        self._embedding_model = SentenceTransformer(
            self.config.resolved_model_dir,
            device="cpu",
            local_files_only=self.config.local_files_only,
        )
        return self._embedding_model

    def _split_sentences_from_cleaned(self, cleaned_text: str) -> list[str]:
        if not cleaned_text:
            return []
        chunks = re.split(r"(?<=[。！？；;!?])", cleaned_text)
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    def _coerce_prepared_text(self, value: PreparedText | str) -> PreparedText:
        if isinstance(value, PreparedText):
            return value
        return self.prepare_text(value)

    def _filter_comparable_sentences(self, sentences: list[str]) -> list[str]:
        filtered: list[str] = []
        for sentence in sentences:
            normalized = sentence.strip()
            if len(normalized) < 8:
                continue
            if re.fullmatch(r"[0-9一二三四五六七八九十百零两年月日、，。；：:（）()\-\s]+", normalized):
                continue
            filtered.append(normalized)
        return filtered

    def _estimate_token_count(self, text: str) -> int:
        self._ensure_jieba_ready()
        tokens = [token.strip() for token in self._jieba.lcut(text) if token.strip()]
        return len(tokens)

    def _calculate_term_density(self, text: str, term: str, token_count: int) -> float:
        if not text or not term or token_count <= 0:
            return 0.0
        occurrences = len(re.findall(re.escape(term), text))
        return occurrences / token_count

    def _is_valid_candidate_term(self, term: str) -> bool:
        if len(term) < 2:
            return False
        if term in self._blocked_terms:
            return False
        if re.fullmatch(r"[0-9A-Za-z\W_]+", term):
            return False
        return True

    def _calculate_evolution_intensity(self, similarity: float) -> float:
        lower = self.config.sentence_similarity_lower
        upper = self.config.sentence_similarity_upper
        if upper <= lower:
            return 0.0
        normalized = (upper - similarity) / (upper - lower)
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def _label_evolution_intensity(intensity: float) -> str:
        if intensity >= 0.67:
            return "高"
        if intensity >= 0.34:
            return "中"
        return "低"

    @staticmethod
    def _join_labels(values: list[str], default: str) -> str:
        if not values:
            return default
        return "、".join(values)

    @staticmethod
    def _emit_progress(
        callback: ProgressCallback | None,
        percent: int,
        message: str,
    ) -> None:
        if callback is not None:
            callback(percent, message)
