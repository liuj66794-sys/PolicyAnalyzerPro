from __future__ import annotations

import json
import os
import shutil
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.config import load_app_config
from core.policy_fetch import (
    PolicyFetchContext,
    PolicyFetchResult,
    PolicyFetchService,
    PolicyFetchTask,
    PolicyRecord,
    PolicySourceAdapter,
    PolicySourceDefinition,
    PolicySourceRegistry,
    append_policy_fetch_audit_event,
    build_policy_fetch_audit_record,
    get_policy_fetch_audit_log_path,
)
from core.policy_fetch.types import FetchLogEntry


class FakePolicyAdapter(PolicySourceAdapter):
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def get_source_id(self) -> str:
        return "gov-demo"

    def get_source_name(self) -> str:
        return "Demo Source"

    def get_source_definition(self) -> PolicySourceDefinition:
        return PolicySourceDefinition(
            source_id="gov-demo",
            name="Demo Source",
            base_url="https://example.gov.cn",
            source_kind="html_list_detail",
            list_fetch_strategy="html_list",
            detail_fetch_strategy="html_detail",
            incremental_strategy="published_at",
        )

    def can_fetch(self) -> bool:
        return True

    def fetch(
        self,
        incremental: bool = False,
        context: PolicyFetchContext | None = None,
    ) -> PolicyFetchResult:
        self.calls.append(bool(incremental))
        return PolicyFetchResult(
            ok=True,
            status="completed",
            records=[
                PolicyRecord(
                    title="关于推进示范改革的通知",
                    content="为进一步推进改革试点，现提出如下意见。",
                    source_url="https://example.gov.cn/policy/1",
                    raw_published_at="2026-03-01",
                    published_at="2026-03-01",
                    source_name="Demo Source",
                )
            ],
            log_entries=[
                FetchLogEntry(
                    timestamp=datetime(2026, 4, 1, 9, 0, 0),
                    event_type="list_fetch_succeeded",
                    status="ok",
                    message="列表抓取成功。",
                    document_count=1,
                )
            ],
        )


class InvalidRecordAdapter(FakePolicyAdapter):
    def fetch(
        self,
        incremental: bool = False,
        context: PolicyFetchContext | None = None,
    ) -> PolicyFetchResult:
        self.calls.append(bool(incremental))
        return PolicyFetchResult(
            ok=True,
            status="completed",
            records=[PolicyRecord(title="", content="")],
        )


@dataclass
class FakeRepository:
    records: list[PolicyRecord]
    states: dict[str, dict]

    def upsert_records(self, records: list[PolicyRecord]) -> int:
        self.records.extend(records)
        return len(records)

    def get_source_state(self, source_id: str) -> dict:
        return dict(self.states.get(source_id, {}))

    def save_source_state(self, source_id: str, state: dict) -> None:
        self.states[source_id] = dict(state)


