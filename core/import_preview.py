from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.config import AppConfig, DEFAULT_CONFIG
from core.text_cleaner import TextCleaner

_AUTHOR_ROLE_MARKERS = (
    "国务院总理",
    "国务院副总理",
    "全国人大常委会委员长",
    "全国政协主席",
    "全国政协副主席",
    "国家主席",
    "最高人民法院院长",
    "最高人民检察院检察长",
    "部长",
    "主任",
    "秘书长",
)

_BODY_START_PATTERNS = (
    re.compile(r"^各位代表[:：]"),
    re.compile(r"^[一二三四五六七八九十]+[、.]"),
    re.compile(r"^（[一二三四五六七八九十]+）"),
)

_SECTION_HEADING_PATTERNS = (
    re.compile(r"^[一二三四五六七八九十]+[、.]"),
    re.compile(r"^（[一二三四五六七八九十]+）"),
)

_EXTRACTION_LABELS = {
    "text_file": "TXT / 文本",
    "docx": "DOCX 文档",
    "pdf_text_layer": "文字层 PDF",
    "pdf_ocr": "OCR",
}


@dataclass(slots=True)
class ImportPreviewState:
    source_path: str = ""
    source_suffix: str = ""
    extraction_mode: str = ""
    raw_char_count: int = 0
    non_empty_line_count: int = 0
    cleaned_paragraph_count: int = 0
    abnormal_blank_lines: bool = False
    ocr_page_range: str = ""
    ocr_page_count: int = 0
    ocr_cache_hit: bool = False

    @property
    def has_document(self) -> bool:
        return bool(self.source_path)


def build_import_preview_markdown(
    text: str,
    source_path: str | Path,
    target_label: str,
    config: AppConfig | None = None,
    preview_state: ImportPreviewState | None = None,
) -> str:
    config = config or DEFAULT_CONFIG
    cleaner = TextCleaner(config)
    preferred_source = preview_state.source_path if preview_state and preview_state.source_path else source_path
    source = Path(preferred_source)
    stripped = text.strip()

    if not stripped:
        return "# \u5bfc\u5165\u9884\u89c8\n\n\u672a\u63d0\u53d6\u5230\u53ef\u7528\u6587\u672c\u3002"

    non_empty_lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    title_lines = _extract_cover_lines(non_empty_lines)
    cleaned_paragraphs = cleaner.clean_paragraphs(stripped)
    body_preview = _extract_body_preview(cleaned_paragraphs, title_lines)
    raw_char_count = preview_state.raw_char_count if preview_state and preview_state.raw_char_count else len(stripped)
    line_count = preview_state.non_empty_line_count if preview_state and preview_state.non_empty_line_count else len(non_empty_lines)
    paragraph_count = (
        preview_state.cleaned_paragraph_count
        if preview_state and preview_state.cleaned_paragraph_count
        else len(cleaned_paragraphs)
    )

    sections = [
        "# \u5bfc\u5165\u9884\u89c8",
        "",
        "## \u6587\u6863\u4fe1\u606f",
        f"- \u6587\u4ef6\u540d\uff1a{source.name}",
        f"- \u5bfc\u5165\u76ee\u6807\uff1a{target_label}",
        f"- \u6587\u4ef6\u7c7b\u578b\uff1a{source.suffix.lower() or '\u65e0\u540e\u7f00'}",
        f"- \u539f\u59cb\u5b57\u7b26\u6570\uff1a{raw_char_count}",
        f"- \u975e\u7a7a\u884c\u6570\uff1a{line_count}",
        f"- \u6e05\u6d17\u540e\u6bb5\u843d\u6570\uff1a{paragraph_count}",
    ]

    if preview_state and preview_state.extraction_mode == "pdf_ocr":
        if preview_state.ocr_page_range:
            sections.append(f"- OCR \u9875\u7801\u8303\u56f4\uff1a{preview_state.ocr_page_range}")
        if preview_state.ocr_page_count:
            sections.append(f"- OCR \u5b9e\u9645\u9875\u6570\uff1a{preview_state.ocr_page_count}")
        sections.append(f"- OCR \u7f13\u5b58\uff1a{_build_ocr_cache_status_label(preview_state)}")

    sections.extend(["", "## \u6807\u9898\u533a\u9884\u89c8"])

    if title_lines:
        sections.extend(f"> {line}" for line in title_lines)
    else:
        sections.append("- \u672a\u8bc6\u522b\u5230\u660e\u663e\u7684\u6807\u9898\u533a\u3002")

    sections.extend(["", "## \u6b63\u6587\u524d\u51e0\u6bb5"])

    if body_preview:
        sections.extend(
            f"{index}. {paragraph}" for index, paragraph in enumerate(body_preview, start=1)
        )
    else:
        sections.append("- \u6e05\u6d17\u540e\u672a\u63d0\u53d6\u5230\u53ef\u9884\u89c8\u7684\u6b63\u6587\u6bb5\u843d\u3002")

    sections.extend(["", "\u7f16\u8f91\u533a\u5df2\u586b\u5165\u5b8c\u6574\u6587\u672c\uff0c\u53ef\u76f4\u63a5\u7ee7\u7eed\u5206\u6790\u3002"])
    return "\n".join(sections)


