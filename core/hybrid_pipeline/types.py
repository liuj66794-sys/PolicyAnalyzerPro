from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HybridExecutionPlan:
    task_kind: str
    selected_segments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HybridExecutionResult:
    ok: bool
    local_result: dict[str, Any] = field(default_factory=dict)
    online_result: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
