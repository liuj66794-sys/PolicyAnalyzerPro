from __future__ import annotations

from typing import Any

from .types import PreparedText, ProgressCallback


class SummaryMixin:
    def _build_single_summary(
        self,
        prepared: PreparedText,
        new_terms: list[dict[str, Any]],
        core_topics: list[dict[str, Any]],
        text_structure: dict[str, Any] | None = None,
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

        if text_structure:
            avg_paragraph = round(text_structure.get("avg_paragraph_length", 0), 1)
            avg_sentence = round(text_structure.get("avg_sentence_length", 0), 1)
            takeaways.append(f"文本结构：平均段落长度 {avg_paragraph} 字，平均句子长度 {avg_sentence} 字。")

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
