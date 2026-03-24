from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF, Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.config import AppConfig, DEFAULT_CONFIG, get_resource_path
from core.startup_checks import (
    DeploymentCheck,
    DeploymentCheckTransition,
    StartupCheckReport,
    build_diagnostic_report_html,
    build_diagnostic_report_markdown,
    build_model_performance_summary_text,
    compare_startup_reports,
    extract_model_performance_metrics,
    get_model_performance_level,
    get_model_performance_level_text,
    run_startup_checks,
    summarize_transitions,
)


_STATUS_TEXT = {
    "ok": "通过",
    "warning": "警告",
    "error": "错误",
}

_STATUS_COLOR = {
    "ok": QColor("#1d7a46"),
    "warning": QColor("#a15c00"),
    "error": QColor("#b42318"),
}

_TRANSITION_STYLE = {
    "improved": {
        "background": QColor("#ecfdf3"),
        "foreground": QColor("#027a48"),
    },
    "regressed": {
        "background": QColor("#fef3f2"),
        "foreground": QColor("#b42318"),
    },
    "updated": {
        "background": QColor("#eff8ff"),
        "foreground": QColor("#175cd3"),
    },
}

_PERFORMANCE_LEVEL_STYLE = {
    "ok": {"background": "#ecfdf3", "foreground": "#027a48", "border": "#abefc6"},
    "near": {"background": "#fffaeb", "foreground": "#b54708", "border": "#fedf89"},
    "slow": {"background": "#fef3f2", "foreground": "#b42318", "border": "#fecdca"},
    "info": {"background": "#f2f4f7", "foreground": "#344054", "border": "#d0d5dd"},
}