class PolicyFetchTests(unittest.TestCase):
    def test_policy_record_normalizes_schema_and_compat_aliases(self) -> None:
        record = PolicyRecord(
            title=" 政策标题 ",
            content=" 正文内容 ",
            source_name=" 国家发改委 ",
            source_url="https://example.gov.cn/policy/42",
            published_at="2026-03-20 10:00:00",
        ).normalized()

        self.assertEqual(record.source, "国家发改委")
        self.assertEqual(record.publish_time.strftime("%Y-%m-%d %H:%M:%S"), "2026-03-20 10:00:00")
        self.assertTrue(record.fetched_at is not None)
        self.assertTrue(bool(record.content_hash))
        self.assertEqual(record.source_type, "website")
        self.assertIn("url:https://example.gov.cn/policy/42", record.dedupe_keys())
        self.assertTrue(any(key.startswith("content_hash:") for key in record.dedupe_keys()))

    def test_registry_keeps_source_definition_and_adapter_separate(self) -> None:
        registry = PolicySourceRegistry()
        adapter = FakePolicyAdapter()
        registry.register(adapter)

        self.assertEqual(registry.list_adapters(), ["gov-demo"])
        self.assertEqual(registry.configured_source_count(enabled_only=True), 1)
        definition = registry.get_definition("gov-demo")
        self.assertIsNotNone(definition)
        self.assertEqual(definition.base_url, "https://example.gov.cn")
        self.assertEqual(registry.resolve_source_id(""), "gov-demo")
        self.assertEqual(registry.resolve_source_id("Demo Source"), "gov-demo")

    def test_health_status_is_not_ok_when_enabled_but_unconfigured(self) -> None:
        config = load_app_config().merge({"policy_source_enabled": True})
        service = PolicyFetchService(config)

        status = service.get_status()
        health = service.get_health_status()

        self.assertEqual(status.state, "unconfigured")
        self.assertFalse(health.overall_ok)
        self.assertEqual(health.configured_sources, 0)

    def test_service_runs_fetch_only_inside_policy_fetch_boundary(self) -> None:
        config = load_app_config().merge({"policy_source_enabled": True})
        service = PolicyFetchService(config)
        registry = PolicySourceRegistry()
        adapter = FakePolicyAdapter()
        registry.register(adapter)
        service.set_registry(registry)
        service.bind_repository(FakeRepository(records=[], states={}))

        result = service.start_collection_task(PolicyFetchTask(task_id="task-1", source_name="Demo Source", incremental=True))

        self.assertTrue(result.ok)
        self.assertEqual(result.source_id, "gov-demo")
        self.assertEqual(result.total_records, 1)
        self.assertEqual(adapter.calls, [True])
        self.assertEqual(service.get_status().state, "results_ready")
        self.assertTrue(any(item.event_type == "list_fetch_succeeded" for item in result.log_entries))
        self.assertTrue(any(item.event_type == "fetch_completed" for item in result.log_entries))
        self.assertTrue(all("analysis_" not in item.event_type for item in result.log_entries))
        recent_logs = service.get_recent_logs(limit=10)
        self.assertTrue(any(item.event_type == "list_fetch_succeeded" for item in recent_logs))

    def test_service_validation_failure_returns_failed_result_instead_of_raising(self) -> None:
        config = load_app_config().merge({"policy_source_enabled": True})
        service = PolicyFetchService(config)
        registry = PolicySourceRegistry()
        registry.register(InvalidRecordAdapter())
        service.set_registry(registry)

        result = service.start_collection_task(PolicyFetchTask(task_id="task-invalid"))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertTrue(any("title" in item or "content" in item for item in result.errors))
        self.assertTrue(any(item.event_type == "fetch_failed" for item in result.log_entries))

    def test_service_flushes_results_into_repository_boundary(self) -> None:
        config = load_app_config().merge({"policy_source_enabled": True})
        service = PolicyFetchService(config)
        registry = PolicySourceRegistry()
        registry.register(FakePolicyAdapter())
        service.set_registry(registry)
        service.start_collection_task(PolicyFetchTask(task_id="task-2"))

        repository = FakeRepository(records=[], states={})
        service.bind_repository(repository)
        inserted = service.flush_results_to_repository()

        self.assertEqual(inserted, 1)
        self.assertEqual(len(repository.records), 1)
        self.assertEqual(service.get_status().pending_record_count, 0)
        self.assertTrue(service.get_health_status().repository_bound)
        self.assertIn("gov-demo", repository.states)

    def test_policy_fetch_audit_uses_separate_jsonl_file(self) -> None:
        temp_dir = Path("tests/_tmp_policy_fetch_audit") / "case_audit"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        previous = os.environ.get("POLICY_FETCH_AUDIT_DIR")
        os.environ["POLICY_FETCH_AUDIT_DIR"] = str(temp_dir)
        if previous is None:
            self.addCleanup(lambda: os.environ.pop("POLICY_FETCH_AUDIT_DIR", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("POLICY_FETCH_AUDIT_DIR", previous))

        event = FetchLogEntry(
            event_type="fetch_started",
            status="started",
            message="政策采集已开始。",
            source_id="gov-demo",
        )
        record = build_policy_fetch_audit_record(event, result_status="started")
        path = append_policy_fetch_audit_event(event, result_status="started")

        self.assertEqual(path, get_policy_fetch_audit_log_path())
        self.assertTrue(path.name.endswith("policy-fetch-events.jsonl"))
        self.assertEqual(record["domain"], "policy_fetch")
        self.assertEqual(record["event_type"], "fetch_started")
        payload = json.loads(path.read_text(encoding="utf-8").strip())
        self.assertEqual(payload["domain"], "policy_fetch")
        self.assertNotIn("analysis_error_mode", payload)


if __name__ == "__main__":
    unittest.main()
