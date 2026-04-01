from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.analysis_router import (
    ANALYSIS_MODE_HYBRID as ROUTE_MODE_HYBRID,
    ANALYSIS_MODE_OFFLINE as ROUTE_MODE_OFFLINE,
    ANALYSIS_MODE_ONLINE as ROUTE_MODE_ONLINE,
    build_analysis_route_text,
    build_capability_snapshot,
    get_analysis_mode_label,
    resolve_analysis_route,
)
from core.config import AppConfig, DEFAULT_CONFIG
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
from core.nlp_thread import (
    ANALYSIS_MODE_BATCH,
    ANALYSIS_MODE_COMPARE,
    ANALYSIS_MODE_SINGLE,
    NLPAnalysisThread,
)
from core.result_formatter import AnalysisResultFormatter
from core.startup_checks import (
    StartupCheckReport,
    build_model_performance_summary_text,
    extract_model_performance_metrics,
    get_model_performance_level,
    get_model_performance_level_text,
    run_startup_checks,
)
from importers.document_loader import DocumentImportError, DocumentLoader, PdfImportOptions
from ui.startup_wizard import StartupWizardDialog


_PERFORMANCE_LEVEL_STYLE = {
    "ok": {"background": "#ecfdf3", "foreground": "#027a48", "border": "#abefc6"},
    "near": {"background": "#fffaeb", "foreground": "#b54708", "border": "#fedf89"},
    "slow": {"background": "#fef3f2", "foreground": "#b42318", "border": "#fecdca"},
    "info": {"background": "#f2f4f7", "foreground": "#344054", "border": "#d0d5dd"},
}


class ClickableBadgeLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PreviewHintPopover(QFrame):
    copy_clicked = Signal()
    insert_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("previewHintPopover")
        self.setStyleSheet(
            "QFrame#previewHintPopover {"
            "background: #ffffff; border: 1px solid #d0d5dd; border-radius: 12px;"
            "}"
            "QLabel#previewHintTitle {"
            "font-size: 13px; font-weight: 700; color: #101828;"
            "}"
            "QLabel#previewHintBody {"
            "font-size: 12px; color: #344054; line-height: 1.45;"
            "}"
            "QLabel#previewHintFootnote {"
            "font-size: 11px; color: #667085;"
            "}"
            "QPushButton#previewHintCopyButton, QPushButton#previewHintInsertButton {"
            "font-size: 11px; font-weight: 700; color: #175cd3; background: #eff8ff;"
            "border: 1px solid #b2ddff; border-radius: 8px; padding: 4px 10px;"
            "}"
            "QPushButton#previewHintCopyButton:hover, QPushButton#previewHintInsertButton:hover {"
            "background: #d1e9ff; border: 1px solid #84caff;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("previewHintTitle")
        self.title_label.setWordWrap(True)

        self.body_label = QLabel(self)
        self.body_label.setObjectName("previewHintBody")
        self.body_label.setWordWrap(True)
        self.body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(8)

        self.footnote_label = QLabel("点击空白处关闭", self)
        self.footnote_label.setObjectName("previewHintFootnote")

        self.insert_button = QPushButton("插入到分析结果", self)
        self.insert_button.setObjectName("previewHintInsertButton")
        self.insert_button.setAutoDefault(False)
        self.insert_button.clicked.connect(self.insert_clicked.emit)

        self.copy_button = QPushButton("复制说明", self)
        self.copy_button.setObjectName("previewHintCopyButton")
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self.copy_clicked.emit)

        footer_row.addWidget(self.footnote_label, 1)
        footer_row.addWidget(self.insert_button, 0)
        footer_row.addWidget(self.copy_button, 0)

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addLayout(footer_row)

        self.setMinimumWidth(320)
        self.setMaximumWidth(420)

    def set_content(self, title: str, body: str) -> None:
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.adjustSize()


