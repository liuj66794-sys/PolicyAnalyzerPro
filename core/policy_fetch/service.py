from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.config import AppConfig, DEFAULT_CONFIG

from .types import (
    PolicyFetchTask,
    PolicyFetchResult,
    PolicyFetchStatus,
    PolicyRecord,
    FetchLogEntry,
    FetchHealthStatus,
)


@dataclass(slots=True)
class PolicyFetchStatus:
    enabled: bool
    state: str
    summary: str


@dataclass(slots=True)
class PolicyFetchResult:
    ok: bool
    records: list[PolicyRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class PolicySourceAdapter(ABC):
    """
    Base interface for policy source adapters.

    Each policy source (website, RSS, API, etc.) implements this interface
    for task2 incremental fetching and integration.
    """

    @abstractmethod
    def get_source_id(self) -> str:
        """Get the unique identifier for this source adapter."""
        ...

    @abstractmethod
    def get_source_name(self) -> str:
        """Get the human-readable name for this source."""
        ...

    @abstractmethod
    def can_fetch(self) -> bool:
        """Check if this adapter is properly configured and can fetch."""
        ...

    @abstractmethod
    def fetch(self, incremental: bool = False) -> PolicyFetchResult:
        """Execute fetch from this source."""
        ...


class PolicySourceRegistry:
    """
    Registry for policy source adapters.

    Reserved for task2 to register multiple policy sources.
    The registry is optional and not required for the offline analysis main path.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, PolicySourceAdapter] = {}

    def register(self, adapter: PolicySourceAdapter) -> None:
        """Register a policy source adapter."""
        self._adapters[adapter.get_source_id()] = adapter

    def unregister(self, source_id: str) -> bool:
        """Unregister a policy source adapter."""
        if source_id in self._adapters:
            del self._adapters[source_id]
            return True
        return False

    def get_adapter(self, source_id: str) -> PolicySourceAdapter | None:
        """Get a registered adapter by source id."""
        return self._adapters.get(source_id)

    def list_adapters(self) -> list[str]:
        """List all registered source ids."""
        return list(self._adapters.keys())


class PolicyFetchService:
    """
    Policy fetch service kept decoupled from the analysis pipeline.

    Design principles:
    - Does not block the main analysis startup or execution
    - Default disabled, only enabled when explicitly configured
    - Skeleton structure allows task2 extension without breaking existing code
    - Maintains clear separation between fetch pipeline and analysis pipeline
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or DEFAULT_CONFIG
        self._registry: PolicySourceRegistry | None = None  # Lazy initialized in task2

    def get_status(self) -> PolicyFetchStatus:
        """Get current status of the fetch subsystem."""
        if not self.config.policy_source_enabled:
            return PolicyFetchStatus(False, "disabled", "政策采集模块未启用，不影响当前分析主流程。")
        return PolicyFetchStatus(True, "idle", "政策采集骨架已就绪，待后续站点规则接入。")

    def start_collection_task(self, task: PolicyFetchTask | None = None) -> PolicyFetchResult:
        """
        Start a collection task.

        In task1 this is just a skeleton - real execution happens in task2.
        Fetch never blocks the main analysis path.
        """
        status = self.get_status()
        task = task or PolicyFetchTask()
        warnings = [status.summary]
        if task.source:
            warnings.append(f"当前骨架版本未执行真实抓取，已忽略来源：{task.source}")
        return PolicyFetchResult(ok=False, warnings=warnings)

    def pull_results(self) -> list[PolicyRecord]:
        """
        Pull completed fetch results into local repository for analysis.

        Results from fetch flow into here, then get handed to analysis entry point.
        """
        return []

    def get_health_status(self) -> FetchHealthStatus:
        """
        Get health check result for the fetch subsystem.

        Reserved for task2 logging and health monitoring.
        """
        return FetchHealthStatus(
            overall_ok=not self.config.policy_source_enabled,
            total_policies=0,
            last_success=None,
        )

    def get_recent_logs(self, limit: int = 50) -> list[FetchLogEntry]:
        """
        Get recent fetch logs for UI display.

        Reserved for task2 logging UI.
        """
        return []

    def get_registry(self) -> PolicySourceRegistry | None:
        """
        Get the policy source registry.

        Registry is created lazily when needed in task2.
        """
        return self._registry

    def set_registry(self, registry: PolicySourceRegistry) -> None:
        """
        Set the policy source registry.

        Called during task2 initialization when sources are registered.
        """
        self._registry = registry