def build_import_preview_hint_text(preview_state: ImportPreviewState | None) -> str:
    if preview_state is None or not preview_state.has_document:
        return "轻提示：未导入"
    return f"轻提示：{_build_import_preview_hint_label(preview_state)}"



def build_import_preview_hint_tooltip(preview_state: ImportPreviewState | None) -> str:
    if preview_state is None or not preview_state.has_document:
        return (
            "\u5c1a\u672a\u5bfc\u5165\u6587\u6863\u3002\n"
            "\u5bfc\u5165\u540e\u8fd9\u4e2a badge \u4f1a\u6839\u636e\u62bd\u53d6\u65b9\u5f0f\u548c\u6587\u672c\u8d28\u91cf\u7ed9\u51fa\u8f7b\u63d0\u793a\u3002\n"
            "\u5efa\u8bae\uff1a\u5148\u5bfc\u5165 TXT / DOCX / PDF \u6587\u6863\u3002"
        )
    if preview_state.abnormal_blank_lines:
        return (
            "\u5224\u5b9a\u4e3a\u300c\u7a7a\u884c\u5f02\u5e38\u300d\uff1a\u6e05\u6d17\u540e\u6587\u672c\u4e2d\u4ecd\u68c0\u6d4b\u5230\u8fde\u7eed\u4e09\u4e2a\u53ca\u4ee5\u4e0a\u7a7a\u884c\u3002\n"
            "\u8fd9\u901a\u5e38\u610f\u5473\u7740\u5206\u9875\u6b8b\u7559\u3001\u7248\u9762\u65ad\u88c2\uff0c\u6216 OCR / PDF \u63d0\u53d6\u7ed3\u679c\u4e0d\u7a33\u5b9a\uff0c\u5efa\u8bae\u5148\u68c0\u67e5\u7f16\u8f91\u533a\u91cc\u7684\u6bb5\u843d\u8fb9\u754c\u3002\n"
            "\u5efa\u8bae\uff1a\u5148\u68c0\u67e5\u7f16\u8f91\u533a\u7b2c 1-3 \u6bb5\u548c\u7a7a\u884c\u5bc6\u96c6\u4f4d\u7f6e\u3002"
        )
    if preview_state.extraction_mode == "pdf_ocr":
        cache_note = (
            "\u672c\u6b21 OCR \u7ed3\u679c\u76f4\u63a5\u6765\u81ea\u672c\u5730\u7f13\u5b58\uff0c\u9002\u5408\u5bf9\u540c\u4e00\u4efd PDF \u91cd\u590d\u590d\u6838\u3002"
            if preview_state.ocr_cache_hit
            else "\u672c\u6b21 OCR \u7ed3\u679c\u4e3a\u65b0\u751f\u6210\uff0c\u540e\u7eed\u91cd\u590d\u5bfc\u5165\u76f8\u540c\u9875\u7801\u8303\u56f4\u53ef\u76f4\u63a5\u547d\u4e2d\u7f13\u5b58\u3002"
        )
        page_note = (
            f"\nOCR \u9875\u7801\u8303\u56f4\uff1a{preview_state.ocr_page_range}\u3002"
            if preview_state.ocr_page_range
            else ""
        )
        return (
            "\u5224\u5b9a\u4e3a\u300cOCR \u590d\u6838\u300d\uff1a\u539f PDF \u6ca1\u6709\u7a33\u5b9a\u6587\u5b57\u5c42\uff0c\u5f53\u524d\u6587\u672c\u6765\u81ea OCR \u8bc6\u522b\u3002\n"
            "OCR \u4f1a\u53d7\u626b\u63cf\u6e05\u6670\u5ea6\u3001\u6392\u7248\u548c\u5b57\u4f53\u5f71\u54cd\uff0c\u5efa\u8bae\u5148\u5feb\u901f\u6838\u5bf9\u6807\u9898\u533a\u548c\u6b63\u6587\u524d\u51e0\u6bb5\u3002"
            f"{page_note}\n"
            f"{cache_note}\n"
            "\u5efa\u8bae\uff1a\u5148\u68c0\u67e5\u7f16\u8f91\u533a\u7b2c 1-3 \u6bb5\u3002"
        )
    if preview_state.extraction_mode == "pdf_text_layer":
        return (
            "\u5224\u5b9a\u4e3a\u300c\u6587\u5b57\u5c42\u76f4\u8bfb\u300d\uff1a\u68c0\u6d4b\u5230 PDF \u81ea\u5e26\u6587\u5b57\u5c42\uff0c\u5f53\u524d\u6587\u672c\u76f4\u63a5\u6765\u81ea\u6587\u5b57\u5c42\u63d0\u53d6\u3002\n"
            "\u8fd9\u79cd\u60c5\u51b5\u901a\u5e38\u6bd4 OCR \u66f4\u7a33\u5b9a\uff0c\u4f46\u4ecd\u53ef\u80fd\u5e26\u5165\u9875\u811a\u3001\u65ad\u884c\u6216\u91cd\u590d\u6807\u9898\u3002\n"
            "\u5efa\u8bae\uff1a\u5148\u5feb\u901f\u6d4f\u89c8\u6807\u9898\u533a\u548c\u6b63\u6587\u524d\u51e0\u6bb5\u3002"
        )
    if preview_state.extraction_mode == "docx":
        return (
            "\u5224\u5b9a\u4e3a\u300c\u6587\u6863\u76f4\u8bfb\u300d\uff1a\u5f53\u524d\u5185\u5bb9\u76f4\u63a5\u6765\u81ea DOCX \u7ed3\u6784\u5316\u6587\u672c\u62bd\u53d6\u3002\n"
            "\u5efa\u8bae\uff1a\u5148\u5feb\u901f\u68c0\u67e5\u6807\u9898\u548c\u5173\u952e\u6bb5\u843d\u662f\u5426\u5b8c\u6574\u3002"
        )
    if preview_state.extraction_mode == "text_file":
        return (
            "\u5224\u5b9a\u4e3a\u300c\u6587\u672c\u76f4\u8bfb\u300d\uff1a\u5f53\u524d\u5185\u5bb9\u76f4\u63a5\u6765\u81ea TXT / \u7eaf\u6587\u672c\u6587\u4ef6\uff0c\u672a\u7ecf\u8fc7 OCR \u3002\n"
            "\u5efa\u8bae\uff1a\u5148\u7a0d\u5fae\u68c0\u67e5\u5f00\u5934\u6bb5\u843d\u548c\u4e3b\u8981\u6807\u9898\u3002"
        )
    return (
        "\u5f53\u524d\u6587\u6863\u5df2\u5b8c\u6210\u6807\u51c6\u5bfc\u5165\u6d41\u7a0b\u3002\n"
        "\u5efa\u8bae\uff1a\u5feb\u901f\u68c0\u67e5\u6807\u9898\u533a\u548c\u6b63\u6587\u524d\u51e0\u6bb5\u3002"
    )


