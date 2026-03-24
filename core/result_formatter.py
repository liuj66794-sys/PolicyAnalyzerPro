from __future__ import annotations

import json
from datetime import datetime
from html import escape
from typing import Any


class AnalysisResultFormatter:
    def to_markdown(self, result: dict[str, Any]) -> str:
        mode = result.get("mode")
        if mode == "compare":
            return self._format_compare_markdown(result)
        if mode == "batch":
            return self._format_batch_markdown(result)
        return self._format_single_markdown(result)

    def to_html_report(self, result: dict[str, Any]) -> str:
        rendered_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode = result.get("mode")
        if mode == "compare":
            title = "PolicyAnalyzerPro - 双篇比对"
            body = self._format_compare_html(result, rendered_at)
        elif mode == "batch":
            title = "PolicyAnalyzerPro - 批量分析"
            body = self._format_batch_html(result, rendered_at)
        else:
            title = "PolicyAnalyzerPro - 单篇分析"
            body = self._format_single_html(result, rendered_at)

        return (
            '<!DOCTYPE html>'
            "<html lang='zh-CN'>"
            '<head>'
            "<meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{escape(title)}</title>"
            f"<style>{self._build_html_styles()}</style>"
            '</head>'
            f"<body>{body}</body>"
            '</html>'
        )

    def to_json_text(self, result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, indent=2)

    def build_export_base_name(self, result: dict[str, Any]) -> str:
        mode = result.get("mode", "single")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"policy_analysis_{mode}_{timestamp}"

    def _format_single_markdown(self, result: dict[str, Any]) -> str:
        metadata = result.get("metadata", {})
        summary = result.get("summary_overview", {})
        meetings = metadata.get("meeting_labels", []) or ["未识别"]
        years = metadata.get("years", []) or ["未识别"]
        new_terms = result.get("new_terms", [])
        topics = result.get("core_topics", [])

        sections = [
            "# 单篇分析结果",
            "",
            "## 摘要页",
            f"- 结论摘要：{summary.get('headline', '本次分析已完成。')}",
            f"- 会议规格：{'、'.join(meetings)}",
            f"- 年份：{'、'.join(years)}",
            f"- 文本规模：{result.get('paragraph_count', 0)} 段，{result.get('sentence_count', 0)} 句",
            "",
            "### 关键观察",
        ]
        sections.extend(self._format_bullets(summary.get("key_takeaways", []), "本篇文本暂无额外关键信号。"))
        sections.append("")
        sections.append("## 新提法 Top 10")
        sections.extend(self._format_weighted_items(new_terms, "term", "未提取到明显新提法。"))
        sections.append("")
        sections.append("## 核心议题 Top 10")
        sections.extend(self._format_weighted_items(topics, "topic", "未提取到核心议题。"))
        note_sections = self._format_import_preview_notes_markdown(result.get("import_preview_notes", []))
        if note_sections:
            sections.extend([""] + note_sections)
        return "\n".join(sections)

    def _format_compare_markdown(self, result: dict[str, Any]) -> str:
        metadata = result.get("metadata", {})
        summary = result.get("summary_overview", {})
        old_meta = metadata.get("old", {})
        new_meta = metadata.get("new", {})
        new_terms = result.get("new_terms", [])
        wording = result.get("wording_evolution", {})
        attenuation = result.get("topic_attenuation", {})

        sections = [
            "# 双篇比对结果",
            "",
            "## 摘要页",
            f"- 总体信号等级：{summary.get('signal_level', '低')}",
            f"- 总体信号分值：{summary.get('signal_score', 0.0)} / 100",
            f"- 核心结论：{summary.get('headline', '本轮对比已完成。')}",
            "",
            "### 关键发现",
        ]
        sections.extend(self._format_bullets(summary.get("key_findings", []), "未检测到突出的结构性变化。"))
        sections.extend(
            [
                "",
                "## 元信息",
                f"- 旧稿会议规格：{self._join_or_default(old_meta.get('meeting_labels'))}",
                f"- 新稿会议规格：{self._join_or_default(new_meta.get('meeting_labels'))}",
                f"- 旧稿年份：{self._join_or_default(old_meta.get('years'))}",
                f"- 新稿年份：{self._join_or_default(new_meta.get('years'))}",
                "",
                "## 新增提法 Top 10",
            ]
        )
        sections.extend(self._format_weighted_items(new_terms, "term", "未识别到明显新增提法。"))
        sections.extend(["", "## 新增议题排行"])
        sections.extend(self._format_topic_rankings(summary.get("top_added_topics", []), "new_weight", "未识别到新增议题。"))
        sections.extend(["", "## 保留议题排行"])
        sections.extend(self._format_topic_rankings(summary.get("top_retained_topics", []), "textrank_weight", "未识别到稳定保留议题。"))
        sections.extend(["", "## 删减议题排行"])
        sections.extend(self._format_change_ranking_table(attenuation.get("changes", []), "未检测到可比较的核心议题变化。"))
        sections.extend(
            [
                "",
                "## 重点措辞演变句对",
                f"- 捕获到 {wording.get('count', 0)} 组潜在演变句对，平均演变强度 {wording.get('average_intensity', 0.0)}%。",
            ]
        )
        sections.extend(self._format_evolution_pairs(summary.get("top_evolution_pairs") or wording.get("matched_pairs", []), "没有捕获到位于 0.70 到 0.95 之间的相似句对。"))
        sections.extend(
            [
                "",
                "## 删减与强化概览",
                f"- 彻底删减：{attenuation.get('removed_count', 0)} 项",
                f"- 明显弱化：{attenuation.get('weakened_count', 0)} 项",
                f"- 明显强化：{attenuation.get('strengthened_count', 0)} 项",
            ]
        )
        note_sections = self._format_import_preview_notes_markdown(result.get("import_preview_notes", []))
        if note_sections:
            sections.extend([""] + note_sections)
        return "\n".join(sections)

    def _format_batch_markdown(self, result: dict[str, Any]) -> str:
        documents = result.get("documents", [])
        summary = result.get("summary_overview", {})
        aggregate_new_terms = result.get("aggregate_new_terms", [])
        aggregate_topics = result.get("aggregate_topics", [])

        sections = [
            "# 批量分析结果",
            "",
            "## 摘要页",
            f"- 批量文档数：{result.get('total_documents', len(documents))}",
            f"- 总段落数：{result.get('total_paragraphs', 0)}",
            f"- 总句子数：{result.get('total_sentences', 0)}",
            f"- 结论摘要：{summary.get('headline', '批量分析已完成。')}",
            "",
            "### 关键发现",
        ]
        sections.extend(self._format_bullets(summary.get("key_findings", []), "未生成批量关键发现。"))
        sections.extend(["", "## 批量高频新提法"])
        sections.extend(self._format_weighted_items(aggregate_new_terms, "term", "未提取到批量高频新提法。"))
        sections.extend(["", "## 批量高频核心议题"])
        sections.extend(self._format_weighted_items(aggregate_topics, "topic", "未提取到批量高频核心议题。"))
        sections.extend([
            "",
            "## 文档概览",
            "| 序号 | 文档 | 会议规格 | 段落数 | 句子数 | 结论摘要 |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for index, document in enumerate(documents, start=1):
            analysis = document.get("analysis", {})
            metadata = analysis.get("metadata", {})
            doc_summary = analysis.get("summary_overview", {})
            sections.append(
                f"| {index} | {document.get('name', '')} | {self._join_or_default(metadata.get('meeting_labels'))} | {analysis.get('paragraph_count', 0)} | {analysis.get('sentence_count', 0)} | {doc_summary.get('headline', '')} |"
            )

        sections.extend(["", "## 分文档结果"])
        for index, document in enumerate(documents, start=1):
            analysis = document.get("analysis", {})
            metadata = analysis.get("metadata", {})
            doc_summary = analysis.get("summary_overview", {})
            sections.extend(
                [
                    "",
                    f"### {index}. {document.get('name', '')}",
                    f"- 来源：{document.get('source_path', '未记录') or '未记录'}",
                    f"- 会议规格：{self._join_or_default(metadata.get('meeting_labels'))}",
                    f"- 年份：{self._join_or_default(metadata.get('years'))}",
                    f"- 文本规模：{analysis.get('paragraph_count', 0)} 段，{analysis.get('sentence_count', 0)} 句",
                    f"- 结论摘要：{doc_summary.get('headline', '本篇分析已完成。')}",
                ]
            )
            takeaways = doc_summary.get("key_takeaways", []) or ["未生成关键观察。"]
            sections.extend(f"- 关键观察：{item}" for item in takeaways[:3])
            new_terms = analysis.get("new_terms", [])
            core_topics = analysis.get("core_topics", [])
            if new_terms:
                sections.append(
                    f"- 新提法：{self._join_or_default([item.get('term', '') for item in new_terms[:5]])}"
                )
            if core_topics:
                sections.append(
                    f"- 核心议题：{self._join_or_default([item.get('topic', '') for item in core_topics[:5]])}"
                )

        note_sections = self._format_import_preview_notes_markdown(result.get("import_preview_notes", []))
        if note_sections:
            sections.extend([""] + note_sections)
        return "\n".join(sections)

    def _format_single_html(self, result: dict[str, Any], rendered_at: str) -> str:
        summary = result.get("summary_overview", {})
        metadata = result.get("metadata", {})
        return (
            self._build_cover_page(
                title="单篇分析报告",
                subtitle=summary.get("headline", "本次分析已完成。"),
                rendered_at=rendered_at,
                badge_label="离线分析",
            )
            + self._build_page(
                "执行摘要",
                self._build_html_findings("关键观察", summary.get("key_takeaways", []), "本篇文本暂无额外关键信号。")
                + self._build_html_metric_cards(
                    [
                        ("会议规格", self._join_or_default(metadata.get("meeting_labels"))),
                        ("年份", self._join_or_default(metadata.get("years"))),
                        ("段落数", str(result.get("paragraph_count", 0))),
                        ("句子数", str(result.get("sentence_count", 0))),
                    ]
                ),
                page_class="summary-page",
            )
            + self._build_page(
                "证据页",
                self._build_html_weighted_section("新提法 Top 10", result.get("new_terms", []), "term", "未提取到明显新提法。")
                + self._build_html_weighted_section("核心议题 Top 10", result.get("core_topics", []), "topic", "未提取到核心议题。"),
            )
            + self._build_html_import_preview_notes_page(result.get("import_preview_notes", []))
        )

    def _format_compare_html(self, result: dict[str, Any], rendered_at: str) -> str:
        summary = result.get("summary_overview", {})
        metadata = result.get("metadata", {})
        old_meta = metadata.get("old", {})
        new_meta = metadata.get("new", {})
        attenuation = result.get("topic_attenuation", {})
        wording = result.get("wording_evolution", {})

        return (
            self._build_cover_page(
                title="双篇比对报告",
                subtitle=summary.get("headline", "本轮对比已完成。"),
                rendered_at=rendered_at,
                badge_label=f"总体信号 {summary.get('signal_level', '低')}",
            )
            + self._build_page(
                "执行摘要",
                self._build_html_metric_cards(
                    [
                        ("总体信号等级", str(summary.get("signal_level", "低"))),
                        ("总体信号分值", f"{summary.get('signal_score', 0.0)} / 100"),
                        ("彻底删减", str(attenuation.get("removed_count", 0))),
                        ("明显弱化", str(attenuation.get("weakened_count", 0))),
                    ]
                )
                + self._build_html_findings("关键发现", summary.get("key_findings", []), "未检测到突出的结构性变化。")
                + self._build_html_metric_cards(
                    [
                        ("旧稿会议规格", self._join_or_default(old_meta.get("meeting_labels"))),
                        ("新稿会议规格", self._join_or_default(new_meta.get("meeting_labels"))),
                        ("旧稿年份", self._join_or_default(old_meta.get("years"))),
                        ("新稿年份", self._join_or_default(new_meta.get("years"))),
                    ]
                ),
                page_class="summary-page",
            )
            + self._build_page(
                "议题演变",
                self._build_html_weighted_section("新增提法 Top 10", result.get("new_terms", []), "term", "未识别到明显新增提法。")
                + self._build_html_topic_table("新增议题排行", summary.get("top_added_topics", []), "new_weight", "未识别到新增议题。")
                + self._build_html_topic_table("保留议题排行", summary.get("top_retained_topics", []), "textrank_weight", "未识别到稳定保留议题。")
                + self._build_html_change_table("删减议题排行", attenuation.get("changes", []), "未检测到可比较的核心议题变化。"),
            )
            + self._build_page(
                "措辞演变证据",
                self._build_html_evolution_section(
                    "重点措辞演变句对",
                    summary.get("top_evolution_pairs") or wording.get("matched_pairs", []),
                    wording.get("count", 0),
                    wording.get("average_intensity", 0.0),
                ),
            )
            + self._build_html_import_preview_notes_page(result.get("import_preview_notes", []))
        )

    def _format_batch_html(self, result: dict[str, Any], rendered_at: str) -> str:
        summary = result.get("summary_overview", {})
        documents = result.get("documents", [])
        return (
            self._build_cover_page(
                title="批量分析报告",
                subtitle=summary.get("headline", "批量分析已完成。"),
                rendered_at=rendered_at,
                badge_label=f"批量文档 {result.get('total_documents', len(documents))} 份",
            )
            + self._build_page(
                "执行摘要",
                self._build_html_metric_cards(
                    [
                        ("批量文档数", str(result.get("total_documents", len(documents)))),
                        ("总段落数", str(result.get("total_paragraphs", 0))),
                        ("总句子数", str(result.get("total_sentences", 0))),
                        ("高频新提法", str(len(result.get("aggregate_new_terms", [])))),
                    ]
                )
                + self._build_html_findings("关键发现", summary.get("key_findings", []), "未生成批量关键发现。"),
                page_class="summary-page",
            )
            + self._build_page(
                "聚合观察",
                self._build_html_weighted_section("批量高频新提法", result.get("aggregate_new_terms", []), "term", "未提取到批量高频新提法。")
                + self._build_html_weighted_section("批量高频核心议题", result.get("aggregate_topics", []), "topic", "未提取到批量高频核心议题。")
                + self._build_html_batch_document_table(documents),
            )
            + self._build_page(
                "分文档结果",
                self._build_html_batch_document_cards(documents),
            )
            + self._build_html_import_preview_notes_page(result.get("import_preview_notes", []))
        )

    def _format_weighted_items(self, items: list[dict[str, Any]], key_name: str, empty_text: str) -> list[str]:
        if not items:
            return [f"- {empty_text}"]
        lines: list[str] = []
        for index, item in enumerate(items[:10], start=1):
            label = item.get(key_name, "")
            weight = item.get("weight", item.get("textrank_weight", item.get("new_weight", 0.0)))
            lines.append(f"{index}. {label}（权重 {weight}）")
        return lines

    def _format_topic_rankings(self, items: list[dict[str, Any]], weight_key: str, empty_text: str) -> list[str]:
        if not items:
            return [f"- {empty_text}"]
        lines: list[str] = []
        for index, item in enumerate(items[:10], start=1):
            lines.append(
                f"{index}. {item.get('topic', '')}（权重 {item.get(weight_key, 0.0)}，旧稿密度 {item.get('old_density', 0.0)}，新稿密度 {item.get('new_density', 0.0)}）"
            )
        return lines

    def _format_change_ranking_table(self, changes: list[dict[str, Any]], empty_text: str) -> list[str]:
        if not changes:
            return [f"- {empty_text}"]
        lines = [
            "| 排名 | 议题 | 状态 | 衰减幅度 | 强化幅度 | 旧稿密度 | 新稿密度 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, item in enumerate(changes[:10], start=1):
            lines.append(
                f"| {index} | {item.get('topic', '')} | {item.get('status', '')} | {item.get('decay_ratio', 0.0)}% | {item.get('amplification_ratio', 0.0)}% | {item.get('old_density', 0.0)} | {item.get('new_density', 0.0)} |"
            )
        return lines

    def _format_evolution_pairs(self, pairs: list[dict[str, Any]], empty_text: str) -> list[str]:
        if not pairs:
            return [f"- {empty_text}"]
        lines: list[str] = []
        for index, pair in enumerate(pairs[:5], start=1):
            lines.extend(
                [
                    f"### 句对 {index}",
                    f"- 相似度：{pair.get('similarity', 0.0)}",
                    f"- 演变强度：{pair.get('evolution_intensity', 0.0)}%（{pair.get('strength_label', '低')}）",
                    f"> 旧稿：{pair.get('old_sentence', '')}",
                    f"> 新稿：{pair.get('new_sentence', '')}",
                    "",
                ]
            )
        return lines[:-1] if lines else lines

    def _format_import_preview_notes_markdown(self, notes: list[str]) -> list[str]:
        if not notes:
            return []
        sections = ["## 导入提示说明"]
        for index, note in enumerate(notes, start=1):
            sections.extend(
                [
                    "",
                    f"### 说明 {index}",
                    "```text",
                    note,
                    "```",
                ]
            )
        return sections

    def _build_html_import_preview_notes_page(self, notes: list[str]) -> str:
        if not notes:
            return ""
        cards = []
        for index, note in enumerate(notes, start=1):
            cards.append(
                '<div class="note-card">'
                f'<div class="note-card-title">说明 {index}</div>'
                f'<pre class="note-pre">{escape(note)}</pre>'
                '</div>'
            )
        return self._build_page("导入提示说明", "".join(cards))

    def _format_bullets(self, items: list[str], empty_text: str) -> list[str]:
        if not items:
            return [f"- {empty_text}"]
        return [f"- {item}" for item in items]

    def _build_cover_page(self, title: str, subtitle: str, rendered_at: str, badge_label: str) -> str:
        return (
            "<section class=\"page cover-page\">"
            "<div class=\"cover-shell\">"
            "<div class=\"cover-kicker\">PolicyAnalyzerPro</div>"
            f"<div class=\"cover-badge\">{escape(badge_label)}</div>"
            f"<h1>{escape(title)}</h1>"
            f"<p class=\"cover-subtitle\">{escape(subtitle)}</p>"
            "<div class=\"cover-meta\">"
            f"<span>生成时间：{escape(rendered_at)}</span>"
            "<span>运行模式：彻底离线</span>"
            "</div>"
            "</div>"
            "</section>"
        )

    def _build_page(self, page_title: str, inner_html: str, page_class: str = "") -> str:
        class_name = "page"
        if page_class:
            class_name += f" {page_class}"
        return (
            f"<section class=\"{class_name}\">"
            f"<div class=\"page-header\"><h2>{escape(page_title)}</h2></div>"
            f"{inner_html}"
            "</section>"
        )

    def _build_html_metric_cards(self, metrics: list[tuple[str, str]]) -> str:
        cards = []
        for label, value in metrics:
            cards.append(
                "<div class=\"metric-card\">"
                f"<div class=\"metric-label\">{escape(label)}</div>"
                f"<div class=\"metric-value\">{escape(value)}</div>"
                "</div>"
            )
        return f"<div class=\"metric-grid\">{''.join(cards)}</div>"

    def _build_html_findings(self, title: str, findings: list[str], empty_text: str) -> str:
        if not findings:
            findings = [empty_text]
        items = "".join(f"<li>{escape(item)}</li>" for item in findings)
        return (
            "<section class=\"panel\">"
            f"<h3>{escape(title)}</h3>"
            f"<ul class=\"finding-list\">{items}</ul>"
            "</section>"
        )

    def _build_html_weighted_section(self, title: str, items: list[dict[str, Any]], key_name: str, empty_text: str) -> str:
        if not items:
            return (
                "<section class=\"panel\">"
                f"<h3>{escape(title)}</h3>"
                f"<p class=\"muted\">{escape(empty_text)}</p>"
                "</section>"
            )
        rows = []
        for index, item in enumerate(items[:10], start=1):
            label = escape(str(item.get(key_name, "")))
            weight = escape(str(item.get("weight", item.get("textrank_weight", item.get("new_weight", 0.0)))))
            rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{label}</td>"
                f"<td>{weight}</td>"
                "</tr>"
            )
        return (
            "<section class=\"panel\">"
            f"<h3>{escape(title)}</h3>"
            "<table class=\"report-table\">"
            "<thead><tr><th>排名</th><th>条目</th><th>权重</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</section>"
        )

    def _build_html_topic_table(self, title: str, items: list[dict[str, Any]], weight_key: str, empty_text: str) -> str:
        if not items:
            return (
                "<section class=\"panel\">"
                f"<h3>{escape(title)}</h3>"
                f"<p class=\"muted\">{escape(empty_text)}</p>"
                "</section>"
            )
        rows = []
        for index, item in enumerate(items[:10], start=1):
            rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{escape(str(item.get('topic', '')))}</td>"
                f"<td>{escape(str(item.get(weight_key, 0.0)))}</td>"
                f"<td>{escape(str(item.get('old_density', 0.0)))}</td>"
                f"<td>{escape(str(item.get('new_density', 0.0)))}</td>"
                "</tr>"
            )
        return (
            "<section class=\"panel\">"
            f"<h3>{escape(title)}</h3>"
            "<table class=\"report-table\">"
            "<thead><tr><th>排名</th><th>议题</th><th>权重</th><th>旧稿密度</th><th>新稿密度</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</section>"
        )

    def _build_html_change_table(self, title: str, changes: list[dict[str, Any]], empty_text: str) -> str:
        if not changes:
            return (
                "<section class=\"panel\">"
                f"<h3>{escape(title)}</h3>"
                f"<p class=\"muted\">{escape(empty_text)}</p>"
                "</section>"
            )
        rows = []
        for index, item in enumerate(changes[:10], start=1):
            rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{escape(str(item.get('topic', '')))}</td>"
                f"<td>{escape(str(item.get('status', '')))}</td>"
                f"<td>{escape(str(item.get('decay_ratio', 0.0)))}%</td>"
                f"<td>{escape(str(item.get('amplification_ratio', 0.0)))}%</td>"
                f"<td>{escape(str(item.get('old_density', 0.0)))}</td>"
                f"<td>{escape(str(item.get('new_density', 0.0)))}</td>"
                "</tr>"
            )
        return (
            "<section class=\"panel\">"
            f"<h3>{escape(title)}</h3>"
            "<table class=\"report-table\">"
            "<thead><tr><th>排名</th><th>议题</th><th>状态</th><th>衰减幅度</th><th>强化幅度</th><th>旧稿密度</th><th>新稿密度</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</section>"
        )

    def _build_html_evolution_section(self, title: str, pairs: list[dict[str, Any]], count: int, average_intensity: float) -> str:
        if not pairs:
            return (
                "<section class=\"panel\">"
                f"<h3>{escape(title)}</h3>"
                f"<p class=\"muted\">共捕获 {escape(str(count))} 组潜在演变句对，平均演变强度 {escape(str(average_intensity))}%。</p>"
                "<p class=\"muted\">没有捕获到位于 0.70 到 0.95 之间的相似句对。</p>"
                "</section>"
            )
        cards = []
        for pair in pairs[:5]:
            cards.append(
                "<div class=\"pair-card\">"
                f"<div class=\"pair-meta\">相似度 {escape(str(pair.get('similarity', 0.0)))} | 演变强度 {escape(str(pair.get('evolution_intensity', 0.0)))}% | 强度等级 {escape(str(pair.get('strength_label', '低')))}</div>"
                f"<div class=\"pair-text\"><strong>旧稿：</strong>{escape(str(pair.get('old_sentence', '')))}</div>"
                f"<div class=\"pair-text\"><strong>新稿：</strong>{escape(str(pair.get('new_sentence', '')))}</div>"
                "</div>"
            )
        return (
            "<section class=\"panel\">"
            f"<h3>{escape(title)}</h3>"
            f"<p class=\"muted\">共捕获 {escape(str(count))} 组潜在演变句对，平均演变强度 {escape(str(average_intensity))}%。</p>"
            f"<div class=\"pair-grid\">{''.join(cards)}</div>"
            "</section>"
        )

    def _build_html_batch_document_table(self, documents: list[dict[str, Any]]) -> str:
        if not documents:
            return (
                "<section class='panel'>"
                "<h3>文档概览</h3>"
                "<p class='muted'>当前没有可展示的批量文档。</p>"
                "</section>"
            )

        rows = []
        for index, document in enumerate(documents, start=1):
            analysis = document.get("analysis", {})
            metadata = analysis.get("metadata", {})
            summary = analysis.get("summary_overview", {})
            rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{escape(str(document.get('name', '')))}</td>"
                f"<td>{escape(self._join_or_default(metadata.get('meeting_labels')))}</td>"
                f"<td>{escape(str(analysis.get('paragraph_count', 0)))}</td>"
                f"<td>{escape(str(analysis.get('sentence_count', 0)))}</td>"
                f"<td>{escape(str(summary.get('headline', '本篇分析已完成。')))}</td>"
                "</tr>"
            )
        return (
            "<section class='panel'>"
            "<h3>文档概览</h3>"
            "<table class='report-table'>"
            "<thead><tr><th>序号</th><th>文档</th><th>会议规格</th><th>段落数</th><th>句子数</th><th>结论摘要</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
            "</section>"
        )

    def _build_html_batch_document_cards(self, documents: list[dict[str, Any]]) -> str:
        if not documents:
            return "<p class='muted'>当前没有可展示的批量文档。</p>"

        cards = []
        for index, document in enumerate(documents, start=1):
            analysis = document.get("analysis", {})
            metadata = analysis.get("metadata", {})
            summary = analysis.get("summary_overview", {})
            takeaways = summary.get("key_takeaways", []) or ["未生成关键观察。"]
            new_terms = "、".join(item.get("term", "") for item in analysis.get("new_terms", [])[:5] if item.get("term")) or "未提取"
            core_topics = "、".join(item.get("topic", "") for item in analysis.get("core_topics", [])[:5] if item.get("topic")) or "未提取"
            takeaway_items = "".join(f"<li>{escape(str(item))}</li>" for item in takeaways[:3])
            cards.append(
                "<section class='panel batch-doc-card'>"
                f"<h3>{index}. {escape(str(document.get('name', '')))}</h3>"
                f"<p class='muted'>来源：{escape(str(document.get('source_path', '未记录') or '未记录'))}</p>"
                f"<p><strong>会议规格：</strong>{escape(self._join_or_default(metadata.get('meeting_labels')))}</p>"
                f"<p><strong>年份：</strong>{escape(self._join_or_default(metadata.get('years')))}</p>"
                f"<p><strong>文本规模：</strong>{escape(str(analysis.get('paragraph_count', 0)))} 段，{escape(str(analysis.get('sentence_count', 0)))} 句</p>"
                f"<p><strong>结论摘要：</strong>{escape(str(summary.get('headline', '本篇分析已完成。')))}</p>"
                f"<p><strong>高频新提法：</strong>{escape(new_terms)}</p>"
                f"<p><strong>核心议题：</strong>{escape(core_topics)}</p>"
                f"<ul class='finding-list'>{takeaway_items}</ul>"
                "</section>"
            )
        return ''.join(cards)

    def _build_html_styles(self) -> str:
        return """
        @page {
            size: A4;
            margin: 12mm;
        }
        :root {
            color-scheme: light;
            --bg: #f1ede3;
            --paper: #fffdf8;
            --line: #d8d0c2;
            --ink: #17212b;
            --muted: #607080;
            --accent: #9a3412;
            --accent-soft: #f5e6da;
            --accent-deep: #6b210f;
            --shadow: 0 20px 40px rgba(23, 33, 43, 0.08);
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 24px;
            font-family: "Microsoft YaHei UI", "SimHei", sans-serif;
            background:
                radial-gradient(circle at top left, #faf4eb 0%, #f3ede0 40%, #ebe4d7 100%);
            color: var(--ink);
        }
        .page {
            width: min(1080px, 100%);
            margin: 0 auto 22px;
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 24px;
            box-shadow: var(--shadow);
            padding: 28px 30px;
            page-break-after: always;
            break-after: page;
        }
        .page:last-child {
            page-break-after: auto;
            break-after: auto;
        }
        .cover-page {
            min-height: calc(297mm - 24mm);
            display: flex;
            align-items: stretch;
            background: linear-gradient(145deg, #fff9f2 0%, #f3e2d2 100%);
        }
        .cover-shell {
            display: flex;
            flex-direction: column;
            justify-content: center;
            width: 100%;
            border: 1px solid rgba(154, 52, 18, 0.16);
            border-radius: 20px;
            padding: 46px 42px;
            background: linear-gradient(180deg, rgba(255,255,255,0.65), rgba(255,255,255,0.25));
        }
        .cover-kicker {
            color: var(--accent);
            font-size: 12px;
            letter-spacing: 0.22em;
            text-transform: uppercase;
            font-weight: 700;
            margin-bottom: 12px;
        }
        .cover-badge {
            align-self: flex-start;
            background: var(--accent-soft);
            color: var(--accent-deep);
            border: 1px solid rgba(154, 52, 18, 0.18);
            border-radius: 999px;
            padding: 8px 14px;
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 20px;
        }
        h1 {
            margin: 0;
            font-size: 38px;
            line-height: 1.18;
            letter-spacing: -0.02em;
        }
        .cover-subtitle {
            margin-top: 18px;
            font-size: 18px;
            line-height: 1.8;
            color: var(--muted);
            max-width: 820px;
        }
        .cover-meta {
            display: flex;
            gap: 18px;
            flex-wrap: wrap;
            margin-top: 26px;
            font-size: 13px;
            color: var(--muted);
        }
        .page-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 12px;
            margin-bottom: 14px;
            border-bottom: 1px solid var(--line);
        }
        h2 {
            margin: 0;
            font-size: 22px;
            line-height: 1.2;
        }
        h3 {
            margin: 0 0 14px;
            font-size: 18px;
            line-height: 1.3;
        }
        p { margin: 0; line-height: 1.8; }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
            margin: 0 0 18px;
        }
        .metric-card, .panel {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 18px;
        }
        .metric-card {
            padding: 18px 20px;
        }
        .metric-label {
            color: var(--muted);
            font-size: 13px;
            margin-bottom: 8px;
        }
        .metric-value {
            color: var(--accent-deep);
            font-size: 24px;
            font-weight: 700;
            line-height: 1.24;
        }
        .panel {
            padding: 20px 22px;
            margin-bottom: 16px;
            box-shadow: 0 8px 24px rgba(23, 33, 43, 0.04);
        }
        .finding-list {
            margin: 0;
            padding-left: 18px;
            line-height: 1.9;
        }
        .muted {
            color: var(--muted);
        }
        .report-table {
            width: 100%;
            border-collapse: collapse;
            border-spacing: 0;
        }
        .report-table th,
        .report-table td {
            padding: 11px 10px;
            border-bottom: 1px solid var(--line);
            text-align: left;
            vertical-align: top;
            line-height: 1.65;
            font-size: 13px;
        }
        .report-table th {
            background: var(--accent-soft);
            color: var(--accent-deep);
            font-weight: 700;
        }
        .pair-grid {
            display: grid;
            gap: 12px;
        }
        .note-card {
            border: 1px solid var(--line);
            border-radius: 16px;
            background: linear-gradient(180deg, #fffefb 0%, #fff7ed 100%);
            padding: 14px 16px;
            margin-bottom: 12px;
        }
        .note-card-title {
            color: var(--accent-deep);
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .note-pre {
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
            font-family: "Microsoft YaHei UI", "SimHei", sans-serif;
            color: var(--ink);
            line-height: 1.8;
        }
        .pair-card {
            border: 1px solid var(--line);
            border-radius: 16px;
            background: linear-gradient(180deg, #fffaf3 0%, #fffefb 100%);
            padding: 14px 16px;
        }
        .batch-doc-card p {
            margin: 0 0 8px;
        }
        .pair-meta {
            color: var(--accent-deep);
            font-size: 13px;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .pair-text {
            line-height: 1.8;
            margin-bottom: 6px;
        }
        @media print {
            body {
                padding: 0;
                background: #ffffff;
            }
            .page {
                width: auto;
                margin: 0;
                border: none;
                border-radius: 0;
                box-shadow: none;
                padding: 0;
            }
            .panel,
            .metric-card,
            .pair-card {
                box-shadow: none;
            }
        }
        @media (max-width: 720px) {
            body { padding: 12px; }
            .page { padding: 18px 18px; border-radius: 18px; }
            .cover-shell { padding: 28px 22px; }
            h1 { font-size: 28px; }
            .cover-subtitle { font-size: 16px; }
        }
        """

    @staticmethod
    def _join_or_default(values: list[str] | None) -> str:
        if not values:
            return "未识别"
        return "、".join(values)
