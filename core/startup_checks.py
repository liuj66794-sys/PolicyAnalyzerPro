from __future__ import annotations

import importlib.util
import os
import re
import shutil
from html import escape
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Callable

from core.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_RELATIVE_PATH,
    AppConfig,
    apply_tesseract_runtime_environment,
    get_resource_path,
)

STARTUP_WIZARD_VERSION = "deployment-v6"

_CHECK_OK = "ok"
_CHECK_WARNING = "warning"
_CHECK_ERROR = "error"

_STATUS_SEVERITY = {
    _CHECK_OK: 0,
    _CHECK_WARNING: 1,
    _CHECK_ERROR: 2,
}


@dataclass(slots=True)
class DeploymentCheck:
    key: str
    title: str
    status: str
    summary: str
    detail: str = ""
    hint: str = ""
    location: str = ""
    required: bool = True


@dataclass(slots=True)
class DeploymentCheckTransition:
    key: str
    title: str
    previous_status: str | None
    current_status: str | None
    previous_summary: str = ""
    current_summary: str = ""

    @property
    def changed(self) -> bool:
        return (
            self.previous_status != self.current_status
            or self.previous_summary != self.current_summary
        )

    @property
    def direction(self) -> str:
        previous = _STATUS_SEVERITY.get(self.previous_status or _CHECK_OK, 0)
        current = _STATUS_SEVERITY.get(self.current_status or _CHECK_OK, 0)
        if current < previous:
            return "improved"
        if current > previous:
            return "regressed"
        if self.changed:
            return "updated"
        return "unchanged"

    @property
    def label(self) -> str:
        if not self.changed:
            return ""
        if self.previous_status is None:
            return f"新增 -> {self.current_status}"
        if self.current_status is None:
            return f"移除 ({self.previous_status})"
        if self.previous_status != self.current_status:
            return f"{self.previous_status} -> {self.current_status}"
        return "细节更新"


@dataclass(slots=True)
class StartupCheckReport:
    results: list[DeploymentCheck]
    checked_at: str
    wizard_version: str = STARTUP_WIZARD_VERSION

    @property
    def ok_count(self) -> int:
        return sum(item.status == _CHECK_OK for item in self.results)

    @property
    def warning_count(self) -> int:
        return sum(item.status == _CHECK_WARNING for item in self.results)

    @property
    def error_count(self) -> int:
        return sum(item.status == _CHECK_ERROR for item in self.results)

    @property
    def has_critical_issues(self) -> bool:
        return self.error_count > 0

    @property
    def overall_status(self) -> str:
        if self.has_critical_issues:
            return _CHECK_ERROR
        if self.warning_count > 0:
            return _CHECK_WARNING
        return _CHECK_OK

    @property
    def overall_label(self) -> str:
        if self.overall_status == _CHECK_ERROR:
            return "需修复"
        if self.overall_status == _CHECK_WARNING:
            return "建议完善"
        return "部署就绪"

    @property
    def summary_text(self) -> str:
        return (
            f"共检查 {len(self.results)} 项：通过 {self.ok_count} 项，"
            f"警告 {self.warning_count} 项，错误 {self.error_count} 项。"
        )

    @property
    def signature(self) -> str:
        return "|".join(
            f"{item.key}:{item.status}:{item.summary}" for item in self.results
        )

    def by_key(self) -> dict[str, DeploymentCheck]:
        return {item.key: item for item in self.results}


@dataclass(slots=True)
class ModelRuntimeProfile:
    embedding_dim: int | None
    model_load_ms: float
    warmup_ms: float
    single_encode_ms: float
    batch_encode_ms: float
    batch_size: int
    batch_item_ms: float
    throughput_items_per_second: float

    @property
    def trial_detail(self) -> str:
        dimension_text = (
            f"\u5411\u91cf\u7ef4\u5ea6 {self.embedding_dim}"
            if self.embedding_dim is not None
            else "\u5411\u91cf\u7ef4\u5ea6\u672a\u8bc6\u522b"
        )
        return (
            f"\u8bd5\u52a0\u8f7d\u6210\u529f\uff0c{dimension_text}\uff1b\u6a21\u578b\u52a0\u8f7d {self.model_load_ms:.0f} ms\uff0c"
            f"\u70ed\u8eab\u7f16\u7801 {self.warmup_ms:.0f} ms\u3002"
        )

    @property
    def benchmark_detail(self) -> str:
        return (
            f"\u6a21\u578b\u52a0\u8f7d {self.model_load_ms:.0f} ms\uff1b\u70ed\u8eab {self.warmup_ms:.0f} ms\uff1b"
            f"\u5355\u6761\u7f16\u7801 {self.single_encode_ms:.0f} ms\uff1b"
            f"{self.batch_size} \u6761\u6279\u91cf\u7f16\u7801 {self.batch_encode_ms:.0f} ms\uff1b"
            f"\u5e73\u5747\u6bcf\u6761 {self.batch_item_ms:.0f} ms\uff1b"
            f"\u541e\u5410 {self.throughput_items_per_second:.2f} \u6761/\u79d2\u3002"
        )


ModelFileLocator = Callable[[Path, tuple[str, ...]], list[Path]]
ModuleAvailabilityChecker = Callable[[str], bool]
TesseractLocator = Callable[[AppConfig], str | None]
TesseractLanguageDetector = Callable[[AppConfig, str | None], set[str] | None]

ModelRuntimeProfiler = Callable[[AppConfig], ModelRuntimeProfile]


@dataclass(slots=True)
class TesseractRuntimeDiagnostics:
    configured_cmd: str = ""
    binary_path: str | None = None
    tessdata_prefix: str = ""
    tessdata_prefix_exists: bool = False
    selected_tessdata_dir: str | None = None
    candidate_dirs: list[str] = field(default_factory=list)
    available_language_count: int = 0
    available_language_sample: list[str] = field(default_factory=list)
    requested_language_files: dict[str, str] = field(default_factory=dict)


def _append_unique_path(paths: list[Path], candidate: Path) -> None:
    normalized = candidate.expanduser()
    if normalized not in paths:
        paths.append(normalized)


def _expand_tessdata_candidate(candidate: Path) -> list[Path]:
    expanded = [candidate]
    if candidate.name.lower() != "tessdata":
        expanded.append(candidate / "tessdata")
    return expanded


def _resolve_tesseract_root(binary_path: str | None) -> tuple[Path | None, Path | None]:
    if not binary_path:
        return None, None

    exe_path = Path(binary_path).expanduser()
    bin_dir = exe_path.parent
    if bin_dir.name.lower() == "bin" and bin_dir.parent.name.lower() == "library":
        return exe_path, bin_dir.parent.parent
    if bin_dir.name.lower() == "bin":
        return exe_path, bin_dir.parent
    return exe_path, bin_dir


def _list_traineddata_files(directory: Path | None) -> list[Path]:
    if directory is None or not directory.exists() or not directory.is_dir():
        return []
    return sorted(directory.glob("*.traineddata"))


def _collect_tessdata_candidate_dirs(
    binary_path: str | None,
    tessdata_prefix: str,
) -> list[Path]:
    candidates: list[Path] = []
    raw_candidates: list[Path] = []
    if tessdata_prefix:
        raw_candidates.append(Path(tessdata_prefix))

    exe_path, root_dir = _resolve_tesseract_root(binary_path)
    if exe_path is not None:
        bin_dir = exe_path.parent
        raw_candidates.extend(
            [
                bin_dir / "tessdata",
                bin_dir.parent / "tessdata",
                bin_dir.parent / "share" / "tessdata",
            ]
        )
        if root_dir is not None:
            raw_candidates.extend(
                [
                    root_dir / "tessdata",
                    root_dir / "share" / "tessdata",
                    root_dir / "Library" / "share" / "tessdata",
                ]
            )

    for raw_candidate in raw_candidates:
        for candidate in _expand_tessdata_candidate(raw_candidate):
            _append_unique_path(candidates, candidate)
    return candidates