class PdfImportOptionsDialog(QDialog):
    def __init__(
        self,
        file_name: str,
        default_page_spec: str,
        use_ocr_cache: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("\u0050\u0044\u0046 OCR \u9009\u9879")
        self.setModal(True)
        self.resize(440, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        description = QLabel(
            f"\u6587\u4ef6\uff1a{file_name}\n"
            "\u9875\u7801\u8303\u56f4\u4ec5\u5728 PDF \u65e0\u7a33\u5b9a\u6587\u5b57\u5c42\u3001\u5b9e\u9645\u8d70 OCR \u65f6\u751f\u6548\u3002"
            "\u7559\u7a7a\u65f6\u6309\u914d\u7f6e\u9ed8\u8ba4\u524d N \u9875\u6267\u884c\u3002",
            self,
        )
        description.setWordWrap(True)
        description.setStyleSheet("color: #475467; font-size: 12px;")

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self.page_range_edit = QLineEdit(self)
        self.page_range_edit.setPlaceholderText("\u4f8b\uff1a1-3,5,8-10")
        self.page_range_edit.setText(default_page_spec)

        self.cache_checkbox = QCheckBox("\u542f\u7528 OCR \u7ed3\u679c\u7f13\u5b58", self)
        self.cache_checkbox.setChecked(use_ocr_cache)

        hint = QLabel(
            "\u9875\u7801\u8303\u56f4\u4ec5\u652f\u6301\u6570\u5b57\u548c\u533a\u95f4\uff0c\u5982 2-4,7\u3002\u7f13\u5b58\u4f1a\u6309\u6587\u4ef6\u3001\u9875\u7801\u8303\u56f4\u548c OCR \u53c2\u6570\u81ea\u52a8\u590d\u7528\u3002",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #667085; font-size: 11px;")

        form.addRow("OCR \u9875\u7801\u8303\u56f4", self.page_range_edit)
        layout.addWidget(description)
        layout.addLayout(form)
        layout.addWidget(self.cache_checkbox)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_options(self) -> PdfImportOptions:
        return PdfImportOptions(
            ocr_page_spec=self.page_range_edit.text().strip(),
            use_ocr_cache=self.cache_checkbox.isChecked(),
        )


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig | None = None,
        startup_report: StartupCheckReport | None = None,
    ) -> None:
        super().__init__()
        self.config = config or DEFAULT_CONFIG
        self._startup_report = startup_report or run_startup_checks(self.config)
        self._analysis_thread: NLPAnalysisThread | None = None
        self._busy_controls: list[QWidget] = []
        self._last_result: dict | None = None
        self._inserted_preview_hint_notes: list[str] = []
        self._batch_documents: list[dict[str, Any]] = []
        self._result_formatter = AnalysisResultFormatter()
        self._document_loader = DocumentLoader(self.config)
        self._analysis_capabilities = build_capability_snapshot(self.config, self._startup_report)
        self._last_pdf_ocr_page_spec = ""
        self._last_pdf_use_cache = bool(getattr(self.config, "enable_ocr_result_cache", True))

        self.setWindowTitle("PolicyAnalyzerPro - 中国政策报告智能分析引擎")
        self.resize(1366, 768)
        self.setMinimumSize(1040, 600)
        # 添加窗口图标
        try:
            from PySide6.QtGui import QIcon
            icon_path = "assets/icons/app_icon.png"
            if Path(icon_path).exists():
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass
        self.setStatusBar(QStatusBar(self))

        self._build_ui()
        self._connect_signals()
        self._set_busy_state(False)
        self._update_export_state()
        self._update_environment_status()
        self._update_analysis_route_status()
        self._show_welcome_message()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        root_layout.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_output_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root_layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(4)

        title = QLabel("中国政策报告智能分析引擎", container)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")

        subtitle = QLabel(
            "离线优先运行，支持 TXT / DOCX / PDF 导入、离线 / 在线 / 混合模式切换与正式报告导出。",
            container,
        )
        subtitle.setStyleSheet("color: #4b5563; font-size: 13px;")

        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        top_row.addLayout(title_column, 1)

        status_column = QVBoxLayout()
        status_column.setContentsMargins(0, 0, 0, 0)
        status_column.setSpacing(6)

        status_row = QHBoxLayout()
        status_row.addStretch(1)
        self.environment_status_label = QLabel(container)
        self.environment_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.environment_status_label.setMinimumWidth(110)
        self.environment_status_label.setStyleSheet(
            "font-size: 12px; font-weight: 700; border-radius: 10px; padding: 6px 10px;"
        )
        self.environment_check_button = QPushButton("环境自检", container)
        status_row.addWidget(self.environment_status_label)


        status_row.addWidget(self.environment_check_button)

        self.environment_helper_label = QLabel(
            "启动前已完成部署检查，可随时重新检测模型、OCR 和关键依赖。",
            container,
        )
        self.environment_helper_label.setStyleSheet("color: #667085; font-size: 12px;")
        self.environment_helper_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        performance_row = QHBoxLayout()
        performance_row.setContentsMargins(0, 0, 0, 0)
        performance_row.setSpacing(8)
        performance_row.addStretch(1)

        self.environment_performance_badge = QLabel(container)
        self.environment_performance_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.environment_performance_badge.setMinimumWidth(92)
        self.environment_performance_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 8px;"
        )

        self.environment_performance_label = QLabel(container)
        self.environment_performance_label.setWordWrap(True)
        self.environment_performance_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.environment_performance_label.setTextFormat(Qt.TextFormat.RichText)
        self.environment_performance_label.setStyleSheet("font-size: 12px;")

        performance_row.addWidget(self.environment_performance_badge)
        performance_row.addWidget(self.environment_performance_label, 1)

        analysis_row = QHBoxLayout()
        analysis_row.setContentsMargins(0, 0, 0, 0)
        analysis_row.setSpacing(8)

        analysis_mode_title = QLabel("\u5206\u6790\u6a21\u5f0f", container)
        analysis_mode_title.setStyleSheet("color: #344054; font-size: 12px; font-weight: 700;")

        self.analysis_mode_combo = QComboBox(container)
        self.analysis_mode_combo.addItem("\u79bb\u7ebf\u5206\u6790\uff08\u9ed8\u8ba4\uff09", ROUTE_MODE_OFFLINE)
        self.analysis_mode_combo.addItem("\u5728\u7ebf\u5206\u6790", ROUTE_MODE_ONLINE)
        self.analysis_mode_combo.addItem("\u6df7\u5408\u5206\u6790", ROUTE_MODE_HYBRID)
        self.analysis_mode_combo.setMinimumWidth(160)

        self.online_status_badge = QLabel(container)
        self.online_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.online_status_badge.setMinimumWidth(82)
        self.online_status_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 8px;"
        )

        self.analysis_mode_label = QLabel(container)
        self.analysis_mode_label.setWordWrap(True)
        self.analysis_mode_label.setStyleSheet("color: #475467; font-size: 12px;")

        # 依赖状态徽章（可点击）
        self.dependency_status_badge = ClickableBadgeLabel(container)
        self.dependency_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dependency_status_badge.setMinimumWidth(82)
        self.dependency_status_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 8px;"
        )
        self.dependency_status_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dependency_status_badge.setToolTip("点击打开环境自检向导查看依赖详情")

        analysis_row.addWidget(analysis_mode_title)
        analysis_row.addWidget(self.analysis_mode_combo, 0)
        analysis_row.addWidget(self.online_status_badge, 0)
        analysis_row.addWidget(self.dependency_status_badge, 0)
        analysis_row.addWidget(self.analysis_mode_label, 1)

        status_column.addLayout(status_row)
        status_column.addWidget(self.environment_helper_label)
        status_column.addLayout(analysis_row)
        status_column.addLayout(performance_row)
        top_row.addLayout(status_column)

        layout.addLayout(top_row)
        return container

    def _build_input_panel(self) -> QWidget:
        self.tab_widget = QTabWidget(self)
        self.tab_widget.addTab(self._build_single_tab(), "单篇分析")
        self.tab_widget.addTab(self._build_compare_tab(), "双篇比对")
        self.tab_widget.addTab(self._build_batch_tab(), "批量分析")
        self._busy_controls.append(self.tab_widget)
        return self.tab_widget

    def _build_single_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        group = QGroupBox("单篇政策报告", page)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(10)

        self.single_input = QTextEdit(group)
        self.single_input.setPlaceholderText(
            "粘贴政府工作报告、政策解读或会议纪要正文。\n\n"
            "也可以直接导入 TXT / DOCX / PDF，系统会自动做政务降噪后再分析。"
        )

        button_row = QHBoxLayout()
        self.single_load_button = QPushButton("导入文档", group)
        self.single_clear_button = QPushButton("清空", group)
        self.single_run_button = QPushButton("开始单篇分析", group)
        self.single_run_button.setDefault(True)

        button_row.addWidget(self.single_load_button)
        button_row.addWidget(self.single_clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.single_run_button)

        group_layout.addWidget(self.single_input, 1)
        group_layout.addLayout(button_row)
        layout.addWidget(group)

        self._busy_controls.extend(
            [
                self.single_input,
                self.single_load_button,
                self.single_clear_button,
                self.single_run_button,
            ]
        )
        return page

    def _build_compare_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        editors_row = QHBoxLayout()
        editors_row.setSpacing(10)

        old_group = QGroupBox("旧稿", page)
        old_layout = QVBoxLayout(old_group)
        self.compare_old_input = QTextEdit(old_group)
        self.compare_old_input.setPlaceholderText(
            "粘贴较早版本的报告正文，或导入旧版 TXT / DOCX / PDF。"
        )
        self.compare_old_load_button = QPushButton("导入旧稿", old_group)
        old_layout.addWidget(self.compare_old_input, 1)
        old_layout.addWidget(self.compare_old_load_button)

        new_group = QGroupBox("新稿", page)
        new_layout = QVBoxLayout(new_group)
        self.compare_new_input = QTextEdit(new_group)
        self.compare_new_input.setPlaceholderText(
            "粘贴较新版本的报告正文，或导入新版 TXT / DOCX / PDF。"
        )
        self.compare_new_load_button = QPushButton("导入新稿", new_group)
        new_layout.addWidget(self.compare_new_input, 1)
        new_layout.addWidget(self.compare_new_load_button)

        editors_row.addWidget(old_group, 1)
        editors_row.addWidget(new_group, 1)

        button_row = QHBoxLayout()
        self.compare_clear_button = QPushButton("清空双稿", page)
        self.compare_run_button = QPushButton("开始双篇比对", page)

        button_row.addWidget(self.compare_clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.compare_run_button)

        layout.addLayout(editors_row, 1)
        layout.addLayout(button_row)

        self._busy_controls.extend(
            [
                self.compare_old_input,
                self.compare_new_input,
                self.compare_old_load_button,
                self.compare_new_load_button,
                self.compare_clear_button,
                self.compare_run_button,
            ]
        )
        return page

    def _build_batch_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        helper = QLabel(
            "导入多个 TXT / DOCX / PDF 文档后，可统一执行批量分析；右侧导入预览会跟随当前选中文档切换。",
            page,
        )
        helper.setWordWrap(True)
        helper.setStyleSheet("color: #667085; font-size: 12px;")

        group = QGroupBox("批量文档", page)
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(10)

        header_row = QHBoxLayout()
        self.batch_count_label = QLabel("当前已选择 0 份文档", group)
        self.batch_count_label.setStyleSheet("color: #475467; font-size: 12px;")
        header_row.addWidget(self.batch_count_label)
        header_row.addStretch(1)

        self.batch_list = QListWidget(group)
        self.batch_list.setAlternatingRowColors(True)
        self.batch_list.setMinimumHeight(280)

        button_row = QHBoxLayout()
        self.batch_add_button = QPushButton("批量导入", group)
        self.batch_remove_button = QPushButton("移除选中", group)
        self.batch_clear_button = QPushButton("清空列表", group)
        self.batch_run_button = QPushButton("开始批量分析", group)

        button_row.addWidget(self.batch_add_button)
        button_row.addWidget(self.batch_remove_button)
        button_row.addWidget(self.batch_clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.batch_run_button)

        group_layout.addLayout(header_row)
        group_layout.addWidget(self.batch_list, 1)
        group_layout.addLayout(button_row)
        layout.addWidget(helper)
        layout.addWidget(group, 1)

        self._busy_controls.extend(
            [
                self.batch_list,
                self.batch_add_button,
                self.batch_remove_button,
                self.batch_clear_button,
                self.batch_run_button,
            ]
        )
        return page

    def _build_output_panel(self) -> QWidget:
        group = QGroupBox("\u7ed3\u679c\u4e0e\u9884\u89c8", self)
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        top_row = QHBoxLayout()
        self.status_label = QLabel("\u5c31\u7eea", group)
        self.export_markdown_button = QPushButton("\u5bfc\u51fa Markdown", group)
        self.export_html_button = QPushButton("\u5bfc\u51fa HTML \u62a5\u544a", group)
        self.export_json_button = QPushButton("\u5bfc\u51fa JSON", group)
        self.cancel_button = QPushButton("\u53d6\u6d88\u4efb\u52a1", group)

        top_row.addWidget(self.status_label)
        top_row.addStretch(1)
        top_row.addWidget(self.export_markdown_button)
        top_row.addWidget(self.export_html_button)
        top_row.addWidget(self.export_json_button)
        top_row.addWidget(self.cancel_button)

        self.progress_bar = QProgressBar(group)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

        self.output_tab_widget = QTabWidget(group)

        self.result_view = QTextBrowser(group)
        self.result_view.setOpenExternalLinks(False)
        self.result_view.setPlaceholderText("\u5206\u6790\u7ed3\u679c\u5c06\u5728\u8fd9\u91cc\u663e\u793a\u3002")

        preview_panel = QWidget(group)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)

        preview_status_row = QHBoxLayout()
        preview_status_row.setContentsMargins(0, 0, 0, 0)
        preview_status_row.setSpacing(8)

        self.preview_hint_badge = ClickableBadgeLabel(preview_panel)
        self.preview_hint_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_hint_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_hint_badge.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.preview_hint_badge.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.preview_hint_badge.setMouseTracking(True)
        self.preview_hint_popover = PreviewHintPopover(self)

        self.preview_status_label = QLabel(preview_panel)
        self.preview_status_label.setWordWrap(True)

        preview_status_row.addWidget(self.preview_hint_badge, 0, Qt.AlignmentFlag.AlignTop)
        preview_status_row.addWidget(self.preview_status_label, 1)

        self.preview_view = QTextBrowser(preview_panel)
        self.preview_view.setOpenExternalLinks(False)
        self.preview_view.setPlaceholderText("\u5bfc\u5165\u6587\u6863\u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u793a\u6807\u9898\u533a\u548c\u6b63\u6587\u9884\u89c8\u3002")

        preview_layout.addLayout(preview_status_row)
        preview_layout.addWidget(self.preview_view, 1)

        self.output_tab_widget.addTab(self.result_view, "\u5206\u6790\u7ed3\u679c")
        self.output_tab_widget.addTab(preview_panel, "\u5bfc\u5165\u9884\u89c8")

        layout.addLayout(top_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.output_tab_widget, 1)

        return group

    def _connect_signals(self) -> None:
        self.environment_check_button.clicked.connect(self._show_environment_check_dialog)
        self.dependency_status_badge.clicked.connect(self._show_environment_check_dialog)
        self.analysis_mode_combo.currentIndexChanged.connect(self._on_analysis_mode_changed)
        self.preview_hint_badge.clicked.connect(self._toggle_preview_hint_popover)
        self.preview_hint_popover.copy_clicked.connect(self._copy_preview_hint_report)
        self.preview_hint_popover.insert_clicked.connect(self._insert_preview_hint_report)
        self.single_load_button.clicked.connect(
            lambda: self._load_document_into_editor(
                self.single_input,
                "导入单篇文档",
                "单篇分析",
            )
        )
        self.single_clear_button.clicked.connect(self._clear_single_input)
        self.single_run_button.clicked.connect(self._start_single_analysis)

        self.compare_old_load_button.clicked.connect(
            lambda: self._load_document_into_editor(
                self.compare_old_input,
                "导入旧稿",
                "双篇比对 / 旧稿",
            )
        )
        self.compare_new_load_button.clicked.connect(
            lambda: self._load_document_into_editor(
                self.compare_new_input,
                "导入新稿",
                "双篇比对 / 新稿",
            )
        )
        self.compare_clear_button.clicked.connect(self._clear_compare_inputs)
        self.compare_run_button.clicked.connect(self._start_compare_analysis)

        self.batch_add_button.clicked.connect(self._load_batch_documents)
        self.batch_remove_button.clicked.connect(self._remove_selected_batch_documents)
        self.batch_clear_button.clicked.connect(self._clear_batch_documents)
        self.batch_run_button.clicked.connect(self._start_batch_analysis)
        self.batch_list.currentRowChanged.connect(self._on_batch_selection_changed)
        self.cancel_button.clicked.connect(self._cancel_analysis)
        self.export_markdown_button.clicked.connect(self._export_markdown)
        self.export_html_button.clicked.connect(self._export_html)
        self.export_json_button.clicked.connect(self._export_json)



    def _show_welcome_message(self) -> None:
        self.result_view.setMarkdown(
            "# 欢迎使用 PolicyAnalyzerPro\n\n"
            "- 离线优先运行，默认不依赖联网服务。\n"
            "- 支持单篇分析、双篇政策演变比对和批量分析。\n"
            "- 可导入 TXT / DOCX / PDF，扫描版 PDF 支持 OCR。\n"
            "- 可导出 Markdown / HTML / JSON 分析结果。\n"
            "- 启动前已完成环境自检，可随时复查模型、OCR 和关键依赖。\n\n"
            "请选择分析模式并导入文本。"
        )
        self._reset_preview_state()
        if self._startup_report.has_critical_issues:
            self.statusBar().showMessage("环境中存在关键部署问题，请先按向导修复。", 8000)
        elif self._startup_report.warning_count > 0:
            self.statusBar().showMessage("环境检查存在警告项，可按需继续完善。", 8000)

    def _performance_level_style(self, level: str) -> dict[str, str]:
        return _PERFORMANCE_LEVEL_STYLE.get(level, _PERFORMANCE_LEVEL_STYLE["info"])

    def _build_environment_performance_summary_html(self) -> tuple[str, str, str, str]:
        benchmark_check = self._startup_report.by_key().get("model_warmup_benchmark")
        metrics = extract_model_performance_metrics(benchmark_check, self.config)
        if metrics:
            level = get_model_performance_level(metrics)
            badge_text = get_model_performance_level_text(level)
            parts = []
            for metric in metrics[:5]:
                metric_style = self._performance_level_style(metric.level)
                parts.append(
                    f"<span style='color: {metric_style['foreground']}; font-weight: 700;'>"
                    f"{metric.label} {metric.display_value}</span>"
                )
            tooltip = benchmark_check.detail or build_model_performance_summary_text(metrics, limit=6)
            return level, badge_text, " | ".join(parts), tooltip

        if benchmark_check is None:
            return "info", "未评估", "", ""

        tooltip = benchmark_check.detail or benchmark_check.summary
        return "info", "未评估", benchmark_check.summary, tooltip

    def _update_environment_status(self) -> None:
        if self._startup_report.has_critical_issues:
            text = "需修复"
            style = "background: #fef3f2; color: #b42318;"
        elif self._startup_report.warning_count > 0:
            text = "建议完善"
            style = "background: #fffaeb; color: #b54708;"
        else:
            text = "部署就绪"
            style = "background: #ecfdf3; color: #027a48;"

        self.environment_status_label.setText(text)
        self.environment_status_label.setStyleSheet(
            "font-size: 12px; font-weight: 700; border-radius: 10px; padding: 6px 10px; "
            + style
        )

        if self._startup_report.has_critical_issues:
            self.environment_helper_label.setText("环境中仍有关键部署问题，建议先完成修复再执行正式分析。")
        elif self._startup_report.warning_count > 0:
            self.environment_helper_label.setText("环境检查已完成，当前可继续使用，但仍有建议完善项。")
        else:
            self.environment_helper_label.setText("启动前部署检查已通过，模型、OCR 和关键依赖均可正常使用。")

        performance_level, badge_text, summary_html, tooltip = self._build_environment_performance_summary_html()
        performance_style = self._performance_level_style(performance_level)
        self.environment_performance_badge.setText(f"模型性能 {badge_text}")
        self.environment_performance_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 8px; "
            f"background: {performance_style['background']}; color: {performance_style['foreground']}; "
            f"border: 1px solid {performance_style['border']};"
        )
        self.environment_performance_label.setText(summary_html or "模型热身与性能基准未生成可展示指标。")
        self.environment_performance_label.setToolTip(tooltip)
        self.environment_performance_badge.setToolTip(tooltip)

    def _on_analysis_mode_changed(self) -> None:
        selected_mode = str(self.analysis_mode_combo.currentData() or ROUTE_MODE_OFFLINE)
        self.config = self.config.merge({"analysis_mode": selected_mode})
        self._update_analysis_route_status()
        self.statusBar().showMessage(f"\u5df2\u5207\u6362\u5230{get_analysis_mode_label(selected_mode)}\u3002", 4000)

    def _update_analysis_route_status(self) -> None:
        self._analysis_capabilities = build_capability_snapshot(self.config, self._startup_report)
        selected_mode = str(self.config.analysis_mode or ROUTE_MODE_OFFLINE)

        combo_index = self.analysis_mode_combo.findData(selected_mode)
        if combo_index >= 0 and combo_index != self.analysis_mode_combo.currentIndex():
            self.analysis_mode_combo.blockSignals(True)
            self.analysis_mode_combo.setCurrentIndex(combo_index)
            self.analysis_mode_combo.blockSignals(False)

        decision = resolve_analysis_route(selected_mode, config=self.config, startup_report=self._startup_report)
        preview_result = {
            "requested_analysis_mode": decision.requested_mode,
            "executed_analysis_mode": decision.executed_mode,
        }
        route_text = build_analysis_route_text(preview_result)
        detail_parts = [route_text, decision.message]
        if decision.warnings:
            detail_parts.append(decision.warnings[0])
        self.analysis_mode_label.setText(" ".join(part for part in detail_parts if part))

        state = self._analysis_capabilities.online_state
        summary = self._analysis_capabilities.online_summary
        if state == "ready":
            badge_text = "\u5728\u7ebf\u5c31\u7eea"
            badge_style = "background: #ecfdf3; color: #027a48; border: 1px solid #abefc6;"
        elif state == "skeleton":
            badge_text = "\u9aa8\u67b6\u5c31\u4f4d"
            badge_style = "background: #eff8ff; color: #175cd3; border: 1px solid #b2ddff;"
        elif state == "unconfigured":
            badge_text = "\u5f85\u914d\u7f6e"
            badge_style = "background: #fffaeb; color: #b54708; border: 1px solid #fedf89;"
        else:
            badge_text = "\u5728\u7ebf\u5173\u95ed"
            badge_style = "background: #f2f4f7; color: #344054; border: 1px solid #d0d5dd;"

        self.online_status_badge.setText(badge_text)
        self.online_status_badge.setToolTip(summary)
        self.online_status_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 8px; " + badge_style
        )

        # 更新依赖状态徽章
        dep_status = self._analysis_capabilities.dependency_status
        if dep_status == "ok":
            dep_badge_text = "环境正常"
            dep_badge_style = "background: #ecfdf3; color: #027a48; border: 1px solid #abefc6;"
            dep_tooltip = "所有依赖检查通过，环境就绪"
        elif dep_status == "warning":
            dep_badge_text = "依赖警告"
            dep_badge_style = "background: #fffaeb; color: #b54708; border: 1px solid #fedf89;"
            dep_tooltip = "存在依赖警告，建议检查环境"
        else:
            dep_badge_text = "依赖缺失"
            dep_badge_style = "background: #fef3f2; color: #b42318; border: 1px solid #fecdca;"
            dep_tooltip = "存在关键依赖缺失，点击打开环境自检向导"

        self.dependency_status_badge.setText(dep_badge_text)
        self.dependency_status_badge.setToolTip(dep_tooltip)
        self.dependency_status_badge.setStyleSheet(
            "font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 8px; " + dep_badge_style
        )

    def _show_environment_check_dialog(self) -> None:
        dialog = StartupWizardDialog(
            config=self.config,
            report=self._startup_report,
            parent=self,
        )
        dialog.exec()
        self._startup_report = dialog.report
        self._update_environment_status()
        self._update_analysis_route_status()
        if self._startup_report.has_critical_issues:
            self.statusBar().showMessage("环境中仍存在关键部署问题，请按向导提示修复。", 8000)
        elif self._startup_report.warning_count > 0:
            self.statusBar().showMessage("环境检查完成，仍有部分建议完善项。", 6000)
        else:
            self.statusBar().showMessage("环境检查完成，当前部署状态良好。", 5000)

    def _collect_pdf_import_options(self, file_path: Path) -> PdfImportOptions | None:
        dialog = PdfImportOptionsDialog(
            file_name=file_path.name,
            default_page_spec=self._last_pdf_ocr_page_spec,
            use_ocr_cache=self._last_pdf_use_cache,
            parent=self,
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return None

        options = dialog.build_options()
        self._last_pdf_ocr_page_spec = options.ocr_page_spec
        self._last_pdf_use_cache = options.use_ocr_cache
        return options

    def _load_document_into_editor(self, editor: QTextEdit, title: str, target_label: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            title,
            str(Path.home()),
            self._document_loader.file_dialog_filter(),
        )
        if not path:
            return

        file_path = Path(path)
        pdf_options = None
        if file_path.suffix.lower() == ".pdf" and self.config.enable_pdf_ocr:
            pdf_options = self._collect_pdf_import_options(file_path)
            if pdf_options is None:
                return

        try:
            content = self._document_loader.load_text_from_path(file_path, pdf_options=pdf_options)
        except DocumentImportError as exc:
            QMessageBox.warning(self, "\u8bfb\u53d6\u5931\u8d25", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "\u8bfb\u53d6\u5931\u8d25", f"\u65e0\u6cd5\u8bfb\u53d6\u6587\u4ef6\uff1a\n{exc}")
            return

        editor.setPlainText(content)
        self._show_import_preview(file_path, content, target_label)

        preview_state = self._document_loader.last_load_state
        if preview_state.extraction_mode == "pdf_ocr":
            range_label = preview_state.ocr_page_range or "\u9ed8\u8ba4\u9875\u7801"
            cache_label = "\u547d\u4e2d\u7f13\u5b58" if preview_state.ocr_cache_hit else "OCR \u65b0\u751f"
            self.statusBar().showMessage(
                f"\u5df2\u8f7d\u5165\u6587\u6863\uff1a{file_path}\uff08{cache_label}\uff0c\u9875\u7801 {range_label}\uff09",
                5000,
            )
            return

        self.statusBar().showMessage(f"\u5df2\u8f7d\u5165\u6587\u6863\uff1a{file_path}", 4000)

    def _clone_preview_state(self, preview_state: ImportPreviewState | None) -> ImportPreviewState:
        if preview_state is None:
            return ImportPreviewState()
        return ImportPreviewState(**asdict(preview_state))

    def _sync_document_loader_preview_state(self, preview_state: ImportPreviewState | None) -> ImportPreviewState:
        cloned_state = self._clone_preview_state(preview_state)
        self._document_loader.last_load_state = cloned_state
        return cloned_state

    def _load_batch_documents(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "批量导入文档",
            str(Path.home()),
            self._document_loader.file_dialog_filter(),
        )
        if not paths:
            return

        added_count = 0
        last_source_path = ""
        errors: list[str] = []

        for raw_path in paths:
            file_path = Path(raw_path)
            pdf_options = None
            if file_path.suffix.lower() == ".pdf" and self.config.enable_pdf_ocr:
                pdf_options = self._collect_pdf_import_options(file_path)
                if pdf_options is None:
                    continue

            try:
                content = self._document_loader.load_text_from_path(file_path, pdf_options=pdf_options)
            except DocumentImportError as exc:
                errors.append(f"{file_path.name}：{exc}")
                continue
            except Exception as exc:
                errors.append(f"{file_path.name}：{exc}")
                continue

            preview_state = self._clone_preview_state(self._document_loader.last_load_state)
            preview_markdown = build_import_preview_markdown(
                content,
                source_path=file_path,
                target_label="批量分析",
                config=self.config,
                preview_state=preview_state,
            )
            self._store_batch_document(
                {
                    "name": file_path.stem or file_path.name,
                    "display_name": file_path.name,
                    "source_path": str(file_path),
                    "text": content,
                    "preview_state": preview_state,
                    "preview_markdown": preview_markdown,
                }
            )
            added_count += 1
            last_source_path = str(file_path)

        self._refresh_batch_list(select_source_path=last_source_path)

        if added_count:
            self.statusBar().showMessage(f"已加入 {added_count} 份批量文档。", 5000)
        if errors:
            QMessageBox.warning(self, "部分文档未导入", "\n".join(errors[:8]))

    def _store_batch_document(self, record: dict[str, Any]) -> None:
        source_path = str(record.get("source_path", ""))
        for index, existing in enumerate(self._batch_documents):
            if str(existing.get("source_path", "")) == source_path:
                self._batch_documents[index] = record
                return
        self._batch_documents.append(record)

    def _refresh_batch_list(
        self,
        *,
        select_source_path: str = "",
        select_row: int | None = None,
    ) -> None:
        self.batch_list.blockSignals(True)
        self.batch_list.clear()
        for document in self._batch_documents:
            item = QListWidgetItem(str(document.get("display_name", document.get("name", ""))))
            item.setToolTip(str(document.get("source_path", "")))
            self.batch_list.addItem(item)
        self.batch_list.blockSignals(False)
        self._update_batch_summary()

        if not self._batch_documents:
            self._reset_preview_state()
            return

        target_row = 0
        if select_source_path:
            for index, document in enumerate(self._batch_documents):
                if str(document.get("source_path", "")) == select_source_path:
                    target_row = index
                    break
        elif select_row is not None:
            target_row = max(0, min(select_row, len(self._batch_documents) - 1))

        self.batch_list.setCurrentRow(target_row)
        self._show_batch_document_preview(target_row)

    def _update_batch_summary(self) -> None:
        self.batch_count_label.setText(f"当前已选择 {len(self._batch_documents)} 份文档")

    def _on_batch_selection_changed(self, current_row: int) -> None:
        if current_row < 0 or current_row >= len(self._batch_documents):
            return
        self._show_batch_document_preview(current_row)

    def _show_batch_document_preview(self, row: int) -> None:
        if row < 0 or row >= len(self._batch_documents):
            return
        document = self._batch_documents[row]
        preview_state = self._sync_document_loader_preview_state(document.get("preview_state"))
        self._apply_preview_status(preview_state)
        self.preview_view.setMarkdown(str(document.get("preview_markdown", "")))
        self.output_tab_widget.setCurrentIndex(1)

    def _remove_selected_batch_documents(self) -> None:
        rows = sorted({index.row() for index in self.batch_list.selectedIndexes()}, reverse=True)
        if not rows and self.batch_list.currentRow() >= 0:
            rows = [self.batch_list.currentRow()]
        if not rows:
            return

        for row in rows:
            if 0 <= row < len(self._batch_documents):
                self._batch_documents.pop(row)

        if not self._batch_documents:
            self._refresh_batch_list()
            self.statusBar().showMessage("批量文档列表已清空。", 4000)
            return

        next_row = min(min(rows), len(self._batch_documents) - 1)
        self._refresh_batch_list(select_row=next_row)
        self.statusBar().showMessage("已移除选中文档。", 4000)

    def _clear_batch_documents(self) -> None:
        self._batch_documents.clear()
        self._refresh_batch_list()
        self.statusBar().showMessage("已清空批量文档列表。", 4000)

    def _clear_single_input(self) -> None:
        self.single_input.clear()
        self._reset_preview_state()

    def _clear_compare_inputs(self) -> None:
        self.compare_old_input.clear()
        self.compare_new_input.clear()
        self._reset_preview_state()

    def _reset_preview_state(self) -> None:
        self._document_loader.reset_last_load_state()
        self._apply_preview_status(None)
        self.preview_view.setMarkdown(
            "# \u5bfc\u5165\u9884\u89c8\n\n"
            "\u5bfc\u5165 TXT / DOCX / PDF \u540e\uff0c\u8fd9\u91cc\u4f1a\u663e\u793a\u62bd\u53d6\u65b9\u5f0f\u3001\u6807\u9898\u533a\u3001\u6bb5\u843d\u7edf\u8ba1\u548c\u5f02\u5e38\u7a7a\u884c\u63d0\u793a\u3002"
        )

    def _apply_preview_status(self, preview_state) -> None:
        self.preview_hint_popover.hide()
        self.preview_hint_badge.setText(build_import_preview_hint_text(preview_state))
        self.preview_hint_badge.setStyleSheet(build_import_preview_hint_style(preview_state))
        self.preview_hint_badge.setToolTip(build_import_preview_hint_tooltip(preview_state))
        self.preview_status_label.setText(build_import_preview_status_text(preview_state))
        self.preview_status_label.setStyleSheet(build_import_preview_status_style(preview_state))



    def _build_result_export_payload(self) -> dict | None:
        if self._last_result is None:
            return None
        payload = dict(self._last_result)
        if self._inserted_preview_hint_notes:
            payload["import_preview_notes"] = list(self._inserted_preview_hint_notes)
        return payload

    def _build_pending_hint_notes_markdown(self) -> str:
        sections = [
            "# 待附加说明",
            "",
            "以下说明会在下一次分析结果和导出报告中自动附加：",
        ]
        for index, note in enumerate(self._inserted_preview_hint_notes, start=1):
            sections.extend(["", f"## 说明 {index}", "```text", note, "```"])
        return "\n".join(sections)

    def _refresh_result_view(self) -> None:
        payload = self._build_result_export_payload()
        if payload is not None:
            self.result_view.setMarkdown(self._result_formatter.to_markdown(payload))
            return
        if self._inserted_preview_hint_notes:
            self.result_view.setMarkdown(self._build_pending_hint_notes_markdown())

    def _copy_preview_hint_report(self) -> None:
        report_text = build_import_preview_hint_report_text(self._document_loader.last_load_state)
        QApplication.clipboard().setText(report_text)
        self.preview_hint_popover.hide()
        self.statusBar().showMessage("已复制轻提示说明。", 3000)

    def _insert_preview_hint_report(self) -> None:
        report_text = build_import_preview_hint_report_text(self._document_loader.last_load_state)
        if report_text in self._inserted_preview_hint_notes:
            self.preview_hint_popover.hide()
            self.output_tab_widget.setCurrentIndex(0)
            self._refresh_result_view()
            self.statusBar().showMessage("该说明已在分析结果中。", 3000)
            return

        self._inserted_preview_hint_notes.append(report_text)
        if self._last_result is not None:
            self._last_result["import_preview_notes"] = list(self._inserted_preview_hint_notes)
        self.preview_hint_popover.hide()
        self.output_tab_widget.setCurrentIndex(0)
        self._refresh_result_view()
        self.statusBar().showMessage("已插入轻提示说明，后续导出会自动带上。", 4000)

    def _toggle_preview_hint_popover(self) -> None:
        if self.preview_hint_popover.isVisible():
            self.preview_hint_popover.hide()
            return
        self._show_preview_hint_popover(self._document_loader.last_load_state)

    def _show_preview_hint_popover(self, preview_state) -> None:
        self.preview_hint_popover.set_content(
            build_import_preview_hint_text(preview_state),
            build_import_preview_hint_tooltip(preview_state),
        )

        anchor = self.preview_hint_badge.mapToGlobal(QPoint(0, self.preview_hint_badge.height() + 8))
        x = anchor.x()
        y = anchor.y()

        screen = self.screen()
        if screen is not None:
            geometry = screen.availableGeometry()
            x = min(max(x, geometry.left() + 12), geometry.right() - self.preview_hint_popover.width() - 12)
            if y + self.preview_hint_popover.height() > geometry.bottom() - 12:
                above = self.preview_hint_badge.mapToGlobal(QPoint(0, -self.preview_hint_popover.height() - 8))
                y = max(geometry.top() + 12, above.y())

        self.preview_hint_popover.move(x, y)
        self.preview_hint_popover.show()
        self.preview_hint_popover.raise_()

    def _show_import_preview(self, source_path: str | Path, content: str, target_label: str) -> None:
        preview_state = self._document_loader.last_load_state
        markdown = build_import_preview_markdown(
            content,
            source_path=source_path,
            target_label=target_label,
            config=self.config,
            preview_state=preview_state,
        )
        self._apply_preview_status(preview_state)
        self.preview_view.setMarkdown(markdown)
        self.output_tab_widget.setCurrentIndex(1)

    def _start_single_analysis(self) -> None:
        text = self.single_input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "缺少文本", "请先输入或导入要分析的政策文本。")
            return
        self._start_analysis(ANALYSIS_MODE_SINGLE, text)

    def _start_compare_analysis(self) -> None:
        old_text = self.compare_old_input.toPlainText().strip()
        new_text = self.compare_new_input.toPlainText().strip()
        if not old_text or not new_text:
            QMessageBox.information(self, "缺少文本", "双篇比对需要同时提供旧稿和新稿。")
            return
        self._start_analysis(ANALYSIS_MODE_COMPARE, old_text, new_text)

    def _start_batch_analysis(self) -> None:
        batch_inputs = [
            {
                "name": str(document.get("name", "")),
                "source_path": str(document.get("source_path", "")),
                "text": str(document.get("text", "")),
            }
            for document in self._batch_documents
            if str(document.get("text", "")).strip()
        ]
        if not batch_inputs:
            QMessageBox.information(self, "缺少文本", "批量分析至少需要导入一份有效文档。")
            return
        self._start_analysis(ANALYSIS_MODE_BATCH, "", batch_inputs=batch_inputs)

    def _start_analysis(self, mode: str, primary_text: str, secondary_text: str = "", batch_inputs: list[dict[str, str]] | None = None) -> None:
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            QMessageBox.information(self, "任务进行中", "当前已有分析任务在运行，请等待完成或先取消。")
            return

        self._last_result = None
        self._update_export_state()
        self.progress_bar.setValue(0)
        status_text = {
            ANALYSIS_MODE_SINGLE: "正在启动单篇分析任务",
            ANALYSIS_MODE_COMPARE: "正在启动双篇比对任务",
            ANALYSIS_MODE_BATCH: "正在启动批量分析任务",
        }.get(mode, "正在启动后台分析任务")
        self.status_label.setText(status_text)
        self.result_view.setMarkdown("# 正在分析\n\n请稍候，结果生成后会自动显示。")
        self.output_tab_widget.setCurrentIndex(0)
        self.statusBar().showMessage("分析任务已启动")
        self._set_busy_state(True)

        self._analysis_thread = NLPAnalysisThread(
            mode=mode,
            primary_text=primary_text,
            secondary_text=secondary_text,
            config=self.config,
            parent=self,
            batch_inputs=batch_inputs,
            analysis_mode=self.config.analysis_mode,
        )
        self._analysis_thread.progress_changed.connect(self._on_progress_changed)
        self._analysis_thread.status_changed.connect(self._on_status_changed)
        self._analysis_thread.result_ready.connect(self._on_result_ready)
        self._analysis_thread.error_occurred.connect(self._on_error_occurred)
        self._analysis_thread.finished.connect(self._on_thread_finished)
        self._analysis_thread.start()

    def _cancel_analysis(self) -> None:
        if self._analysis_thread is None or not self._analysis_thread.isRunning():
            return
        self._analysis_thread.request_cancel()
        self.status_label.setText("正在请求取消任务")
        self.statusBar().showMessage("已发送取消请求")

    def _on_progress_changed(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(max(0, min(100, percent)))
        if message:
            self.status_label.setText(message)
            self.statusBar().showMessage(message)

    def _on_status_changed(self, status: str) -> None:
        if status:
            self.status_label.setText(status)
            self.statusBar().showMessage(status)

    def _on_result_ready(self, result: dict) -> None:
        self._last_result = result
        route_message = str(result.get("analysis_route_message", "") or "").strip()
        route_text = build_analysis_route_text(result)
        if self._inserted_preview_hint_notes:
            self._last_result["import_preview_notes"] = list(self._inserted_preview_hint_notes)
        self._refresh_result_view()
        self.output_tab_widget.setCurrentIndex(0)
        self.progress_bar.setValue(100)
        if route_message:
            self.status_label.setText(route_message)
            self.statusBar().showMessage(f"{route_text} {route_message}", 6000)
        self._update_export_state()

    def _on_error_occurred(self, message: str) -> None:
        self._last_result = None
        self._update_export_state()
        self.result_view.setMarkdown(f"# 分析失败\n\n{message}")
        self.output_tab_widget.setCurrentIndex(0)
        QMessageBox.warning(self, "分析失败", message)

    def _on_thread_finished(self) -> None:
        self._set_busy_state(False)
        self._analysis_thread = None
        self._update_export_state()

    def _set_busy_state(self, busy: bool) -> None:
        for widget in self._busy_controls:
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def _update_export_state(self) -> None:
        export_enabled = self._last_result is not None and not (
            self._analysis_thread is not None and self._analysis_thread.isRunning()
        )
        self.export_markdown_button.setEnabled(export_enabled)
        self.export_html_button.setEnabled(export_enabled)
        self.export_json_button.setEnabled(export_enabled)

    def _export_markdown(self) -> None:
        if self._last_result is None:
            return
        initial_name = self._result_formatter.build_export_base_name(self._last_result)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Markdown 分析报告",
            str(Path.home() / f"{initial_name}.md"),
            "Markdown 文件 (*.md);;所有文件 (*.*)",
        )
        if not path:
            return

        try:
            export_payload = self._build_result_export_payload()
            if export_payload is None:
                return
            Path(path).write_text(
                self._result_formatter.to_markdown(export_payload),
                encoding="utf-8-sig",
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{exc}")
            return

        self.statusBar().showMessage(f"分析报告已导出：{path}", 5000)

    def _export_html(self) -> None:
        if self._last_result is None:
            return
        initial_name = self._result_formatter.build_export_base_name(self._last_result)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 HTML 分析报告",
            str(Path.home() / f"{initial_name}.html"),
            "HTML 文件 (*.html);;所有文件 (*.*)",
        )
        if not path:
            return

        try:
            export_payload = self._build_result_export_payload()
            if export_payload is None:
                return
            Path(path).write_text(
                self._result_formatter.to_html_report(export_payload),
                encoding="utf-8-sig",
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{exc}")
            return

        self.statusBar().showMessage(f"HTML 报告已导出：{path}", 5000)

    def _export_json(self) -> None:
        if self._last_result is None:
            return
        initial_name = self._result_formatter.build_export_base_name(self._last_result)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 JSON 结果",
            str(Path.home() / f"{initial_name}.json"),
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return

        try:
            export_payload = self._build_result_export_payload()
            if export_payload is None:
                return
            Path(path).write_text(
                self._result_formatter.to_json_text(export_payload),
                encoding="utf-8-sig",
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"无法写入文件：\n{exc}")
            return

        self.statusBar().showMessage(f"JSON 结果已导出：{path}", 5000)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            answer = QMessageBox.question(
                self,
                "任务仍在运行",
                "后台分析任务仍在执行，确定要退出程序吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self._analysis_thread.request_cancel()
            self._analysis_thread.wait(1500)

        event.accept()
