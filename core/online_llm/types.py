from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class OnlineLLMRequest:
    task_kind: str
    payload: dict[str, Any]
    provider: str = ""
    timeout_sec: int = 60


@dataclass(slots=True)
class OnlineLLMResponse:
    ok: bool
    content: dict[str, Any] = field(default_factory=dict)
    provider_meta: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