def _probe_tesseract_runtime(
    config: AppConfig,
    tesseract_binary: str | None,
) -> TesseractRuntimeDiagnostics:
    if tesseract_binary:
        apply_tesseract_runtime_environment(tesseract_binary)

    tessdata_prefix = (os.environ.get("TESSDATA_PREFIX", "") or "").strip()
    candidate_dirs = _collect_tessdata_candidate_dirs(tesseract_binary, tessdata_prefix)
    existing_dirs = [candidate for candidate in candidate_dirs if candidate.exists() and candidate.is_dir()]

    selected_dir = None
    for candidate in existing_dirs:
        if _list_traineddata_files(candidate):
            selected_dir = candidate
            break
    if selected_dir is None and existing_dirs:
        selected_dir = existing_dirs[0]

    available_files = _list_traineddata_files(selected_dir)
    requested_files: dict[str, str] = {}
    requested_languages = _split_requested_languages(config.ocr_languages)
    for language in requested_languages:
        for candidate in existing_dirs:
            traineddata_path = candidate / f"{language}.traineddata"
            if traineddata_path.exists():
                requested_files[language] = str(traineddata_path.resolve())
                break

    return TesseractRuntimeDiagnostics(
        configured_cmd=(config.tesseract_cmd or "").strip(),
        binary_path=tesseract_binary,
        tessdata_prefix=tessdata_prefix,
        tessdata_prefix_exists=bool(tessdata_prefix) and Path(tessdata_prefix).exists(),
        selected_tessdata_dir=(str(selected_dir.resolve()) if selected_dir is not None else None),
        candidate_dirs=[str(candidate.resolve()) if candidate.exists() else str(candidate) for candidate in candidate_dirs],
        available_language_count=len(available_files),
        available_language_sample=[path.name for path in available_files[:8]],
        requested_language_files=requested_files,
    )


def _build_tesseract_runtime_detail(
    diagnostics: TesseractRuntimeDiagnostics,
    requested_languages: list[str] | None = None,
) -> str:
    lines = [
        f"配置值 tesseract_cmd：{diagnostics.configured_cmd or '未设置'}",
        f"Tesseract 路径：{diagnostics.binary_path or '未检测到'}",
    ]

    if diagnostics.tessdata_prefix:
        prefix_state = "存在" if diagnostics.tessdata_prefix_exists else "不存在"
        lines.append(f"TESSDATA_PREFIX：{diagnostics.tessdata_prefix}（{prefix_state}）")
    else:
        lines.append("TESSDATA_PREFIX：未设置")

    if diagnostics.selected_tessdata_dir:
        lines.append(f"tessdata 目录：{diagnostics.selected_tessdata_dir}")
    else:
        lines.append("tessdata 目录：未定位")

    if diagnostics.candidate_dirs:
        lines.append("候选目录：" + " | ".join(diagnostics.candidate_dirs[:6]))

    if diagnostics.available_language_count:
        sample = ", ".join(diagnostics.available_language_sample)
        if diagnostics.available_language_count > len(diagnostics.available_language_sample):
            sample += f" 等 {diagnostics.available_language_count} 个"
        lines.append(f"已发现 traineddata：{sample}")
    elif diagnostics.selected_tessdata_dir:
        lines.append("已发现 traineddata：当前目录下未检测到任何 .traineddata 文件。")

    if requested_languages:
        for language in requested_languages:
            lines.append(
                f"{language}.traineddata：{diagnostics.requested_language_files.get(language, '未找到')}"
            )

    return "\n".join(lines)

_MODEL_PERFORMANCE_LEVEL_INFO = "info"
_MODEL_PERFORMANCE_LEVEL_OK = "ok"
_MODEL_PERFORMANCE_LEVEL_NEAR = "near"
_MODEL_PERFORMANCE_LEVEL_SLOW = "slow"

_MODEL_PERFORMANCE_LEVEL_LABEL = {
    _MODEL_PERFORMANCE_LEVEL_OK: "\u8fbe\u6807",
    _MODEL_PERFORMANCE_LEVEL_NEAR: "\u4e34\u754c",
    _MODEL_PERFORMANCE_LEVEL_SLOW: "\u504f\u6162",
    _MODEL_PERFORMANCE_LEVEL_INFO: "\u672a\u8bc4\u4f30",
}

_MODEL_PERFORMANCE_LEVEL_SEVERITY = {
    _MODEL_PERFORMANCE_LEVEL_INFO: 0,
    _MODEL_PERFORMANCE_LEVEL_OK: 1,
    _MODEL_PERFORMANCE_LEVEL_NEAR: 2,
    _MODEL_PERFORMANCE_LEVEL_SLOW: 3,
}


@dataclass(slots=True)
class ModelPerformanceMetric:
    key: str
    label: str
    value: float
    display_value: str
    level: str
    threshold: float | None = None


def _extract_float_metric(detail: str, pattern: str) -> float | None:
    match = re.search(pattern, detail)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _classify_latency_metric(value: float, threshold: float | None) -> str:
    if threshold is None or threshold <= 0:
        return _MODEL_PERFORMANCE_LEVEL_INFO
    if value > threshold:
        return _MODEL_PERFORMANCE_LEVEL_SLOW
    if value >= threshold * 0.8:
        return _MODEL_PERFORMANCE_LEVEL_NEAR
    return _MODEL_PERFORMANCE_LEVEL_OK


def _classify_throughput_metric(value: float, threshold: float | None) -> str:
    if threshold is None or threshold <= 0:
        return _MODEL_PERFORMANCE_LEVEL_INFO
    if value < threshold:
        return _MODEL_PERFORMANCE_LEVEL_SLOW
    if value <= threshold * 1.25:
        return _MODEL_PERFORMANCE_LEVEL_NEAR
    return _MODEL_PERFORMANCE_LEVEL_OK


def extract_model_performance_metrics(
    check: DeploymentCheck | None,
    config: AppConfig | None = None,
) -> list[ModelPerformanceMetric]:
    if check is None or check.key not in {"model_trial_load", "model_warmup_benchmark"}:
        return []

    detail = (check.detail or "").strip()
    if not detail:
        return []

    cfg = config or DEFAULT_CONFIG
    metrics: list[ModelPerformanceMetric] = []

    load_ms = _extract_float_metric(detail, r"\u6a21\u578b\u52a0\u8f7d ([0-9]+(?:\.[0-9]+)?) ms")
    if load_ms is not None:
        metrics.append(
            ModelPerformanceMetric(
                key="model_load_ms",
                label="\u6a21\u578b\u52a0\u8f7d",
                value=load_ms,
                display_value=f"{load_ms:.0f} ms",
                level=_classify_latency_metric(load_ms, float(getattr(cfg, "model_acceptable_load_ms", 0.0) or 0.0)),
                threshold=float(getattr(cfg, "model_acceptable_load_ms", 0.0) or 0.0),
            )
        )

    warmup_ms = _extract_float_metric(detail, r"\u70ed\u8eab(?:\u7f16\u7801)? ([0-9]+(?:\.[0-9]+)?) ms")
    if warmup_ms is not None:
        metrics.append(
            ModelPerformanceMetric(
                key="warmup_ms",
                label="\u70ed\u8eab",
                value=warmup_ms,
                display_value=f"{warmup_ms:.0f} ms",
                level=_classify_latency_metric(warmup_ms, float(getattr(cfg, "model_acceptable_warmup_ms", 0.0) or 0.0)),
                threshold=float(getattr(cfg, "model_acceptable_warmup_ms", 0.0) or 0.0),
            )
        )

    single_ms = _extract_float_metric(detail, r"\u5355\u6761\u7f16\u7801 ([0-9]+(?:\.[0-9]+)?) ms")
    if single_ms is not None:
        metrics.append(
            ModelPerformanceMetric(
                key="single_encode_ms",
                label="\u5355\u6761\u7f16\u7801",
                value=single_ms,
                display_value=f"{single_ms:.0f} ms",
                level=_classify_latency_metric(single_ms, float(getattr(cfg, "model_acceptable_single_encode_ms", 0.0) or 0.0)),
                threshold=float(getattr(cfg, "model_acceptable_single_encode_ms", 0.0) or 0.0),
            )
        )

    batch_match = re.search(r"([0-9]+) \u6761\u6279\u91cf\u7f16\u7801 ([0-9]+(?:\.[0-9]+)?) ms", detail)
    batch_size = int(getattr(cfg, "model_benchmark_batch_size", 0) or 0)
    batch_ms = None
    if batch_match is not None:
        batch_size = int(batch_match.group(1))
        batch_ms = float(batch_match.group(2))
        metrics.append(
            ModelPerformanceMetric(
                key="batch_encode_ms",
                label=f"{batch_size} \u6761\u6279\u91cf",
                value=batch_ms,
                display_value=f"{batch_ms:.0f} ms",
                level=_classify_latency_metric(batch_ms, float(getattr(cfg, "model_acceptable_batch_encode_ms", 0.0) or 0.0)),
                threshold=float(getattr(cfg, "model_acceptable_batch_encode_ms", 0.0) or 0.0),
            )
        )

    batch_item_ms = _extract_float_metric(detail, r"\u5e73\u5747\u6bcf\u6761 ([0-9]+(?:\.[0-9]+)?) ms")
    if batch_item_ms is not None:
        metrics.append(
            ModelPerformanceMetric(
                key="batch_item_ms",
                label="\u5e73\u5747\u6bcf\u6761",
                value=batch_item_ms,
                display_value=f"{batch_item_ms:.0f} ms",
                level=_classify_latency_metric(batch_item_ms, float(getattr(cfg, "model_acceptable_batch_item_ms", 0.0) or 0.0)),
                threshold=float(getattr(cfg, "model_acceptable_batch_item_ms", 0.0) or 0.0),
            )
        )

    throughput = _extract_float_metric(detail, r"\u541e\u5410 ([0-9]+(?:\.[0-9]+)?) \u6761/\u79d2")
    if throughput is not None:
        batch_threshold_ms = float(getattr(cfg, "model_acceptable_batch_encode_ms", 0.0) or 0.0)
        throughput_threshold = None
        if batch_threshold_ms > 0 and batch_size > 0:
            throughput_threshold = batch_size / (batch_threshold_ms / 1000.0)
        metrics.append(
            ModelPerformanceMetric(
                key="throughput_items_per_second",
                label="\u541e\u5410",
                value=throughput,
                display_value=f"{throughput:.2f} \u6761/\u79d2",
                level=_classify_throughput_metric(throughput, throughput_threshold),
                threshold=throughput_threshold,
            )
        )

    return metrics


