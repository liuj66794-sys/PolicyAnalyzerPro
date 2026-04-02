from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import AppConfig, DEFAULT_CONFIG

from .errors import HybridPipelineUnavailableError
from .types import HybridExecutionPlan, HybridExecutionResult


@dataclass(slots=True)
class HybridPipelineStatus:
    available: bool
    state: str
    summary: str


class HybridPipelineService:
    """Hybrid pipeline skeleton for future local-plus-online orchestration."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG

    def get_status(self) -> HybridPipelineStatus:
        if not self.config.cloud_fallback_enabled:
            return HybridPipelineStatus(False, "disabled", "混合分析未启用，当前保持纯离线运行。")

        provider = (self.config.llm_provider or "").strip()
        if not provider:
            return HybridPipelineStatus(False, "unconfigured", "尚未配置在线模型提供方，混合分析不会启用。")

        return HybridPipelineStatus(
            False,
            "skeleton",
            "混合编排骨架已接入，但当前版本尚未启用正式在线增强执行。",
        )

    def build_plan(self, task_kind: str, payload: dict[str, Any]) -> HybridExecutionPlan:
        selected_segments: list[str] = []
        if task_kind == "single":
            text = str(payload.get("text", "") or "").strip()
            if text:
                selected_segments.append(text[:2000])
        return HybridExecutionPlan(task_kind=task_kind, selected_segments=selected_segments)

    def run(self, task_kind: str, payload: dict[str, Any]) -> HybridExecutionResult:
        status = self.get_status()
        if not status.available:
            raise HybridPipelineUnavailableError(status.summary)
        return HybridExecutionResult(ok=False, warnings=[status.summary])

    def run_single(self, text: str) -> HybridExecutionResult:
        return self.run("single", {"text": text})

    def run_compare(self, old_text: str, new_text: str) -> HybridExecutionResult:
        return self.run("compare", {"old_text": old_text, "new_text": new_text})

    def run_batch(self, batch_inputs: list[dict[str, Any]]) -> HybridExecutionResult:
        return self.run("batch", {"batch_inputs": [dict(item) for item in batch_inputs]})
