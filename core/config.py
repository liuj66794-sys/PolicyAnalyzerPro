from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_RELATIVE_PATH = "config/default_config.json"

DEFAULT_POLITICAL_STOPWORDS = [
    "中国",
    "全国",
    "人民",
    "党中央",
    "国务院",
    "地方",
    "部门",
    "工作",
    "会议",
    "报告",
    "意见",
    "要求",
    "任务",
    "落实",
    "推进",
    "推动",
    "坚持",
    "加强",
    "完善",
    "提升",
    "深化",
    "实施",
    "促进",
    "加快",
    "发展",
    "进一步",
    "全面",
    "持续",
    "积极",
    "切实",
    "扎实",
]

DEFAULT_HISTORICAL_BASELINE_TERMS = [
    "高质量发展",
    "新发展格局",
    "中国式现代化",
    "乡村振兴",
    "共同富裕",
    "依法治国",
]

DEFAULT_NOISE_PATTERNS = [
    r"^\s*新华社.*(?:电|讯)\s*$",
    r"^\s*(央视网消息|人民网.*|中新网.*|经济日报.*|人民日报.*)\s*$",
    r"^\s*(来源|责任编辑|编辑|记者|作者|审核|校对)[:：].*$",
    r"^\s*(原标题|编者按|导读)[:：].*$",
    r"^\s*点击(?:查看更多|进入专题).*$",
    r"^\s*[【\[].*(?:打印|关闭窗口|返回顶部|责任编辑).*[】\]]\s*$",
]

DEFAULT_INLINE_NOISE_PATTERNS = [
    r"新华社(?:北京|上海|广州|深圳|[^\s]{0,10})?\d{0,2}月?\d{0,2}日?电",
    r"(?:责任编辑|编辑|审核|校对)[:：][^\n]+",
    r"【(?:打印|关闭窗口|返回顶部)】",
    r"\((?:完|记者[^\)]{0,20})\)",
]


def get_project_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def get_resource_path(relative_path: str) -> str:
    """
    Resolve bundled resources for both source runs and PyInstaller --onedir builds.
    """
    return str((get_project_root() / relative_path).resolve())


def apply_tesseract_runtime_environment(tesseract_cmd: str) -> None:
    command = (tesseract_cmd or "").strip()
    if not command:
        return

    exe_path = Path(command)
    if not exe_path.exists():
        return

    bin_dir = exe_path.parent
    root_dir = None
    if bin_dir.name.lower() == "bin" and bin_dir.parent.name.lower() == "library":
        root_dir = bin_dir.parent.parent

    existing_parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    prefixes: list[str] = []
    if root_dir is not None:
        prefixes.append(str(root_dir))
    prefixes.append(str(bin_dir))

    for prefix in reversed(prefixes):
        if prefix not in existing_parts:
            existing_parts.insert(0, prefix)
    os.environ["PATH"] = os.pathsep.join(existing_parts)

    tessdata_candidates = []
    if root_dir is not None:
        tessdata_candidates.append(root_dir / "share" / "tessdata")
    tessdata_candidates.append(bin_dir.parent / "share" / "tessdata")

    for candidate in tessdata_candidates:
        if candidate.exists():
            os.environ["TESSDATA_PREFIX"] = str(candidate)
            break


@dataclass(slots=True)
class AppConfig:
    app_name: str = "PolicyAnalyzerPro"
    model_dir: str = "models/hfl/chinese-roberta-wwm-ext"
    font_path: str = "assets/fonts/simhei.ttf"
    custom_dictionary_path: str = "assets/dicts/custom_words.txt"
    political_stopwords: list[str] = field(
        default_factory=lambda: list(DEFAULT_POLITICAL_STOPWORDS)
    )
    historical_baseline_terms: list[str] = field(
        default_factory=lambda: list(DEFAULT_HISTORICAL_BASELINE_TERMS)
    )
    noise_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_NOISE_PATTERNS))
    inline_noise_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_INLINE_NOISE_PATTERNS)
    )
    tfidf_top_k: int = 15
    textrank_top_k: int = 15
    sentence_similarity_lower: float = 0.70
    sentence_similarity_upper: float = 0.95
    weakening_ratio_threshold: float = 0.80
    process_pool_workers: int = 1
    torch_num_threads: int = 2
    local_files_only: bool = True
    enable_model_trial_load_check: bool = True
    enable_model_warmup_benchmark_check: bool = True
    model_benchmark_batch_size: int = 4
    model_acceptable_load_ms: float = 8000.0
    model_acceptable_warmup_ms: float = 2500.0
    model_acceptable_single_encode_ms: float = 700.0
    model_acceptable_batch_encode_ms: float = 2200.0
    model_acceptable_batch_item_ms: float = 550.0
    model_benchmark_samples: list[str] = field(
        default_factory=lambda: [
            "加快建设现代化产业体系，发展新质生产力。",
            "着力扩大国内需求，推动消费和投资更好结合。",
            "深入推进绿色低碳转型，积极稳妥推进碳达峰碳中和。",
            "更大力度保障和改善民生，兜牢基层三保底线。",
        ]
    )
    enable_pdf_ocr: bool = True
    ocr_languages: str = "chi_sim+eng"
    tesseract_cmd: str = ""
    pdf_ocr_zoom: float = 2.0
    pdf_ocr_max_pages: int = 20
    enable_ocr_result_cache: bool = True
    ocr_cache_dir: str = "cache/ocr"
    offline_env: dict[str, str] = field(
        default_factory=lambda: {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )

    @property
    def resolved_model_dir(self) -> str:
        return get_resource_path(self.model_dir)

    @property
    def resolved_font_path(self) -> str:
        return get_resource_path(self.font_path)

    @property
    def resolved_custom_dictionary_path(self) -> str:
        return get_resource_path(self.custom_dictionary_path)

    @property
    def resolved_ocr_cache_dir(self) -> str:
        return get_resource_path(self.ocr_cache_dir)

    @classmethod
    def from_json(cls, json_path: str | Path) -> "AppConfig":
        path = Path(json_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Configuration JSON must contain a top-level object.")

        return cls().merge(data)

    def merge(self, overrides: dict[str, Any]) -> "AppConfig":
        valid_fields = set(self.__dataclass_fields__.keys())
        normalized: dict[str, Any] = {}

        for key, value in overrides.items():
            if key not in valid_fields:
                continue
            normalized[key] = value

        merged = asdict(self)
        merged.update(normalized)
        return AppConfig(**merged)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_CONFIG = AppConfig()


def load_app_config(config_path: str | Path | None = None) -> AppConfig:
    if config_path is not None:
        return AppConfig.from_json(config_path)

    env_config = os.environ.get("POLICY_ANALYZER_CONFIG")
    if env_config:
        env_path = Path(env_config)
        if env_path.exists():
            return AppConfig.from_json(env_path)

    bundled_path = Path(get_resource_path(DEFAULT_CONFIG_RELATIVE_PATH))
    if bundled_path.exists():
        return AppConfig.from_json(bundled_path)

    return DEFAULT_CONFIG