def build_import_preview_hint_report_text(preview_state: ImportPreviewState | None) -> str:
    title = build_import_preview_hint_text(preview_state)
    status = build_import_preview_status_text(preview_state)
    detail = build_import_preview_hint_tooltip(preview_state)
    return (
        f"{title}\n"
        f"{status}\n\n"
        "判定说明：\n"
        f"{detail}"
    )


def build_import_preview_status_text(preview_state: ImportPreviewState | None) -> str:
    if preview_state is None or not preview_state.has_document:
        return (
            "\u5c1a\u672a\u5bfc\u5165\u6587\u6863\u3002"
            "\u5bfc\u5165\u540e\u4f1a\u5728\u8fd9\u91cc\u663e\u793a\u5bfc\u5165\u8def\u5f84\u3001"
            "\u6e05\u6d17\u540e\u6bb5\u843d\u6570\u548c\u7a7a\u884c\u68c0\u67e5\u7ed3\u679c\u3002"
        )

    extraction_label = _EXTRACTION_LABELS.get(preview_state.extraction_mode, "\u672a\u8bc6\u522b")
    blank_line_label = (
        "\u68c0\u6d4b\u5230\u5f02\u5e38\u7a7a\u884c"
        if preview_state.abnormal_blank_lines
        else "\u672a\u53d1\u73b0\u5f02\u5e38\u7a7a\u884c"
    )
    parts = [
        f"\u68c0\u6d4b\u5230\uff1a{extraction_label}",
        f"\u6e05\u6d17\u540e\u6bb5\u843d\uff1a{preview_state.cleaned_paragraph_count}",
    ]
    if preview_state.extraction_mode == "pdf_ocr":
        if preview_state.ocr_page_range:
            parts.append(f"OCR \u9875\u7801\uff1a{preview_state.ocr_page_range}")
        if preview_state.ocr_page_count:
            parts.append(f"OCR \u9875\u6570\uff1a{preview_state.ocr_page_count}")
        parts.append(f"OCR \u7f13\u5b58\uff1a{_build_ocr_cache_status_label(preview_state)}")
    parts.append(f"\u7a7a\u884c\u68c0\u67e5\uff1a{blank_line_label}")
    return "  |  ".join(parts)


