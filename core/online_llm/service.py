from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config import AppConfig, DEFAULT_CONFIG

from .errors import OnlineLLMUnavailableError
from .types import OnlineLLMRequest, OnlineLLMResponse


@dataclass(slots=True)
class OnlineLLMStatus:
    available: bool
    state: str
    summary: str


class OnlineLLMService:
    """Online LLM skeleton for future provider integration."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG

    def get_status(self) -> OnlineLLMStatus:
        if not self.config.cloud_fallback_enabled:
            return OnlineLLMStatus(False, "disabled", "在线分析未启用，当前保持纯离线运行。")

        provider = (self.config.llm_provider or "").strip()
        if not provider:
            return OnlineLLMStatus(False, "unconfigured", "尚未配置在线模型提供方，在线分析不会启用。")

        return OnlineLLMStatus(
            False,
            "skeleton",
            "在线调用骨架已接入，但当前版本尚未启用正式 Provider 执行。",
        )

    def create_request(self, task_kind: str, payload: dict[str, Any]) -> OnlineLLMRequest:
        return OnlineLLMRequest(
            task_kind=task_kind,
            payload=dict(payload),
            provider=(self.config.llm_provider or "").strip(),
        )

    def analyze(self, task_kind: str, payload: dict[str, Any]) -> OnlineLLMResponse:
        status = self.get_status()
        if not status.available:
            raise OnlineLLMUnavailableError(status.summary)
        return OnlineLLMResponse(ok=False, error_message=status.summary)

    def analyze_single(self, text: str) -> OnlineLLMResponse:
        return self.analyze("single", {"text": text})

    def analyze_compare(self, old_text: str, new_text: str) -> OnlineLLMResponse:
        return self.analyze("compare", {"old_text": old_text, "new_text": new_text})

    def analyze_batch(self, batch_inputs: list[dict[str, Any]]) -> OnlineLLMResponse:
        return self.analyze("batch", {"batch_inputs": [dict(item) for item in batch_inputs]})