def get_model_performance_level(metrics: list[ModelPerformanceMetric]) -> str:
    if not metrics:
        return _MODEL_PERFORMANCE_LEVEL_INFO
    return max(metrics, key=lambda item: _MODEL_PERFORMANCE_LEVEL_SEVERITY.get(item.level, 0)).level


def get_model_performance_level_text(level: str) -> str:
    return _MODEL_PERFORMANCE_LEVEL_LABEL.get(level, _MODEL_PERFORMANCE_LEVEL_LABEL[_MODEL_PERFORMANCE_LEVEL_INFO])


def build_model_performance_summary_text(
    metrics: list[ModelPerformanceMetric],
    limit: int = 4,
) -> str:
    if not metrics:
        return ""
    return " | ".join(
        f"{item.label} {item.display_value}" for item in metrics[: max(1, limit)]
    )


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _find_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(root.rglob(pattern))
    return matches


def _detect_tesseract_binary(config: AppConfig) -> str | None:
    configured = (config.tesseract_cmd or "").strip()
    if configured:
        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path.resolve())
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        return None

    return shutil.which("tesseract")


def _detect_tesseract_languages(
    config: AppConfig,
    tesseract_binary: str | None,
) -> set[str] | None:
    if tesseract_binary is None:
        return None

    import pytesseract

    apply_tesseract_runtime_environment(tesseract_binary)
    pytesseract.pytesseract.tesseract_cmd = tesseract_binary
    return set(pytesseract.get_languages(config=""))




def _build_model_benchmark_samples(config: AppConfig) -> list[str]:
    samples = [
        item.strip()
        for item in getattr(config, "model_benchmark_samples", [])
        if isinstance(item, str) and item.strip()
    ]
    if samples:
        return samples
    return ["\u90e8\u7f72\u81ea\u68c0"]