class StartupWizardDialog(QDialog):
    def __init__(
        self,
        config: AppConfig | None = None,
        report: StartupCheckReport | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config or DEFAULT_CONFIG
        self.report = report or run_startup_checks(self.config)
        self._previous_report: StartupCheckReport | None = None
        self._transitions: list[DeploymentCheckTransition] = []
        self._transition_map: dict[str, DeploymentCheckTransition] = {}

        self.setWindowTitle("PolicyAnalyzerPro - 部署向导")
        self.resize(1020, 780)
        self.setMinimumSize(900, 660)

        self._build_ui()
        self._populate_report()

    @property
    def suppress_future_wizard(self) -> bool:
        return self._suppress_checkbox.isChecked() and not self.report.has_critical_issues

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        header = QWidget(self)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        title = QLabel("首次部署向导与环境自检", header)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        subtitle = QLabel(
            "启动前会检查模型目录、真实模型试加载、OCR 管线与资源文件，帮助你把部署问题提前暴露出来。",
            header,
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #4b5563; font-size: 13px;")

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        summary_card = QWidget(self)
        summary_card.setStyleSheet(
            "background: #fffaf2; border: 1px solid #ead8bf; border-radius: 12px;"
        )
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(4)

        self._overall_badge = QLabel(summary_card)
        self._overall_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overall_badge.setFixedWidth(112)
        self._overall_badge.setStyleSheet(
            "font-weight: 700; border-radius: 10px; padding: 6px 10px;"
        )

        self._summary_label = QLabel(summary_card)
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("font-size: 13px;")

        self._change_summary_label = QLabel(summary_card)
        self._change_summary_label.setWordWrap(True)
        self._change_summary_label.setStyleSheet("color: #175cd3; font-size: 12px;")

        self._checked_at_label = QLabel(summary_card)
        self._checked_at_label.setStyleSheet("color: #667085; font-size: 12px;")

        summary_layout.addWidget(self._overall_badge, 0, Qt.AlignmentFlag.AlignLeft)
        summary_layout.addWidget(self._summary_label)
        summary_layout.addWidget(self._change_summary_label)
        summary_layout.addWidget(self._checked_at_label)

        action_row = QHBoxLayout()
        self._refresh_button = QPushButton("重新检测", self)
        self._export_report_button = QPushButton("导出诊断报告", self)
        self._open_model_button = QPushButton("打开模型目录", self)
        self._open_config_button = QPushButton("打开配置目录", self)
        action_row.addWidget(self._refresh_button)
        action_row.addWidget(self._export_report_button)
        action_row.addWidget(self._open_model_button)
        action_row.addWidget(self._open_config_button)
        action_row.addStretch(1)

        self._checks_tree = QTreeWidget(self)
        self._checks_tree.setColumnCount(4)
        self._checks_tree.setHeaderLabels(["检查项", "状态", "变化", "说明"])
        self._checks_tree.setRootIsDecorated(False)
        self._checks_tree.setAlternatingRowColors(True)
        self._checks_tree.setUniformRowHeights(True)
        self._checks_tree.setColumnWidth(0, 180)
        self._checks_tree.setColumnWidth(1, 80)
        self._checks_tree.setColumnWidth(2, 150)

        self._detail_view = QTextBrowser(self)
        self._detail_view.setOpenExternalLinks(False)
        self._detail_view.setStyleSheet("border: 1px solid #d0d5dd; border-radius: 10px;")

        self._suppress_checkbox = QCheckBox("环境稳定后，下次不再自动显示此向导", self)

        footer_row = QHBoxLayout()
        footer_row.addWidget(self._suppress_checkbox)
        footer_row.addStretch(1)
        self._continue_button = QPushButton("进入软件", self)
        self._exit_button = QPushButton("退出", self)
        footer_row.addWidget(self._continue_button)
        footer_row.addWidget(self._exit_button)

        root_layout.addWidget(header)
        root_layout.addWidget(summary_card)
        root_layout.addLayout(action_row)
        root_layout.addWidget(self._checks_tree, 3)
        root_layout.addWidget(self._detail_view, 2)
        root_layout.addLayout(footer_row)

        self._refresh_button.clicked.connect(self._refresh_report)
        self._export_report_button.clicked.connect(self._export_diagnostic_report)
        self._open_model_button.clicked.connect(self._open_model_directory)
        self._open_config_button.clicked.connect(self._open_config_directory)
        self._checks_tree.currentItemChanged.connect(self._on_current_item_changed)
        self._continue_button.clicked.connect(self.accept)
        self._exit_button.clicked.connect(self.reject)

    def _populate_report(self) -> None:
        self._checks_tree.clear()
        for index, item in enumerate(self.report.results):
            transition = self._transition_map.get(item.key)
            tree_item = QTreeWidgetItem(
                [
                    item.title,
                    _STATUS_TEXT.get(item.status, item.status),
                    transition.label if transition is not None else "",
                    item.summary,
                ]
            )
            color = _STATUS_COLOR.get(item.status, QColor("#344054"))
            tree_item.setForeground(1, QBrush(color))
            tree_item.setData(0, Qt.ItemDataRole.UserRole, index)
            if item.location:
                tree_item.setToolTip(0, item.location)
            if transition is not None:
                self._apply_transition_style(tree_item, transition)
            self._checks_tree.addTopLevelItem(tree_item)

        if self._checks_tree.topLevelItemCount() > 0:
            self._checks_tree.setCurrentItem(self._checks_tree.topLevelItem(0))

        self._update_summary_ui()
        self._update_continue_button()

    def _apply_transition_style(
        self,
        tree_item: QTreeWidgetItem,
        transition: DeploymentCheckTransition,
    ) -> None:
        style = _TRANSITION_STYLE.get(transition.direction)
        if style is None:
            return

        background = QBrush(style["background"])
        foreground = QBrush(style["foreground"])
        for column in range(self._checks_tree.columnCount()):
            tree_item.setBackground(column, background)
        tree_item.setForeground(2, foreground)

    def _update_summary_ui(self) -> None:
        overall = self.report.overall_status
        if overall == "error":
            badge_bg = "#fef3f2"
            badge_fg = "#b42318"
        elif overall == "warning":
            badge_bg = "#fffaeb"
            badge_fg = "#b54708"
        else:
            badge_bg = "#ecfdf3"
            badge_fg = "#027a48"

        self._overall_badge.setText(self.report.overall_label)
        self._overall_badge.setStyleSheet(
            f"font-weight: 700; border-radius: 10px; padding: 6px 10px; background: {badge_bg}; color: {badge_fg};"
        )
        self._summary_label.setText(self.report.summary_text)
        if self._previous_report is None:
            self._change_summary_label.setText("点击“重新检测”后，可在这里查看修复前后差异。")
        else:
            self._change_summary_label.setText(summarize_transitions(self._transitions))
        self._checked_at_label.setText(f"最近检测时间：{self.report.checked_at}")

        if self.report.has_critical_issues:
            self._suppress_checkbox.setChecked(False)
            self._suppress_checkbox.setEnabled(False)
        else:
            self._suppress_checkbox.setEnabled(True)

    def _update_continue_button(self) -> None:
        if self.report.has_critical_issues:
            self._continue_button.setText("带风险进入软件")
        elif self.report.warning_count > 0:
            self._continue_button.setText("继续进入软件")
        else:
            self._continue_button.setText("进入软件")

    def _refresh_report(self) -> None:
        previous_report = self.report
        self.report = run_startup_checks(self.config)
        self._previous_report = previous_report
        self._transitions = compare_startup_reports(previous_report, self.report)
        self._transition_map = {item.key: item for item in self._transitions}
        self._populate_report()


    def _on_current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            self._detail_view.clear()
            return

        index = current.data(0, Qt.ItemDataRole.UserRole)
        if index is None:
            self._detail_view.clear()
            return

        check = self.report.results[int(index)]
        self._detail_view.setHtml(self._build_detail_html(check))

    def _performance_level_style(self, level: str) -> dict[str, str]:
        return _PERFORMANCE_LEVEL_STYLE.get(level, _PERFORMANCE_LEVEL_STYLE["info"])

    def _build_performance_metrics_html(self, check: DeploymentCheck) -> str:
        metrics = extract_model_performance_metrics(check, self.config)
        if not metrics:
            return ""

        overall_level = get_model_performance_level(metrics)
        overall_style = self._performance_level_style(overall_level)
        cards: list[str] = []
        for metric in metrics:
            metric_style = self._performance_level_style(metric.level)
            threshold_html = ""
            if metric.threshold:
                if metric.key == "throughput_items_per_second":
                    threshold_html = (
                        f"<div style='margin-top: 4px; color: #667085; font-size: 11px;'>\u53c2\u8003\u9608\u503c\uff1a{metric.threshold:.2f} \u6761/\u79d2</div>"
                    )
                else:
                    threshold_html = (
                        f"<div style='margin-top: 4px; color: #667085; font-size: 11px;'>\u9608\u503c\uff1a{metric.threshold:.0f} ms</div>"
                    )
            cards.append(
                "<div style='flex: 1 1 180px; min-width: 170px; border-radius: 12px; padding: 10px 12px; "
                f"border: 1px solid {metric_style['border']}; background: {metric_style['background']};'>"
                f"<div style='font-size: 12px; color: {metric_style['foreground']}; font-weight: 700;'>"
                f"{escape(metric.label)} | {escape(get_model_performance_level_text(metric.level))}</div>"
                f"<div style='margin-top: 4px; font-size: 18px; color: #101828; font-weight: 700;'>"
                f"{escape(metric.display_value)}</div>"
                f"{threshold_html}"
                "</div>"
            )

        summary_text = build_model_performance_summary_text(metrics, limit=5)
        return (
            "<div style='margin: 12px 0 14px 0; padding: 12px; border-radius: 14px; border: 1px solid #d0d5dd; background: #fcfcfd;'>"
            "<div style='display: flex; align-items: center; gap: 10px; margin-bottom: 10px;'>"
            f"<span style='display: inline-block; padding: 4px 10px; border-radius: 999px; background: {overall_style['background']}; color: {overall_style['foreground']}; border: 1px solid {overall_style['border']}; font-size: 12px; font-weight: 700;'>\u6027\u80fd\u7b49\u7ea7\uff1a{escape(get_model_performance_level_text(overall_level))}</span>"
            f"<span style='color: #475467; font-size: 12px;'>{escape(summary_text)}</span>"
            "</div>"
            "<div style='display: flex; flex-wrap: wrap; gap: 10px;'>"
            f"{''.join(cards)}"
            "</div>"
            "</div>"
        )

    def _build_detail_html(self, check: DeploymentCheck) -> str:
        location_html = ""
        if check.location:
            location_html = f"<p><strong>\u4f4d\u7f6e\uff1a</strong>{escape(check.location)}</p>"

        detail_html = ""
        if check.detail:
            detail_html = f"<p><strong>\u8be6\u60c5\uff1a</strong><br>{escape(check.detail).replace(chr(10), '<br>')}</p>"

        hint_html = ""
        if check.hint:
            hint_html = f"<p><strong>\u5efa\u8bae\uff1a</strong>{escape(check.hint)}</p>"

        transition_html = ""
        transition = self._transition_map.get(check.key)
        if transition is not None:
            previous_summary = transition.previous_summary or "\u65e0"
            current_summary = transition.current_summary or "\u65e0"
            transition_html = (
                "<p><strong>\u4fee\u590d\u524d\u540e\u5dee\u5f02\uff1a</strong>"
                f"{escape(transition.label)}<br>"
                f"\u4e4b\u524d\uff1a{escape(previous_summary)}<br>"
                f"\u73b0\u5728\uff1a{escape(current_summary)}</p>"
            )

        performance_html = self._build_performance_metrics_html(check)

        return (
            "<html><body style='font-family: Microsoft YaHei UI, SimHei, sans-serif; line-height: 1.7;'>"
            f"<h3 style='margin-top: 0;'>{escape(check.title)}</h3>"
            f"<p><strong>\u72b6\u6001\uff1a</strong>{escape(_STATUS_TEXT.get(check.status, check.status))}</p>"
            f"<p><strong>\u6458\u8981\uff1a</strong>{escape(check.summary)}</p>"
            f"{performance_html}"
            f"{transition_html}"
            f"{location_html}"
            f"{detail_html}"
            f"{hint_html}"
            "</body></html>"
        )

    def _build_diagnostic_export_base_name(self) -> str:
        return f"deployment-diagnostic-{self.report.checked_at.replace(':', '').replace(' ', '-')}"

    def _resolve_diagnostic_export_target(self, raw_path: str, selected_filter: str) -> tuple[Path, str]:
        export_path = Path(raw_path)
        suffix = export_path.suffix.lower()
        if suffix == ".html":
            return export_path, "html"
        if suffix == ".pdf":
            return export_path, "pdf"
        if suffix == ".md":
            return export_path, "markdown"

        selected_filter = selected_filter or ""
        if "HTML" in selected_filter:
            return export_path.with_suffix(".html"), "html"
        if "PDF" in selected_filter:
            return export_path.with_suffix(".pdf"), "pdf"
        return export_path.with_suffix(".md"), "markdown"

    def _write_diagnostic_pdf_report(self, path: Path, html: str) -> None:
        document = QTextDocument(self)
        document.setHtml(html)

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(path))
        page_layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(12, 12, 12, 12),
            QPageLayout.Unit.Millimeter,
        )
        printer.setPageLayout(page_layout)
        document.print_(printer)

        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError("PDF 导出失败，未生成有效文件。")

    def _export_diagnostic_report(self) -> None:
        default_base_name = self._build_diagnostic_export_base_name()
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出部署诊断报告",
            str(Path.home() / default_base_name),
            "Markdown 文件 (*.md);;HTML 文件 (*.html);;PDF 文件 (*.pdf);;所有文件 (*.*)",
        )
        if not path:
            return

        target_path, export_format = self._resolve_diagnostic_export_target(path, selected_filter)

        try:
            markdown_content = build_diagnostic_report_markdown(
                self.report,
                config=self.config,
                previous_report=self._previous_report,
            )
            if export_format == "markdown":
                target_path.write_text(markdown_content, encoding="utf-8-sig")
            else:
                html_content = build_diagnostic_report_html(
                    self.report,
                    config=self.config,
                    previous_report=self._previous_report,
                )
                if export_format == "html":
                    target_path.write_text(html_content, encoding="utf-8-sig")
                else:
                    self._write_diagnostic_pdf_report(target_path, html_content)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入诊断报告：\n{exc}")
            return

        QMessageBox.information(self, "导出完成", f"部署诊断报告已导出到：\n{target_path}")

    def _open_model_directory(self) -> None:
        model_path = Path(self.config.resolved_model_dir)
        target = model_path if model_path.exists() else model_path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _open_config_directory(self) -> None:
        config_dir = Path(get_resource_path("config"))
        target = config_dir if config_dir.exists() else Path(get_resource_path("."))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def accept(self) -> None:
        if self.report.has_critical_issues:
            answer = QMessageBox.question(
                self,
                "仍存在关键问题",
                "当前仍有关键部署问题，部分分析功能可能无法工作。确定仍然进入软件吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        super().accept()