def build_import_preview_hint_style(preview_state: ImportPreviewState | None) -> str:
    base = (
        "QLabel {"
        "font-size: 11px; font-weight: 700; color: #475467; background: #f2f4f7; "
        "border: 1px solid #d0d5dd; border-radius: 999px; padding: 4px 10px;"
        "}"
        "QLabel:hover {"
        "background: #e4e7ec; border: 1px solid #98a2b3;"
        "}"
    )
    if preview_state is None or not preview_state.has_document:
        return base
    if preview_state.abnormal_blank_lines:
        return (
            "QLabel {"
            "font-size: 11px; font-weight: 700; color: #9a3412; background: #fff7ed; "
            "border: 1px solid #fdba74; border-radius: 999px; padding: 4px 10px;"
            "}"
            "QLabel:hover {"
            "background: #ffedd5; border: 1px solid #fb923c;"
            "}"
        )
    if preview_state.extraction_mode == "pdf_ocr":
        return (
            "QLabel {"
            "font-size: 11px; font-weight: 700; color: #7c2d12; background: #fffbeb; "
            "border: 1px solid #fcd34d; border-radius: 999px; padding: 4px 10px;"
            "}"
            "QLabel:hover {"
            "background: #fef3c7; border: 1px solid #f59e0b;"
            "}"
        )
    if preview_state.extraction_mode == "pdf_text_layer":
        return (
            "QLabel {"
            "font-size: 11px; font-weight: 700; color: #1d4ed8; background: #eff6ff; "
            "border: 1px solid #93c5fd; border-radius: 999px; padding: 4px 10px;"
            "}"
            "QLabel:hover {"
            "background: #dbeafe; border: 1px solid #60a5fa;"
            "}"
        )
    return base


def build_import_preview_status_style(preview_state: ImportPreviewState | None) -> str:
    if preview_state is None or not preview_state.has_document:
        return "font-size: 12px; color: #667085; padding: 4px 0;"
    return "font-size: 12px; color: #344054; padding: 4px 0;"



def _build_ocr_cache_status_label(preview_state: ImportPreviewState) -> str:
    return "命中" if preview_state.ocr_cache_hit else "新生成"


def _build_import_preview_hint_label(preview_state: ImportPreviewState) -> str:
    if preview_state.abnormal_blank_lines:
        return "空行异常"
    if preview_state.extraction_mode == "pdf_ocr":
        return "OCR 复核"
    if preview_state.extraction_mode == "pdf_text_layer":
        return "文字层直读"
    if preview_state.extraction_mode == "docx":
        return "文档直读"
    if preview_state.extraction_mode == "text_file":
        return "文本直读"
    return "标准导入"


def _extract_cover_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []

    cover = [lines[0]]
    for line in lines[1:4]:
        if _looks_like_body_start(line):
            break
        if line.startswith(("——", "--")) or _looks_like_author_line(line):
            cover.append(line)
            continue
        if len(cover) == 1 and len(line) <= 48 and not line.endswith("。"):
            cover.append(line)
            continue
        break
    return cover[:3]


def _extract_body_preview(paragraphs: list[str], cover_lines: list[str]) -> list[str]:
    if not paragraphs:
        return []

    normalized_cover = {_normalize_compare_key(line) for line in cover_lines}
    preview: list[str] = []
    for paragraph in paragraphs:
        key = _normalize_compare_key(paragraph)
        if not key or key in normalized_cover:
            continue
        if _looks_like_author_line(paragraph) or _looks_like_section_heading(paragraph):
            continue
        preview.append(_truncate_paragraph(paragraph))
        if len(preview) >= 3:
            break
    return preview


def _normalize_compare_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _looks_like_author_line(line: str) -> bool:
    return any(marker in line for marker in _AUTHOR_ROLE_MARKERS)


def _looks_like_body_start(line: str) -> bool:
    return any(pattern.match(line) for pattern in _BODY_START_PATTERNS)


def _looks_like_section_heading(line: str) -> bool:
    return any(pattern.match(line) for pattern in _SECTION_HEADING_PATTERNS)


def _truncate_paragraph(text: str, max_length: int = 220) -> str:
    compact = text.strip()
    if len(compact) <= max_length:
        return compact
    return compact[:max_length].rstrip() + "..."
