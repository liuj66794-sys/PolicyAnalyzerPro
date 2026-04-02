from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from .service import PolicyFetchService
from .types import PolicyFetchResult, PolicyFetchTask


@dataclass(slots=True)
class PolicyFetchTaskSnapshot:
    task_id: str
    source_id: str
    status: str
    trigger: str
    submitted_at: datetime
    finished_at: datetime | None = None
    error_message: str = ""
    result_status: str = ""


class PolicyFetchExecutor:
    """Independent background executor for fetch tasks."""

    def __init__(self, service: PolicyFetchService, *, max_workers: int = 2) -> None:
        self.service = service
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="policy-fetch")
        self._futures: dict[str, Future[PolicyFetchResult]] = {}
        self._snapshots: dict[str, PolicyFetchTaskSnapshot] = {}

    def submit_task(
        self,
        task: PolicyFetchTask,
        *,
        sync_repository: bool = True,
    ) -> str:
        normalized = task.normalized()
        task_id = normalized.task_id or f"fetch-{uuid4().hex}"
        normalized.task_id = task_id
        snapshot = PolicyFetchTaskSnapshot(
            task_id=task_id,
            source_id=normalized.source_id or normalized.source_name,
            status="queued",
            trigger=normalized.trigger,
            submitted_at=datetime.now(),
        )
        self._snapshots[task_id] = snapshot
        future = self._executor.submit(self._run_task, normalized, sync_repository)
        future.add_done_callback(lambda done, tid=task_id: self._mark_done(tid, done))
        self._futures[task_id] = future
        return task_id

    def run_due_sources(self, *, now: datetime | None = None, sync_repository: bool = True) -> list[str]:
        current = now or datetime.now()
        task_ids: list[str] = []
        for definition in self.service.get_registry().list_definitions():
            if not definition.enabled or definition.schedule != "daily":
                continue
            if not self.service.is_source_due(definition.source_id, now=current):
                continue
            task_ids.append(
                self.submit_task(
                    PolicyFetchTask(
                        source_id=definition.source_id,
                        source_name=definition.name,
                        incremental=True,
                        trigger="scheduled",
                    ),
                    sync_repository=sync_repository,
                )
            )
        return task_ids

    def wait_for_task(self, task_id: str, timeout: float | None = None) -> PolicyFetchResult:
        return self._futures[task_id].result(timeout=timeout)

    def get_task_snapshot(self, task_id: str) -> PolicyFetchTaskSnapshot | None:
        return self._snapshots.get(task_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _run_task(self, task: PolicyFetchTask, sync_repository: bool) -> PolicyFetchResult:
        snapshot = self._snapshots.get(task.task_id)
        if snapshot is not None:
            snapshot.status = "running"
            snapshot.source_id = task.source_id or task.source_name
        return self.service.run_collection_task(task, sync_repository=sync_repository)

    def _mark_done(self, task_id: str, future: Future[PolicyFetchResult]) -> None:
        snapshot = self._snapshots.get(task_id)
        if snapshot is None:
            return
        snapshot.finished_at = datetime.now()
        try:
            result = future.result()
        except Exception as exc:  # pragma: no cover - defensive boundary
            snapshot.status = "failed"
            snapshot.error_message = str(exc)
            snapshot.result_status = "failed"
            return

        snapshot.status = "completed" if result.ok else "failed"
        snapshot.result_status = result.status
        snapshot.source_id = result.source_id or snapshot.source_id
        if result.errors:
            snapshot.error_message = result.errors[0]
