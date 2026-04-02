from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.config import AppConfig, DEFAULT_CONFIG
from core.hybrid_pipeline import HybridPipelineService
from core.online_llm import OnlineLLMService

ANALYSIS_MODE_OFFLINE = "offline"
ANALYSIS_MODE_ONLINE = "online"
ANALYSIS_MODE_HYBRID = "hybrid"
SUPPORTED_ANALYSIS_MODES = (
    ANALYSIS_MODE_OFFLINE,
    ANALYSIS_MODE_ONLINE,
    ANALYSIS_MODE_HYBRID,
)

_ANALYSIS_MODE_LABELS = {
    ANALYSIS_MODE_OFFLINE: "离线分析",
    ANALYSIS_MODE_ONLINE: "在线分析",
    ANALYSIS_MODE_HYBRID: "混合分析",
}


@dataclass(slots=True)
class AnalysisCapabilitySnapshot:
    selected_mode: str
    dependency_status: str = "ok"
    policy_source_enabled: bool = False
    online_ready: bool = False
    online_state: str = "disabled"
    online_summary: str = "在线能力未启用。"
    hybrid_ready: bool = False
    hybrid_state: str = "disabled"
    hybrid_summary: str = "混合分析未启用。"


@dataclass(slots=True)
class AnalysisRouteDecision:
    requested_mode: str
    executed_mode: str
    degraded: bool = False
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    capability_snapshot: AnalysisCapabilitySnapshot | None = None


def normalize_analysis_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_ANALYSIS_MODES:
        return normalized
    return ANALYSIS_MODE_OFFLINE


def get_analysis_mode_label(mode: str | None) -> str:
    normalized = normalize_analysis_mode(mode)
    return _ANALYSIS_MODE_LABELS.get(normalized, _ANALYSIS_MODE_LABELS[ANALYSIS_MODE_OFFLINE])


def build_capability_snapshot(
    config: AppConfig | None = None,
    startup_report: Any | None = None,
) -> AnalysisCapabilitySnapshot:
    cfg = config or DEFAULT_CONFIG

    dependency_status = "ok"
    if startup_report is not None:
        if getattr(startup_report, "has_critical_issues", False):
            dependency_status = "error"
        elif getattr(startup_report, "warning_count", 0) > 0:
            dependency_status = "warning"

    online_status = OnlineLLMService(cfg).get_status()
    hybrid_status = HybridPipelineService(cfg).get_status()

    return AnalysisCapabilitySnapshot(
        selected_mode=normalize_analysis_mode(cfg.analysis_mode),
        dependency_status=dependency_status,
        policy_source_enabled=bool(cfg.policy_source_enabled),
        online_ready=online_status.available,
        online_state=online_status.state,
        online_summary=online_status.summary,
        hybrid_ready=hybrid_status.available,
        hybrid_state=hybrid_status.state,
        hybrid_summary=hybrid_status.summary,
    )


def resolve_analysis_route(
    requested_mode: str | None,
    *,
    config: AppConfig | None = None,
    startup_report: Any | None = None,
) -> AnalysisRouteDecision:
    cfg = config or DEFAULT_CONFIG
    normalized_mode = normalize_analysis_mode(requested_mode or cfg.analysis_mode)
    snapshot = build_capability_snapshot(cfg, startup_report=startup_report)

    if normalized_mode == ANALYSIS_MODE_OFFLINE:
        return AnalysisRouteDecision(
            requested_mode=normalized_mode,
            executed_mode=ANALYSIS_MODE_OFFLINE,
            degraded=False,
            message="当前按离线模式执行。",
            capability_snapshot=snapshot,
        )

    if normalized_mode == ANALYSIS_MODE_ONLINE:
        if snapshot.online_ready:
            return AnalysisRouteDecision(
                requested_mode=normalized_mode,
                executed_mode=ANALYSIS_MODE_ONLINE,
                degraded=False,
                message="当前按在线模式执行。",
                capability_snapshot=snapshot,
            )
        warning = snapshot.online_summary or "在线能力当前不可用。"
        return AnalysisRouteDecision(
            requested_mode=normalized_mode,
            executed_mode=ANALYSIS_MODE_OFFLINE,
            degraded=True,
            message="在线模式当前不可用，已自动回退到离线模式。",
            warnings=[warning],
            capability_snapshot=snapshot,
        )

    if snapshot.hybrid_ready:
        return AnalysisRouteDecision(
            requested_mode=normalized_mode,
            executed_mode=ANALYSIS_MODE_HYBRID,
            degraded=False,
            message="当前按混合模式执行。",
            capability_snapshot=snapshot,
        )

    warning = snapshot.hybrid_summary or "混合分析当前不可用。"
    return AnalysisRouteDecision(
        requested_mode=normalized_mode,
        executed_mode=ANALYSIS_MODE_OFFLINE,
        degraded=True,
        message="混合模式当前不可用，已自动回退到离线模式。",
        warnings=[warning],
        capability_snapshot=snapshot,
    )


def apply_route_metadata(result: dict[str, Any], decision: AnalysisRouteDecision) -> dict[str, Any]:
    payload = dict(result)
    payload["requested_analysis_mode"] = decision.requested_mode
    payload["executed_analysis_mode"] = decision.executed_mode
    payload["analysis_route_status"] = "degraded" if decision.degraded else "ok"
    payload["analysis_route_message"] = decision.message
    payload["analysis_route_warnings"] = list(decision.warnings)
    payload["analysis_mode"] = decision.executed_mode
    snapshot = decision.capability_snapshot
    if snapshot is not None:
        payload["capability_snapshot"] = {
            "selected_mode": snapshot.selected_mode,
            "dependency_status": snapshot.dependency_status,
            "policy_source_enabled": snapshot.policy_source_enabled,
            "online_ready": snapshot.online_ready,
            "online_state": snapshot.online_state,
            "online_summary": snapshot.online_summary,
            "hybrid_ready": snapshot.hybrid_ready,
            "hybrid_state": snapshot.hybrid_state,
            "hybrid_summary": snapshot.hybrid_summary,
        }
    return payload


def build_analysis_route_text(result: dict[str, Any]) -> str:
    requested = normalize_analysis_mode(result.get("requested_analysis_mode"))
    executed = normalize_analysis_mode(result.get("executed_analysis_mode"))
    if requested == executed:
        return f"分析模式：{get_analysis_mode_label(executed)}"
    return (
        f"分析模式：请求 {get_analysis_mode_label(requested)}，"
        f"实际执行 {get_analysis_mode_label(executed)}"
    )