def _profile_sentence_transformer_runtime(config: AppConfig) -> ModelRuntimeProfile:
    from core.algorithms import initialize_runtime_environment

    initialize_runtime_environment(config)

    from sentence_transformers import SentenceTransformer

    samples = _build_model_benchmark_samples(config)
    batch_size = max(1, int(getattr(config, "model_benchmark_batch_size", 4) or 1))
    batch_samples = list(samples[:batch_size])
    while len(batch_samples) < batch_size:
        batch_samples.append(samples[len(batch_samples) % len(samples)])

    load_started = perf_counter()
    model = SentenceTransformer(
        config.resolved_model_dir,
        device="cpu",
        local_files_only=config.local_files_only,
    )
    model_load_ms = (perf_counter() - load_started) * 1000.0

    warmup_started = perf_counter()
    warmup_embeddings = model.encode(
        ["\u90e8\u7f72\u81ea\u68c0"],
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    warmup_ms = (perf_counter() - warmup_started) * 1000.0

    single_started = perf_counter()
    model.encode(
        [samples[0]],
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    single_encode_ms = (perf_counter() - single_started) * 1000.0

    batch_started = perf_counter()
    model.encode(
        batch_samples,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    batch_encode_ms = (perf_counter() - batch_started) * 1000.0

    shape = getattr(warmup_embeddings, "shape", None)
    embedding_dim = int(shape[1]) if shape is not None and len(shape) >= 2 else None
    batch_item_ms = batch_encode_ms / len(batch_samples) if batch_samples else batch_encode_ms
    throughput_items_per_second = (
        len(batch_samples) / (batch_encode_ms / 1000.0)
        if batch_samples and batch_encode_ms > 0
        else 0.0
    )

    return ModelRuntimeProfile(
        embedding_dim=embedding_dim,
        model_load_ms=model_load_ms,
        warmup_ms=warmup_ms,
        single_encode_ms=single_encode_ms,
        batch_encode_ms=batch_encode_ms,
        batch_size=len(batch_samples),
        batch_item_ms=batch_item_ms,
        throughput_items_per_second=throughput_items_per_second,
    )
def _split_requested_languages(language_spec: str) -> list[str]:
    normalized = language_spec.replace(",", "+").replace(" ", "+")
    return [token.strip() for token in normalized.split("+") if token.strip()]


def check_config_bundle() -> DeploymentCheck:
    config_path = Path(get_resource_path(DEFAULT_CONFIG_RELATIVE_PATH))
    if config_path.exists():
        return DeploymentCheck(
            key="config_bundle",
            title="配置文件",
            status=_CHECK_OK,
            summary="默认配置文件可用。",
            detail="启动时可从 config/default_config.json 加载部署参数。",
            location=str(config_path),
            required=True,
        )

    return DeploymentCheck(
        key="config_bundle",
        title="配置文件",
        status=_CHECK_WARNING,
        summary="未找到默认配置文件，程序将回退到内置默认配置。",
        detail="这不会阻止程序启动，但不利于后续部署调参。",
        location=str(config_path),
        hint="建议补齐 config/default_config.json，便于调整模型路径、OCR 参数和停用词。",
        required=False,
    )


def check_model_directory(
    config: AppConfig | None = None,
    file_locator: ModelFileLocator = _find_files,
) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    model_path = Path(cfg.resolved_model_dir)
    if not model_path.exists():
        return DeploymentCheck(
            key="model_directory",
            title="离线模型目录",
            status=_CHECK_ERROR,
            summary="模型目录不存在。",
            detail="句向量与双篇措辞比对依赖本地 SentenceTransformer 模型。",
            location=str(model_path),
            hint="请将离线模型放入配置中的 model_dir 路径，再重新启动程序。",
            required=True,
        )

    if not model_path.is_dir():
        return DeploymentCheck(
            key="model_directory",
            title="离线模型目录",
            status=_CHECK_ERROR,
            summary="model_dir 指向的不是文件夹。",
            location=str(model_path),
            hint="请检查 config/default_config.json 中的 model_dir 设置。",
            required=True,
        )

    weight_files = file_locator(
        model_path,
        (
            "*.safetensors",
            "model.safetensors.index.json",
            "pytorch_model.bin",
        ),
    )
    tokenizer_files = file_locator(
        model_path,
        (
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
            "spiece.model",
        ),
    )
    sentence_transformer_files = file_locator(
        model_path,
        (
            "modules.json",
            "config_sentence_transformers.json",
            "sentence_bert_config.json",
        ),
    )

    found_fragments = [
        path.relative_to(model_path).as_posix()
        for path in (
            sentence_transformer_files[:2]
            + weight_files[:2]
            + tokenizer_files[:2]
        )
    ]
    detail = "\n".join(found_fragments) if found_fragments else "未探测到关键模型文件。"

    if not weight_files:
        return DeploymentCheck(
            key="model_directory",
            title="离线模型目录",
            status=_CHECK_ERROR,
            summary="模型目录存在，但缺少权重文件。",
            detail=detail,
            location=str(model_path),
            hint="至少应包含 .safetensors 或 pytorch_model.bin 等权重文件。",
            required=True,
        )

    if not tokenizer_files or not sentence_transformer_files:
        return DeploymentCheck(
            key="model_directory",
            title="离线模型目录",
            status=_CHECK_WARNING,
            summary="模型目录不完整，可能缺少 tokenizer 或 SentenceTransformer 配置。",
            detail=detail,
            location=str(model_path),
            hint="建议补齐 modules.json、tokenizer.json 等文件，避免本地加载失败。",
            required=True,
        )

    return DeploymentCheck(
        key="model_directory",
        title="离线模型目录",
        status=_CHECK_OK,
        summary="模型目录完整，可用于本地推理。",
        detail=detail,
        location=str(model_path),
        required=True,
    )




def _summarize_model_performance_thresholds(
    profile: ModelRuntimeProfile,
    config: AppConfig,
) -> list[str]:
    comparisons = [
        ("\u6a21\u578b\u52a0\u8f7d", profile.model_load_ms, float(getattr(config, "model_acceptable_load_ms", 8000.0))),
        ("\u70ed\u8eab\u7f16\u7801", profile.warmup_ms, float(getattr(config, "model_acceptable_warmup_ms", 2500.0))),
        ("\u5355\u6761\u7f16\u7801", profile.single_encode_ms, float(getattr(config, "model_acceptable_single_encode_ms", 700.0))),
        ("\u6279\u91cf\u7f16\u7801", profile.batch_encode_ms, float(getattr(config, "model_acceptable_batch_encode_ms", 2200.0))),
        ("\u5e73\u5747\u6bcf\u6761", profile.batch_item_ms, float(getattr(config, "model_acceptable_batch_item_ms", 550.0))),
    ]
    exceeded: list[str] = []
    for label, actual_ms, threshold_ms in comparisons:
        if actual_ms > threshold_ms:
            exceeded.append(f"{label} {actual_ms:.0f} ms\uff08\u9608\u503c {threshold_ms:.0f} ms\uff09")
    return exceeded



def check_model_trial_load(
    config: AppConfig | None = None,
    availability_checker: ModuleAvailabilityChecker = _module_available,
    model_profiler: ModelRuntimeProfiler = _profile_sentence_transformer_runtime,
    directory_check: DeploymentCheck | None = None,
    runtime_profile: ModelRuntimeProfile | None = None,
    profile_error: Exception | None = None,
) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    if not getattr(cfg, "enable_model_trial_load_check", True):
        return DeploymentCheck(
            key="model_trial_load",
            title="\u6a21\u578b\u8bd5\u52a0\u8f7d",
            status=_CHECK_OK,
            summary="\u6a21\u578b\u8bd5\u52a0\u8f7d\u81ea\u68c0\u5df2\u5728\u914d\u7f6e\u4e2d\u5173\u95ed\u3002",
            hint="\u5982\u9700\u542f\u52a8\u524d\u9a8c\u8bc1\u771f\u5b9e\u6a21\u578b\u53ef\u7528\u6027\uff0c\u53ef\u91cd\u65b0\u542f\u7528\u8be5\u68c0\u67e5\u3002",
            required=False,
        )

    if not availability_checker("sentence_transformers") or not availability_checker("torch"):
        return DeploymentCheck(
            key="model_trial_load",
            title="\u6a21\u578b\u8bd5\u52a0\u8f7d",
            status=_CHECK_WARNING,
            summary="\u7f3a\u5c11\u8bd5\u52a0\u8f7d\u6240\u9700\u4f9d\u8d56\uff0c\u5df2\u8df3\u8fc7\u771f\u5b9e\u6a21\u578b\u9a8c\u8bc1\u3002",
            hint="\u8bf7\u5148\u8865\u9f50 sentence-transformers \u548c torch\uff0c\u518d\u6267\u884c\u90e8\u7f72\u81ea\u68c0\u3002",
            required=False,
        )

    model_directory_check = directory_check or check_model_directory(cfg)
    if model_directory_check.status == _CHECK_ERROR:
        return DeploymentCheck(
            key="model_trial_load",
            title="\u6a21\u578b\u8bd5\u52a0\u8f7d",
            status=_CHECK_WARNING,
            summary="\u57fa\u7840\u6a21\u578b\u76ee\u5f55\u68c0\u67e5\u672a\u901a\u8fc7\uff0c\u5df2\u8df3\u8fc7\u771f\u5b9e\u6a21\u578b\u9a8c\u8bc1\u3002",
            detail=model_directory_check.summary,
            location=model_directory_check.location,
            hint="\u8bf7\u5148\u4fee\u590d\u6a21\u578b\u76ee\u5f55\u95ee\u9898\uff0c\u518d\u91cd\u65b0\u6267\u884c\u90e8\u7f72\u81ea\u68c0\u3002",
            required=False,
        )

    if profile_error is not None:
        return DeploymentCheck(
            key="model_trial_load",
            title="\u6a21\u578b\u8bd5\u52a0\u8f7d",
            status=_CHECK_ERROR,
            summary="\u6a21\u578b\u76ee\u5f55\u5b58\u5728\uff0c\u4f46\u771f\u5b9e\u8bd5\u52a0\u8f7d\u5931\u8d25\u3002",
            detail=str(profile_error),
            location=str(Path(cfg.resolved_model_dir)),
            hint="\u8bf7\u91cd\u70b9\u68c0\u67e5\u6a21\u578b\u76ee\u5f55\u5b8c\u6574\u6027\u3001transformers \u7248\u672c\u517c\u5bb9\u6027\u548c\u672c\u5730\u6743\u91cd\u683c\u5f0f\u3002",
            required=True,
        )

    profile = runtime_profile
    if profile is None:
        try:
            profile = model_profiler(cfg)
        except Exception as exc:
            return DeploymentCheck(
                key="model_trial_load",
                title="\u6a21\u578b\u8bd5\u52a0\u8f7d",
                status=_CHECK_ERROR,
                summary="\u6a21\u578b\u76ee\u5f55\u5b58\u5728\uff0c\u4f46\u771f\u5b9e\u8bd5\u52a0\u8f7d\u5931\u8d25\u3002",
                detail=str(exc),
                location=str(Path(cfg.resolved_model_dir)),
                hint="\u8bf7\u91cd\u70b9\u68c0\u67e5\u6a21\u578b\u76ee\u5f55\u5b8c\u6574\u6027\u3001transformers \u7248\u672c\u517c\u5bb9\u6027\u548c\u672c\u5730\u6743\u91cd\u683c\u5f0f\u3002",
                required=True,
            )

    return DeploymentCheck(
        key="model_trial_load",
        title="\u6a21\u578b\u8bd5\u52a0\u8f7d",
        status=_CHECK_OK,
        summary="\u6a21\u578b\u8bd5\u52a0\u8f7d\u6210\u529f\u3002",
        detail=profile.trial_detail,
        location=str(Path(cfg.resolved_model_dir)),
        required=True,
    )



def check_model_warmup_benchmark(
    config: AppConfig | None = None,
    availability_checker: ModuleAvailabilityChecker = _module_available,
    model_profiler: ModelRuntimeProfiler = _profile_sentence_transformer_runtime,
    directory_check: DeploymentCheck | None = None,
    runtime_profile: ModelRuntimeProfile | None = None,
    profile_error: Exception | None = None,
    trial_load_check: DeploymentCheck | None = None,
) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    if not getattr(cfg, "enable_model_warmup_benchmark_check", True):
        return DeploymentCheck(
            key="model_warmup_benchmark",
            title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
            status=_CHECK_OK,
            summary="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6\u81ea\u68c0\u5df2\u5728\u914d\u7f6e\u4e2d\u5173\u95ed\u3002",
            hint="\u5982\u9700\u5728\u542f\u52a8\u524d\u786e\u8ba4\u6a21\u578b\u54cd\u5e94\u901f\u5ea6\uff0c\u53ef\u91cd\u65b0\u542f\u7528\u8be5\u68c0\u67e5\u3002",
            required=False,
        )

    if not availability_checker("sentence_transformers") or not availability_checker("torch"):
        return DeploymentCheck(
            key="model_warmup_benchmark",
            title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
            status=_CHECK_WARNING,
            summary="\u7f3a\u5c11\u6027\u80fd\u57fa\u51c6\u6240\u9700\u4f9d\u8d56\uff0c\u5df2\u8df3\u8fc7\u6a21\u578b\u70ed\u8eab\u6d4b\u8bd5\u3002",
            hint="\u8bf7\u5148\u8865\u9f50 sentence-transformers \u548c torch\uff0c\u518d\u6267\u884c\u90e8\u7f72\u81ea\u68c0\u3002",
            required=False,
        )

    model_directory_check = directory_check or check_model_directory(cfg)
    if model_directory_check.status == _CHECK_ERROR:
        return DeploymentCheck(
            key="model_warmup_benchmark",
            title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
            status=_CHECK_WARNING,
            summary="\u57fa\u7840\u6a21\u578b\u76ee\u5f55\u68c0\u67e5\u672a\u901a\u8fc7\uff0c\u5df2\u8df3\u8fc7\u6a21\u578b\u70ed\u8eab\u4e0e\u57fa\u51c6\u6d4b\u8bd5\u3002",
            detail=model_directory_check.summary,
            location=model_directory_check.location,
            hint="\u8bf7\u5148\u4fee\u590d\u6a21\u578b\u76ee\u5f55\u95ee\u9898\uff0c\u518d\u91cd\u65b0\u6267\u884c\u90e8\u7f72\u81ea\u68c0\u3002",
            required=False,
        )

    if trial_load_check is not None and trial_load_check.status == _CHECK_ERROR:
        return DeploymentCheck(
            key="model_warmup_benchmark",
            title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
            status=_CHECK_WARNING,
            summary="\u6a21\u578b\u8bd5\u52a0\u8f7d\u672a\u901a\u8fc7\uff0c\u5df2\u8df3\u8fc7\u6a21\u578b\u70ed\u8eab\u4e0e\u57fa\u51c6\u6d4b\u8bd5\u3002",
            detail=trial_load_check.summary,
            location=str(Path(cfg.resolved_model_dir)),
            hint="\u8bf7\u5148\u4fee\u590d\u6a21\u578b\u8bd5\u52a0\u8f7d\u5931\u8d25\u95ee\u9898\uff0c\u518d\u91cd\u65b0\u6267\u884c\u6027\u80fd\u57fa\u51c6\u3002",
            required=False,
        )

    if profile_error is not None:
        return DeploymentCheck(
            key="model_warmup_benchmark",
            title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
            status=_CHECK_WARNING,
            summary="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6\u6267\u884c\u5931\u8d25\u3002",
            detail=str(profile_error),
            location=str(Path(cfg.resolved_model_dir)),
            hint="\u53ef\u5148\u786e\u8ba4\u6a21\u578b\u53ef\u6b63\u5e38\u5206\u6790\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u4fdd\u7559\u542f\u52a8\u524d\u6027\u80fd\u57fa\u51c6\u3002",
            required=False,
        )

    profile = runtime_profile
    if profile is None:
        try:
            profile = model_profiler(cfg)
        except Exception as exc:
            return DeploymentCheck(
                key="model_warmup_benchmark",
                title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
                status=_CHECK_WARNING,
                summary="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6\u6267\u884c\u5931\u8d25\u3002",
                detail=str(exc),
                location=str(Path(cfg.resolved_model_dir)),
                hint="\u53ef\u5148\u786e\u8ba4\u6a21\u578b\u53ef\u6b63\u5e38\u5206\u6790\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u4fdd\u7559\u542f\u52a8\u524d\u6027\u80fd\u57fa\u51c6\u3002",
                required=False,
            )

    exceeded = _summarize_model_performance_thresholds(profile, cfg)
    if exceeded:
        detail = profile.benchmark_detail + " \u8d85\u9650\u9879\uff1a" + "\uff1b".join(exceeded) + "\u3002"
        return DeploymentCheck(
            key="model_warmup_benchmark",
            title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
            status=_CHECK_WARNING,
            summary="\u6a21\u578b\u53ef\u52a0\u8f7d\uff0c\u4f46\u70ed\u8eab\u6216\u7f16\u7801\u6027\u80fd\u4e0d\u5728\u53ef\u63a5\u53d7\u8303\u56f4\u5185\u3002",
            detail=detail,
            location=str(Path(cfg.resolved_model_dir)),
            hint="\u5efa\u8bae\u4f18\u5148\u68c0\u67e5 CPU \u5360\u7528\u3001\u6a21\u578b\u4f53\u79ef\u548c\u5b89\u5168\u8f6f\u4ef6\u626b\u63cf\uff0c\u5fc5\u8981\u65f6\u653e\u5bbd\u914d\u7f6e\u9608\u503c\u3002",
            required=False,
        )

    return DeploymentCheck(
        key="model_warmup_benchmark",
        title="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6",
        status=_CHECK_OK,
        summary="\u6a21\u578b\u70ed\u8eab\u4e0e\u6027\u80fd\u57fa\u51c6\u901a\u8fc7\u3002",
        detail=profile.benchmark_detail,
        location=str(Path(cfg.resolved_model_dir)),
        hint="\u5f53\u524d\u6a21\u578b\u53ef\u52a0\u8f7d\uff0c\u4e14\u542f\u52a8\u540e\u7684\u54cd\u5e94\u901f\u5ea6\u5904\u4e8e\u53ef\u63a5\u53d7\u8303\u56f4\u5185\u3002",
        required=False,
    )
def check_font_resource(config: AppConfig | None = None) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    font_path = Path(cfg.resolved_font_path)
    if font_path.exists():
        return DeploymentCheck(
            key="font_resource",
            title="应用字体",
            status=_CHECK_OK,
            summary="字体资源已就绪。",
            location=str(font_path),
            required=False,
        )

    return DeploymentCheck(
        key="font_resource",
        title="应用字体",
        status=_CHECK_WARNING,
        summary="未找到 simhei.ttf，程序将回退到系统默认字体。",
        location=str(font_path),
        hint="这不影响分析功能，但中文排版和打印效果可能不稳定。",
        required=False,
    )


def check_custom_dictionary(config: AppConfig | None = None) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    dict_path = Path(cfg.resolved_custom_dictionary_path)
    if dict_path.exists():
        return DeploymentCheck(
            key="custom_dictionary",
            title="自定义词典",
            status=_CHECK_OK,
            summary="自定义词典已就绪。",
            location=str(dict_path),
            required=False,
        )

    return DeploymentCheck(
        key="custom_dictionary",
        title="自定义词典",
        status=_CHECK_WARNING,
        summary="未找到自定义词典，将仅使用默认分词。",
        location=str(dict_path),
        hint="建议补齐关键政策术语，提升新提法与议题识别精度。",
        required=False,
    )


def check_core_dependencies(
    availability_checker: ModuleAvailabilityChecker = _module_available,
) -> DeploymentCheck:
    required_modules = {
        "jieba": "分词与关键词提取",
        "sentence_transformers": "句向量编码",
        "torch": "本地推理运行时",
        "transformers": "Transformer 模型加载",
    }
    missing = [
        label for module, label in required_modules.items() if not availability_checker(module)
    ]
    if missing:
        return DeploymentCheck(
            key="core_dependencies",
            title="核心分析依赖",
            status=_CHECK_ERROR,
            summary=f"缺少核心依赖：{'、'.join(missing)}。",
            detail="缺失这些依赖时，单篇或双篇分析将无法正常执行。",
            hint="请根据 requirements.txt 补齐 Python 依赖。",
            required=True,
        )

    return DeploymentCheck(
        key="core_dependencies",
        title="核心分析依赖",
        status=_CHECK_OK,
        summary="核心分析依赖已安装。",
        required=True,
    )


def check_document_dependencies(
    availability_checker: ModuleAvailabilityChecker = _module_available,
) -> DeploymentCheck:
    optional_modules = {
        "docx": "DOCX 导入",
        "pypdf": "PDF 文字层导入",
    }
    missing = [
        label for module, label in optional_modules.items() if not availability_checker(module)
    ]
    if missing:
        return DeploymentCheck(
            key="document_dependencies",
            title="文档导入依赖",
            status=_CHECK_WARNING,
            summary=f"部分导入能力未就绪：{'、'.join(missing)}。",
            hint="如需完整支持 DOCX / PDF 导入，请补齐对应依赖。",
            required=False,
        )

    return DeploymentCheck(
        key="document_dependencies",
        title="文档导入依赖",
        status=_CHECK_OK,
        summary="TXT / DOCX / PDF 导入依赖已安装。",
        required=False,
    )


def check_ocr_pipeline(
    config: AppConfig | None = None,
    availability_checker: ModuleAvailabilityChecker = _module_available,
    tesseract_locator: TesseractLocator = _detect_tesseract_binary,
) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    if not cfg.enable_pdf_ocr:
        return DeploymentCheck(
            key="ocr_pipeline",
            title="扫描版 PDF OCR",
            status=_CHECK_OK,
            summary="OCR 已在配置中关闭。",
            hint="如需支持扫描版 PDF，可在配置中启用 enable_pdf_ocr。",
            required=False,
        )

    missing_modules = [
        label
        for module, label in {
            "fitz": "PyMuPDF",
            "PIL": "Pillow",
            "pytesseract": "pytesseract",
        }.items()
        if not availability_checker(module)
    ]
    tesseract_binary = tesseract_locator(cfg)
    diagnostics = _probe_tesseract_runtime(cfg, tesseract_binary)

    if missing_modules or not tesseract_binary:
        details: list[str] = []
        if missing_modules:
            details.append(f"缺少 OCR Python 依赖：{'、'.join(missing_modules)}。")
        if not tesseract_binary:
            details.append("未检测到 Tesseract-OCR 可执行程序。")
        details.append(_build_tesseract_runtime_detail(diagnostics))

        return DeploymentCheck(
            key="ocr_pipeline",
            title="扫描版 PDF OCR",
            status=_CHECK_WARNING,
            summary="OCR 未完全就绪，扫描版 PDF 可能无法导入。",
            detail="\n".join(details),
            location=cfg.tesseract_cmd or "tesseract",
            hint="请安装 Tesseract-OCR，并根据需要在配置中设置 tesseract_cmd、检查 TESSDATA_PREFIX 与 tessdata 目录。",
            required=False,
        )

    detail = _build_tesseract_runtime_detail(diagnostics)
    if diagnostics.selected_tessdata_dir is None or diagnostics.available_language_count == 0:
        return DeploymentCheck(
            key="ocr_pipeline",
            title="扫描版 PDF OCR",
            status=_CHECK_WARNING,
            summary="Tesseract 可执行程序已检测到，但未定位到可用的 tessdata 目录。",
            detail=detail,
            location=tesseract_binary,
            hint="请检查 share/tessdata 目录是否存在，以及 TESSDATA_PREFIX 是否指向正确路径。",
            required=False,
        )

    return DeploymentCheck(
        key="ocr_pipeline",
        title="扫描版 PDF OCR",
        status=_CHECK_OK,
        summary="OCR 管线已就绪，可处理扫描版 PDF。",
        detail=detail,
        location=tesseract_binary,
        required=False,
    )


def check_ocr_languages(
    config: AppConfig | None = None,
    availability_checker: ModuleAvailabilityChecker = _module_available,
    tesseract_locator: TesseractLocator = _detect_tesseract_binary,
    language_detector: TesseractLanguageDetector = _detect_tesseract_languages,
) -> DeploymentCheck:
    cfg = config or DEFAULT_CONFIG
    requested_languages = _split_requested_languages(cfg.ocr_languages)
    if not cfg.enable_pdf_ocr:
        return DeploymentCheck(
            key="ocr_languages",
            title="OCR 语言包",
            status=_CHECK_OK,
            summary="OCR 已关闭，无需检测语言包。",
            required=False,
        )

    tesseract_binary = tesseract_locator(cfg)
    diagnostics = _probe_tesseract_runtime(cfg, tesseract_binary)

    if not availability_checker("pytesseract"):
        return DeploymentCheck(
            key="ocr_languages",
            title="OCR 语言包",
            status=_CHECK_WARNING,
            summary="未安装 pytesseract，无法检测语言包。",
            detail=_build_tesseract_runtime_detail(diagnostics, requested_languages),
            hint="安装 pytesseract 后，可再次运行部署自检。",
            required=False,
        )

    if not tesseract_binary:
        return DeploymentCheck(
            key="ocr_languages",
            title="OCR 语言包",
            status=_CHECK_WARNING,
            summary="未检测到 Tesseract，可用语言包无法探测。",
            detail=_build_tesseract_runtime_detail(diagnostics, requested_languages),
            hint="请先安装或配置 Tesseract-OCR。",
            required=False,
        )

    try:
        available_languages = language_detector(cfg, tesseract_binary) or set()
    except Exception as exc:
        detail = _build_tesseract_runtime_detail(diagnostics, requested_languages)
        detail = detail + "\n" + f"语言探测异常：{exc}"
        return DeploymentCheck(
            key="ocr_languages",
            title="OCR 语言包",
            status=_CHECK_WARNING,
            summary="语言包探测失败。",
            detail=detail,
            location=tesseract_binary,
            hint="请确认 Tesseract 安装完整，并且 tessdata 目录可访问。",
            required=False,
        )

    missing_languages = [
        language for language in requested_languages if language not in available_languages
    ]
    detail_lines = [
        _build_tesseract_runtime_detail(diagnostics, requested_languages),
        (
            f"pytesseract.get_languages：{', '.join(sorted(available_languages))}"
            if available_languages
            else "pytesseract.get_languages：未探测到任何语言包。"
        ),
    ]
    detail = "\n".join(item for item in detail_lines if item)

    if missing_languages:
        return DeploymentCheck(
            key="ocr_languages",
            title="OCR 语言包",
            status=_CHECK_WARNING,
            summary=f"缺少配置所需语言包：{'、'.join(missing_languages)}。",
            detail=detail,
            location=tesseract_binary,
            hint="请安装对应语言包，或修改 ocr_languages 与当前环境保持一致。",
            required=False,
        )

    return DeploymentCheck(
        key="ocr_languages",
        title="OCR 语言包",
        status=_CHECK_OK,
        summary="OCR 语言包满足当前配置。",
        detail=detail,
        location=tesseract_binary,
        required=False,
    )


def run_startup_checks(config: AppConfig | None = None) -> StartupCheckReport:
    cfg = config or DEFAULT_CONFIG
    model_directory_check = check_model_directory(cfg)

    runtime_profile: ModelRuntimeProfile | None = None
    profile_error: Exception | None = None
    should_profile_model = (
        getattr(cfg, "enable_model_trial_load_check", True)
        or getattr(cfg, "enable_model_warmup_benchmark_check", True)
    )
    if (
        should_profile_model
        and model_directory_check.status != _CHECK_ERROR
        and _module_available("sentence_transformers")
        and _module_available("torch")
    ):
        try:
            runtime_profile = _profile_sentence_transformer_runtime(cfg)
        except Exception as exc:
            profile_error = exc

    model_trial_check = check_model_trial_load(
        cfg,
        directory_check=model_directory_check,
        runtime_profile=runtime_profile,
        profile_error=profile_error,
    )
    model_benchmark_check = check_model_warmup_benchmark(
        cfg,
        directory_check=model_directory_check,
        runtime_profile=runtime_profile,
        profile_error=profile_error,
        trial_load_check=model_trial_check,
    )

    results = [
        check_config_bundle(),
        check_core_dependencies(),
        model_directory_check,
        model_trial_check,
        model_benchmark_check,
        check_document_dependencies(),
        check_ocr_pipeline(cfg),
        check_ocr_languages(cfg),
        check_font_resource(cfg),
        check_custom_dictionary(cfg),
    ]
    return StartupCheckReport(
        results=results,
        checked_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
def compare_startup_reports(
    previous: StartupCheckReport | None,
    current: StartupCheckReport,
) -> list[DeploymentCheckTransition]:
    if previous is None:
        return []

    previous_map = previous.by_key()
    current_map = current.by_key()

    ordered_keys = [item.key for item in current.results]
    for key in previous_map:
        if key not in current_map:
            ordered_keys.append(key)

    transitions: list[DeploymentCheckTransition] = []
    for key in ordered_keys:
        before = previous_map.get(key)
        after = current_map.get(key)
        transition = DeploymentCheckTransition(
            key=key,
            title=(after.title if after is not None else before.title),
            previous_status=(before.status if before is not None else None),
            current_status=(after.status if after is not None else None),
            previous_summary=(before.summary if before is not None else ""),
            current_summary=(after.summary if after is not None else ""),
        )
        if transition.changed:
            transitions.append(transition)
    return transitions


def summarize_transitions(transitions: list[DeploymentCheckTransition]) -> str:
    if not transitions:
        return "本次重检未发现状态变化。"

    improved = sum(item.direction == "improved" for item in transitions)
    regressed = sum(item.direction == "regressed" for item in transitions)
    updated = sum(item.direction == "updated" for item in transitions)
    parts: list[str] = []
    if improved:
        parts.append(f"改善 {improved} 项")
    if regressed:
        parts.append(f"退化 {regressed} 项")
    if updated:
        parts.append(f"信息更新 {updated} 项")
    return "本次重检变化：" + "，".join(parts) + "。"



_DIAGNOSTIC_STATUS_TEXT = {
    _CHECK_OK: "通过",
    _CHECK_WARNING: "警告",
    _CHECK_ERROR: "错误",
}


def _build_diagnostic_status_badge_html(status: str) -> str:
    style_map = {
        _CHECK_OK: {"background": "#ecfdf3", "foreground": "#027a48", "border": "#abefc6"},
        _CHECK_WARNING: {"background": "#fffaeb", "foreground": "#b54708", "border": "#fedf89"},
        _CHECK_ERROR: {"background": "#fef3f2", "foreground": "#b42318", "border": "#fecdca"},
    }
    style = style_map.get(
        status,
        {"background": "#f2f4f7", "foreground": "#344054", "border": "#d0d5dd"},
    )
    label = _DIAGNOSTIC_STATUS_TEXT.get(status, status)
    return (
        "<span class='status-badge' "
        f"style='background: {style['background']}; color: {style['foreground']}; border-color: {style['border']};'>"
        f"{escape(label)}"
        "</span>"
    )


def _build_diagnostic_metric_cards_html(report: StartupCheckReport) -> str:
    cards = [
        ("总体状态", report.overall_label),
        ("通过", str(report.ok_count)),
        ("警告", str(report.warning_count)),
        ("错误", str(report.error_count)),
    ]
    return "".join(
        (
            "<div class='metric-card'>"
            f"<div class='metric-label'>{escape(label)}</div>"
            f"<div class='metric-value'>{escape(value)}</div>"
            "</div>"
        )
        for label, value in cards
    )


def _build_diagnostic_performance_html(check: DeploymentCheck, config: AppConfig) -> str:
    metrics = extract_model_performance_metrics(check, config)
    if not metrics:
        return ""

    level_style_map = {
        _MODEL_PERFORMANCE_LEVEL_OK: {"background": "#ecfdf3", "foreground": "#027a48", "border": "#abefc6"},
        _MODEL_PERFORMANCE_LEVEL_NEAR: {"background": "#fffaeb", "foreground": "#b54708", "border": "#fedf89"},
        _MODEL_PERFORMANCE_LEVEL_SLOW: {"background": "#fef3f2", "foreground": "#b42318", "border": "#fecdca"},
        _MODEL_PERFORMANCE_LEVEL_INFO: {"background": "#f2f4f7", "foreground": "#344054", "border": "#d0d5dd"},
    }
    overall_level = get_model_performance_level(metrics)
    overall_style = level_style_map.get(overall_level, level_style_map[_MODEL_PERFORMANCE_LEVEL_INFO])

    cards: list[str] = []
    for metric in metrics:
        metric_style = level_style_map.get(metric.level, level_style_map[_MODEL_PERFORMANCE_LEVEL_INFO])
        if metric.threshold:
            if metric.key == "throughput_items_per_second":
                threshold_text = f"参考阈值：{metric.threshold:.2f} 条/秒"
            else:
                threshold_text = f"阈值：{metric.threshold:.0f} ms"
        else:
            threshold_text = ""
        cards.append(
            "<div class='perf-card' "
            f"style='border-color: {metric_style['border']}; background: {metric_style['background']};'>"
            f"<div class='perf-label' style='color: {metric_style['foreground']};'>{escape(metric.label)} | {escape(get_model_performance_level_text(metric.level))}</div>"
            f"<div class='perf-value'>{escape(metric.display_value)}</div>"
            f"<div class='perf-threshold'>{escape(threshold_text)}</div>"
            "</div>"
        )

    summary_text = build_model_performance_summary_text(metrics, limit=5)
    return (
        "<section class='perf-panel'>"
        "<div class='section-title-row'>"
        f"<span class='status-badge' style='background: {overall_style['background']}; color: {overall_style['foreground']}; border-color: {overall_style['border']};'>性能等级：{escape(get_model_performance_level_text(overall_level))}</span>"
        f"<span class='perf-summary'>{escape(summary_text)}</span>"
        "</div>"
        f"<div class='perf-grid'>{''.join(cards)}</div>"
        "</section>"
    )


def _build_diagnostic_detail_block_html(label: str, value: str) -> str:
    escaped_value = escape(value).replace(chr(10), '<br>')
    return (
        "<div class='detail-block'>"
        f"<div class='detail-label'>{escape(label)}</div>"
        f"<div class='detail-value'>{escaped_value}</div>"
        "</div>"
    )


def _build_diagnostic_check_html(
    check: DeploymentCheck,
    config: AppConfig,
    transition: DeploymentCheckTransition | None = None,
) -> str:
    parts = [
        "<article class='check-card'>",
        "<div class='check-header'>",
        f"<div><h3>{escape(check.title)}</h3><p class='check-summary'>{escape(check.summary)}</p></div>",
        _build_diagnostic_status_badge_html(check.status),
        "</div>",
    ]

    performance_html = _build_diagnostic_performance_html(check, config)
    if performance_html:
        parts.append(performance_html)

    if transition is not None:
        previous_summary = transition.previous_summary or '无'
        current_summary = transition.current_summary or '无'
        parts.append(
            "<div class='transition-box'>"
            "<div class='detail-label'>修复前后差异</div>"
            f"<div class='detail-value'>{escape(transition.label)}<br>之前：{escape(previous_summary)}<br>现在：{escape(current_summary)}</div>"
            "</div>"
        )

    if check.location:
        parts.append(_build_diagnostic_detail_block_html('位置', check.location))
    if check.detail:
        parts.append(_build_diagnostic_detail_block_html('详情', check.detail))
    if check.hint:
        parts.append(_build_diagnostic_detail_block_html('建议', check.hint))

    parts.append("</article>")
    return ''.join(parts)


def _build_diagnostic_report_styles() -> str:
    return (
        "body { font-family: 'Microsoft YaHei UI', 'SimHei', sans-serif; margin: 0; color: #101828; background: #f5f7fa; }"
        ".page { max-width: 1080px; margin: 0 auto; padding: 28px 24px 40px; }"
        ".hero { background: linear-gradient(135deg, #0f172a, #1d4ed8); color: #fff; border-radius: 20px; padding: 28px; box-shadow: 0 16px 48px rgba(15, 23, 42, 0.18); }"
        ".hero h1 { margin: 0 0 10px; font-size: 30px; }"
        ".hero p { margin: 6px 0; color: rgba(255,255,255,0.92); }"
        ".status-badge { display: inline-block; padding: 4px 10px; border-radius: 999px; border: 1px solid transparent; font-size: 12px; font-weight: 700; white-space: nowrap; }"
        ".meta-grid, .metric-grid, .perf-grid, .transition-grid, .check-grid { display: grid; gap: 14px; }"
        ".meta-grid { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 18px; }"
        ".metric-grid { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); margin: 18px 0 10px; }"
        ".metric-card, .meta-card, .transition-card, .check-card, .perf-panel { background: #fff; border: 1px solid #d0d5dd; border-radius: 16px; box-shadow: 0 6px 18px rgba(15, 23, 42, 0.05); }"
        ".metric-card { padding: 16px; }"
        ".metric-label { color: #667085; font-size: 12px; }"
        ".metric-value { margin-top: 6px; font-size: 24px; font-weight: 700; color: #101828; }"
        ".meta-card { padding: 16px; }"
        ".meta-card h3, .section h2 { margin: 0 0 12px; }"
        ".meta-card p { margin: 6px 0; color: #344054; }"
        ".section { margin-top: 22px; }"
        ".section-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }"
        ".section-subtitle { color: #667085; font-size: 13px; }"
        ".transition-grid, .check-grid { grid-template-columns: 1fr; }"
        ".transition-card { padding: 16px; }"
        ".transition-card h3 { margin: 0 0 8px; font-size: 16px; }"
        ".transition-card p { margin: 6px 0; color: #344054; }"
        ".check-card { padding: 18px; }"
        ".check-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }"
        ".check-header h3 { margin: 0; font-size: 18px; }"
        ".check-summary { margin: 8px 0 0; color: #344054; }"
        ".detail-block, .transition-box { margin-top: 12px; padding: 12px 14px; border-radius: 12px; background: #f8fafc; border: 1px solid #e4e7ec; }"
        ".detail-label { font-size: 12px; font-weight: 700; color: #475467; margin-bottom: 6px; }"
        ".detail-value { color: #101828; line-height: 1.7; }"
        ".perf-panel { margin: 14px 0 4px; padding: 14px; }"
        ".section-title-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }"
        ".perf-summary { color: #475467; font-size: 12px; }"
        ".perf-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }"
        ".perf-card { border: 1px solid #d0d5dd; border-radius: 12px; padding: 12px; }"
        ".perf-label { font-size: 12px; font-weight: 700; }"
        ".perf-value { margin-top: 4px; font-size: 20px; font-weight: 700; color: #101828; }"
        ".perf-threshold { margin-top: 4px; color: #667085; font-size: 11px; min-height: 16px; }"
        "@media print { body { background: #fff; } .page { max-width: none; padding: 0; } .hero, .metric-card, .meta-card, .transition-card, .check-card, .perf-panel { box-shadow: none; } .section { page-break-inside: avoid; } }"
    )


def build_diagnostic_report_html(
    report: StartupCheckReport,
    config: AppConfig | None = None,
    previous_report: StartupCheckReport | None = None,
) -> str:
    cfg = config or DEFAULT_CONFIG
    transitions = compare_startup_reports(previous_report, report)
    transition_map = {item.key: item for item in transitions}

    transition_html = ''
    if transitions:
        transition_cards = []
        for item in transitions:
            transition_cards.append(
                "<article class='transition-card'>"
                f"<h3>{escape(item.title)}</h3>"
                f"<p><strong>变化：</strong>{escape(item.label)}</p>"
                f"<p><strong>之前：</strong>{escape(item.previous_summary or '无')}</p>"
                f"<p><strong>现在：</strong>{escape(item.current_summary or '无')}</p>"
                "</article>"
            )
        transition_html = (
            "<section class='section'>"
            "<div class='section-header'><h2>修复前后差异</h2>"
            f"<div class='section-subtitle'>{escape(summarize_transitions(transitions))}</div></div>"
            f"<div class='transition-grid'>{''.join(transition_cards)}</div>"
            "</section>"
        )

    checks_html = ''.join(
        _build_diagnostic_check_html(item, cfg, transition_map.get(item.key))
        for item in report.results
    )

    ocr_enabled = '启用' if cfg.enable_pdf_ocr else '关闭'
    ocr_languages = cfg.ocr_languages or '未设置'
    return (
        "<!DOCTYPE html>"
        "<html lang='zh-CN'>"
        "<head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>PolicyAnalyzerPro 部署诊断报告</title>"
        f"<style>{_build_diagnostic_report_styles()}</style>"
        "</head>"
        "<body>"
        "<div class='page'>"
        "<section class='hero'>"
        "<h1>PolicyAnalyzerPro 部署诊断报告</h1>"
        f"<p>检测时间：{escape(report.checked_at)}</p>"
        f"<p>汇总：{escape(report.summary_text)}</p>"
        f"<p>总体状态：{escape(report.overall_label)}</p>"
        "</section>"
        f"<section class='section'><div class='metric-grid'>{_build_diagnostic_metric_cards_html(report)}</div></section>"
        "<section class='section'>"
        "<div class='section-header'><h2>环境概览</h2><div class='section-subtitle'>当前部署的关键路径和运行前提</div></div>"
        "<div class='meta-grid'>"
        f"<article class='meta-card'><h3>模型与资源</h3><p><strong>模型目录：</strong>{escape(cfg.resolved_model_dir)}</p><p><strong>配置文件：</strong>{escape(DEFAULT_CONFIG_RELATIVE_PATH)}</p></article>"
        f"<article class='meta-card'><h3>OCR 配置</h3><p><strong>OCR 设置：</strong>{ocr_enabled}</p><p><strong>OCR 语言：</strong>{escape(ocr_languages)}</p></article>"
        f"<article class='meta-card'><h3>诊断摘要</h3><p><strong>通过：</strong>{report.ok_count} 项</p><p><strong>警告：</strong>{report.warning_count} 项</p><p><strong>错误：</strong>{report.error_count} 项</p></article>"
        "</div>"
        "</section>"
        f"{transition_html}"
        "<section class='section'>"
        "<div class='section-header'><h2>检查详情</h2><div class='section-subtitle'>每一项部署检查的当前状态、定位信息和修复建议</div></div>"
        f"<div class='check-grid'>{checks_html}</div>"
        "</section>"
        "</div>"
        "</body>"
        "</html>"
    )


def build_diagnostic_report_markdown(
    report: StartupCheckReport,
    config: AppConfig | None = None,
    previous_report: StartupCheckReport | None = None,
) -> str:
    cfg = config or DEFAULT_CONFIG
    transitions = compare_startup_reports(previous_report, report)

    lines = [
        "# PolicyAnalyzerPro 部署诊断报告",
        "",
        f"- 检测时间：{report.checked_at}",
        f"- 总体状态：{report.overall_label}",
        f"- 汇总：{report.summary_text}",
        f"- 模型目录：{cfg.resolved_model_dir}",
        f"- OCR 设置：{'启用' if cfg.enable_pdf_ocr else '关闭'}",
        "",
    ]

    if transitions:
        lines.append("## 修复前后差异")
        lines.append("")
        for item in transitions:
            lines.append(
                f"- {item.title}：{item.label}，由“{item.previous_summary or '无'}”变为“{item.current_summary or '无'}”。"
            )
        lines.append("")

    lines.append("## 检查详情")
    lines.append("")
    for item in report.results:
        lines.extend(
            [
                f"### {item.title}",
                f"- 状态：{item.status}",
                f"- 摘要：{item.summary}",
            ]
        )
        if item.location:
            lines.append(f"- 位置：{item.location}")
        if item.detail:
            lines.append(f"- 详情：{item.detail}")
        if item.hint:
            lines.append(f"- 建议：{item.hint}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def should_show_startup_wizard(settings: object, report: StartupCheckReport) -> bool:
    stored_version = str(getattr(settings, "value")("startup/wizard_version", "") or "")
    stored_signature = str(getattr(settings, "value")("startup/last_signature", "") or "")
    if report.has_critical_issues:
        return True
    if stored_version != STARTUP_WIZARD_VERSION:
        return True
    return stored_signature != report.signature


def mark_startup_wizard_completed(
    settings: object,
    report: StartupCheckReport,
) -> None:
    getattr(settings, "setValue")("startup/wizard_version", STARTUP_WIZARD_VERSION)
    getattr(settings, "setValue")("startup/last_signature", report.signature)
