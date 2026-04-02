from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

ANALYSIS_MODE_OFFLINE = "offline"
ANALYSIS_MODE_ONLINE = "online"
ANALYSIS_MODE_HYBRID = "hybrid"

_MODE_LABELS = {
    ANALYSIS_MODE_OFFLINE: "离线分析",
    ANALYSIS_MODE_ONLINE: "在线分析",
    ANALYSIS_MODE_HYBRID: "混合分析",
}

_STAGE_LABELS = {
    "validation": "输入校验",
    "routing": "模式路由",
    "initialization": "任务初始化",
    "capability_check": "能力检查",
    "execution": "后台执行",
    "result": "结果整理",
}


def normalize_analysis_error_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _MODE_LABELS:
        return normalized
    return ANALYSIS_MODE_OFFLINE


def normalize_analysis_error_stage(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _STAGE_LABELS:
        return normalized
    return "execution"


def get_analysis_error_mode_label(mode: str | None) -> str:
    normalized = normalize_analysis_error_mode(mode)
    return _MODE_LABELS.get(normalized, _MODE_LABELS[ANALYSIS_MODE_OFFLINE])


def get_analysis_error_stage_label(stage: str | None) -> str:
    normalized = normalize_analysis_error_stage(stage)
    return _STAGE_LABELS.get(normalized, _STAGE_LABELS["execution"])


@dataclass(slots=True)
class AnalysisErrorInfo:
    mode: str = ANALYSIS_MODE_OFFLINE
    stage: str = "execution"
    category: str = "runtime"
    title: str = "离线分析失败"
    user_message: str = "离线分析过程中发生错误。"
    detail: str = ""
    requested_mode: str = ""
    executed_mode: str = ""
    task_mode: str = ""
    exception_type: str = ""
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnalysisExecutionError(RuntimeError):
    def __init__(
        self,
        *,
        mode: str,
        stage: str = "execution",
        category: str = "runtime",
        user_message: str,
        detail: str = "",
        title: str | None = None,
    ) -> None:
        self.mode = normalize_analysis_error_mode(mode)
        self.stage = normalize_analysis_error_stage(stage)
        self.category = str(category or "runtime").strip().lower() or "runtime"
        self.user_message = str(user_message or _default_user_message(self.mode))
        self.detail = str(detail or "").strip()
        self.title = str(title or _default_title(self.mode))
        super().__init__(self.detail or self.user_message)

    def to_info(
        self,
        *,
        requested_mode: str | None = None,
        executed_mode: str | None = None,
        task_mode: str = "",
        degraded: bool = False,
    ) -> AnalysisErrorInfo:
        resolved_executed_mode = normalize_analysis_error_mode(executed_mode or self.mode)
        return AnalysisErrorInfo(
            mode=self.mode,
            stage=self.stage,
            category=self.category,
            title=self.title,
            user_message=self.user_message,
            detail=self.detail,
            requested_mode=normalize_analysis_error_mode(requested_mode or self.mode),
            executed_mode=resolved_executed_mode,
            task_mode=str(task_mode or ""),
            exception_type=type(self).__name__,
            degraded=bool(degraded),
        )


class OfflineAnalysisError(AnalysisExecutionError):
    def __init__(
        self,
        user_message: str = "离线分析过程中发生错误。",
        *,
        stage: str = "execution",
        category: str = "runtime",
        detail: str = "",
    ) -> None:
        super().__init__(
            mode=ANALYSIS_MODE_OFFLINE,
            stage=stage,
            category=category,
            user_message=user_message,
            detail=detail,
            title="离线分析失败",
        )


class OnlineAnalysisError(AnalysisExecutionError):
    def __init__(
        self,
        user_message: str = "在线分析过程中发生错误。",
        *,
        stage: str = "execution",
        category: str = "runtime",
        detail: str = "",
    ) -> None:
        super().__init__(
            mode=ANALYSIS_MODE_ONLINE,
            stage=stage,
            category=category,
            user_message=user_message,
            detail=detail,
            title="在线分析失败",
        )


class HybridAnalysisError(AnalysisExecutionError):
    def __init__(
        self,
        user_message: str = "混合分析过程中发生错误。",
        *,
        stage: str = "execution",
        category: str = "runtime",
        detail: str = "",
    ) -> None:
        super().__init__(
            mode=ANALYSIS_MODE_HYBRID,
            stage=stage,
            category=category,
            user_message=user_message,
            detail=detail,
            title="混合分析失败",
        )


def _default_title(mode: str | None) -> str:
    label = get_analysis_error_mode_label(mode)
    return f"{label}失败"


def _default_user_message(mode: str | None) -> str:
    label = get_analysis_error_mode_label(mode)
    return f"{label}过程中发生错误。"


def coerce_analysis_error_info(
    payload: Any,
    *,
    requested_mode: str | None = None,
    executed_mode: str | None = None,
    task_mode: str = "",
    default_mode: str | None = None,
    default_stage: str = "execution",
    degraded: bool = False,
) -> AnalysisErrorInfo:
    if isinstance(payload, AnalysisErrorInfo):
        info = AnalysisErrorInfo(**payload.to_dict())
    elif isinstance(payload, AnalysisExecutionError):
        info = payload.to_info(
            requested_mode=requested_mode,
            executed_mode=executed_mode,
            task_mode=task_mode,
            degraded=degraded,
        )
    elif isinstance(payload, dict):
        mode = normalize_analysis_error_mode(payload.get("mode") or executed_mode or requested_mode or default_mode)
        info = AnalysisErrorInfo(
            mode=mode,
            stage=normalize_analysis_error_stage(payload.get("stage") or default_stage),
            category=str(payload.get("category", "runtime") or "runtime"),
            title=str(payload.get("title") or _default_title(mode)),
            user_message=str(payload.get("user_message") or _default_user_message(mode)),
            detail=str(payload.get("detail") or "").strip(),
            requested_mode=normalize_analysis_error_mode(payload.get("requested_mode") or requested_mode or mode),
            executed_mode=normalize_analysis_error_mode(payload.get("executed_mode") or executed_mode or mode),
            task_mode=str(payload.get("task_mode") or task_mode or ""),
            exception_type=str(payload.get("exception_type") or ""),
            degraded=bool(payload.get("degraded", degraded)),
        )
    elif isinstance(payload, str):
        mode = normalize_analysis_error_mode(default_mode or executed_mode or requested_mode)
        info = AnalysisErrorInfo(
            mode=mode,
            stage=normalize_analysis_error_stage(default_stage),
            category="runtime",
            title=_default_title(mode),
            user_message=payload,
            requested_mode=normalize_analysis_error_mode(requested_mode or mode),
            executed_mode=normalize_analysis_error_mode(executed_mode or mode),
            task_mode=str(task_mode or ""),
            degraded=bool(degraded),
        )
    else:
        mode = normalize_analysis_error_mode(default_mode or executed_mode or requested_mode)
        detail = str(payload or "").strip()
        info = AnalysisErrorInfo(
            mode=mode,
            stage=normalize_analysis_error_stage(default_stage),
            category="runtime",
            title=_default_title(mode),
            user_message=_default_user_message(mode),
            detail=detail,
            requested_mode=normalize_analysis_error_mode(requested_mode or mode),
            executed_mode=normalize_analysis_error_mode(executed_mode or mode),
            task_mode=str(task_mode or ""),
            exception_type=type(payload).__name__ if payload is not None else "",
            degraded=bool(degraded),
        )

    if not info.requested_mode:
        info.requested_mode = normalize_analysis_error_mode(requested_mode or info.mode)
    if not info.executed_mode:
        info.executed_mode = normalize_analysis_error_mode(executed_mode or info.mode)
    if not info.task_mode:
        info.task_mode = str(task_mode or info.task_mode or "")
    return info


def build_analysis_error_text(payload: Any) -> str:
    info = coerce_analysis_error_info(payload)
    lines = [info.user_message]

    requested = normalize_analysis_error_mode(info.requested_mode or info.mode)
    executed = normalize_analysis_error_mode(info.executed_mode or info.mode)
    if requested and executed:
        if requested == executed:
            lines.append(f"执行模式：{get_analysis_error_mode_label(executed)}")
        else:
            lines.append(
                f"执行模式：请求 {get_analysis_error_mode_label(requested)}，实际 {get_analysis_error_mode_label(executed)}"
            )

    lines.append(f"失败阶段：{get_analysis_error_stage_label(info.stage)}")
    if info.detail and info.detail != info.user_message:
        lines.append(f"详细信息：{info.detail}")
    return "\n".join(line for line in lines if line)


def build_analysis_error_status_text(payload: Any) -> str:
    info = coerce_analysis_error_info(payload)
    return f"{info.title}：{info.user_message}"


def build_analysis_error_markdown(payload: Any) -> str:
    info = coerce_analysis_error_info(payload)
    lines = [f"# {info.title}", "", info.user_message, ""]

    requested = normalize_analysis_error_mode(info.requested_mode or info.mode)
    executed = normalize_analysis_error_mode(info.executed_mode or info.mode)
    if requested == executed:
        route_text = f"执行模式：{get_analysis_error_mode_label(executed)}"
    else:
        route_text = (
            f"执行模式：请求 {get_analysis_error_mode_label(requested)}，"
            f"实际 {get_analysis_error_mode_label(executed)}"
        )

    lines.append(f"- {route_text}")
    lines.append(f"- 失败阶段：{get_analysis_error_stage_label(info.stage)}")
    if info.detail and info.detail != info.user_message:
        lines.append(f"- 详细信息：{info.detail}")
    return "\n".join(lines)


def build_analysis_error_result(
    payload: Any,
    *,
    import_preview_notes: list[str] | None = None,
) -> dict[str, Any]:
    info = coerce_analysis_error_info(payload)
    result = {
        "mode": info.task_mode or "single",
        "analysis_status": "error",
        "analysis_error": info.to_dict(),
        "summary_overview": {
            "headline": info.user_message,
            "key_takeaways": [f"?????{get_analysis_error_stage_label(info.stage)}"],
        },
        "requested_analysis_mode": normalize_analysis_error_mode(info.requested_mode or info.mode),
        "executed_analysis_mode": normalize_analysis_error_mode(info.executed_mode or info.mode),
        "analysis_route_status": "error",
        "analysis_route_message": info.user_message,
        "analysis_route_warnings": [f"?????{get_analysis_error_stage_label(info.stage)}"],
        "analysis_mode": normalize_analysis_error_mode(info.executed_mode or info.mode),
    }
    if import_preview_notes:
        result["import_preview_notes"] = [str(note) for note in import_preview_notes if str(note).strip()]
    return result
