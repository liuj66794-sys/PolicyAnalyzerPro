from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class PolicyFetchTask:
    """Request to start a policy fetch task."""
    source: str = ""
    source_id: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    incremental: bool = False  # 增量抓取标记，任务2预留


@dataclass(slots=True)
class PolicyRecord:
    """
    Minimum policy record constraint for future task2 integration.

    This defines the minimal fields that must be provided after fetching
    before entering the local policy repository and analysis pipeline.
    """
    title: str = ""
    content: str = ""
    source: str = ""
    source_url: str = ""
    publish_time: datetime | None = None
    policy_id: str = ""  # 唯一标识，任务2用于去重和增量更新
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchLogEntry:
    """Fetch log entry for status checking and health inspection."""
    timestamp: datetime
    level: str  # info, warning, error
    message: str
    source: str = ""
    policy_id: str = ""


@dataclass(slots=True)
class FetchHealthStatus:
    """Health check result for the fetch subsystem."""
    overall_ok: bool
    total_policies: int
    last_success: datetime | None
    errors: list[str] = field(default_factory=list)
