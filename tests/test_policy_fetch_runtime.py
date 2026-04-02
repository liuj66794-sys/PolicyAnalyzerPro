from __future__ import annotations

import json
import shutil
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from core.config import load_app_config
from core.policy_fetch import PolicyFetchExecutor, PolicyFetchService, PolicyFetchTask, SqlitePolicyRepository


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    def serve_forever(self, poll_interval: float = 0.5) -> None:
        try:
            super().serve_forever(poll_interval=poll_interval)
        except OSError as exc:
            if getattr(exc, "winerror", None) != 10038:
                raise


class _RuntimeRequestHandler(BaseHTTPRequestHandler):
    routes: dict[str, tuple[int, str, str]] = {}
    counters: dict[str, int] = {}

    def do_GET(self) -> None:  # noqa: N802
        path = self.path
        _RuntimeRequestHandler.counters[path] = _RuntimeRequestHandler.counters.get(path, 0) + 1

        if path == "/retry/rss.xml" and _RuntimeRequestHandler.counters[path] == 1:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("temporary failure".encode("utf-8"))
            return

        status, content_type, body = _RuntimeRequestHandler.routes.get(path, (404, "text/plain; charset=utf-8", "not found"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class PolicyFetchRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/_tmp_policy_fetch_runtime") / f"case_{uuid4().hex}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

        self.server = _QuietThreadingHTTPServer(("127.0.0.1", 0), _RuntimeRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.addCleanup(lambda: self.server_thread.join(timeout=2))

        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        _RuntimeRequestHandler.counters = {}
        _RuntimeRequestHandler.routes = {
            "/rss.xml": (
                200,
                "application/rss+xml; charset=utf-8",
                f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
                <rss version=\"2.0\"><channel><title>Policies</title>
                  <item>
                    <title>RSS 政策 A</title>
                    <link>{self.base_url}/rss/policy-a</link>
                    <guid>rss-a</guid>
                    <pubDate>Mon, 01 Apr 2026 09:00:00 GMT</pubDate>
                    <description><![CDATA[<p>RSS 正文 A</p>]]></description>
                  </item>
                </channel></rss>""",
            ),
            "/retry/rss.xml": (
                200,
                "application/rss+xml; charset=utf-8",
                f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
                <rss version=\"2.0\"><channel><title>Policies</title>
                  <item>
                    <title>RSS 重试政策</title>
                    <link>{self.base_url}/rss/policy-retry</link>
                    <guid>rss-retry</guid>
                    <pubDate>2026-04-01 09:30:00</pubDate>
                    <description><![CDATA[<p>重试成功正文</p>]]></description>
                  </item>
                </channel></rss>""",
            ),
            "/api/policies": (
                200,
                "application/json; charset=utf-8",
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "json-a",
                                "title": "JSON 政策 A",
                                "content": "JSON 正文 A",
                                "url": f"{self.base_url}/api/policy-a",
                                "published_at": "2026-04-01 10:00:00"
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            ),
            "/html/index.html": (
                200,
                "text/html; charset=utf-8",
                f"""
                <html><body>
                  <a class=\"policy-link\" href=\"/html/detail-1.html\" data-date=\"2026-04-01 11:00:00\">HTML 政策 A</a>
                </body></html>
                """,
            ),
            "/html/detail-1.html": (
                200,
                "text/html; charset=utf-8",
                """
                <html><body>
                  <h1>HTML 政策 A</h1>
                  <time>2026-04-01 11:00:00</time>
                  <article><p>HTML 正文 A</p></article>
                </body></html>
                """,
            ),
        }

    def _write_source_config(self, payload: dict) -> Path:
        path = self.temp_dir / "policy_sources.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_three_source_kinds_run_and_repeat_without_duplicate_insert(self) -> None:
        config_path = self._write_source_config(
            {
                "sources": [
                    {
                        "source_id": "rss-source",
                        "name": "RSS 源",
                        "enabled": True,
                        "source_kind": "rss",
                        "schedule": "daily",
                        "base_url": f"{self.base_url}/rss.xml",
                        "options": {"feed_url": f"{self.base_url}/rss.xml"},
                    },
                    {
                        "source_id": "json-source",
                        "name": "JSON 源",
                        "enabled": True,
                        "source_kind": "json_api",
                        "base_url": f"{self.base_url}/api/policies",
                        "options": {
                            "api_url": f"{self.base_url}/api/policies",
                            "items_path": "items",
                            "field_mapping": {
                                "policy_id": "id",
                                "title": "title",
                                "content": "content",
                                "source_url": "url",
                                "published_at": "published_at"
                            }
                        }
                    },
                    {
                        "source_id": "html-source",
                        "name": "HTML 源",
                        "enabled": True,
                        "source_kind": "html_list_detail",
                        "base_url": f"{self.base_url}/html/index.html",
                        "options": {
                            "list_url": f"{self.base_url}/html/index.html",
                            "list_item_pattern": '<a class=\\"policy-link\\" href=\\"(?<url>[^\\"]+)\\" data-date=\\"(?<published_at>[^\\"]*)\\">(?<title>.*?)</a>',
                            "detail_title_pattern": '<h1>(?<value>.*?)</h1>',
                            "detail_published_at_pattern": '<time>(?<value>.*?)</time>',
                            "detail_content_pattern": '<article>(?<value>[\\s\\S]*?)</article>'
                        }
                    }
                ]
            }
        )
        repo_dir = self.temp_dir / "repository"
        config = load_app_config().merge(
            {
                "policy_source_enabled": True,
                "policy_source_registry_path": str(config_path),
                "policy_repository_dir": str(repo_dir),
            }
        )
        service = PolicyFetchService(config)

        self.assertEqual(service.get_registry().configured_source_count(enabled_only=True), 3)
        rss_result = service.run_collection_task(PolicyFetchTask(source_id="rss-source"), sync_repository=True)
        json_result = service.run_collection_task(PolicyFetchTask(source_id="json-source"), sync_repository=True)
        html_result = service.run_collection_task(PolicyFetchTask(source_id="html-source"), sync_repository=True)

        self.assertTrue(rss_result.ok)
        self.assertTrue(json_result.ok)
        self.assertTrue(html_result.ok)

        repository = service.get_repository()
        self.assertIsInstance(repository, SqlitePolicyRepository)
        self.assertEqual(repository.count_records(), 3)

        service.run_collection_task(PolicyFetchTask(source_id="rss-source"), sync_repository=True)
        service.run_collection_task(PolicyFetchTask(source_id="json-source"), sync_repository=True)
        service.run_collection_task(PolicyFetchTask(source_id="html-source"), sync_repository=True)
        self.assertEqual(repository.count_records(), 3)

    def test_retry_source_logs_retry_and_succeeds(self) -> None:
        config_path = self._write_source_config(
            {
                "sources": [
                    {
                        "source_id": "retry-rss",
                        "name": "重试 RSS",
                        "enabled": True,
                        "source_kind": "rss",
                        "base_url": f"{self.base_url}/retry/rss.xml",
                        "retry_times": 1,
                        "options": {"feed_url": f"{self.base_url}/retry/rss.xml"},
                    }
                ]
            }
        )
        config = load_app_config().merge(
            {
                "policy_source_enabled": True,
                "policy_source_registry_path": str(config_path),
                "policy_repository_dir": str(self.temp_dir / "retry_repo"),
            }
        )
        service = PolicyFetchService(config)

        result = service.run_collection_task(PolicyFetchTask(source_id="retry-rss"), sync_repository=True)

        self.assertTrue(result.ok)
        self.assertGreaterEqual(_RuntimeRequestHandler.counters.get("/retry/rss.xml", 0), 2)
        self.assertTrue(any(item.event_type == "request_retry" for item in result.log_entries))

    def test_executor_runs_daily_incremental_sources_once_per_day(self) -> None:
        config_path = self._write_source_config(
            {
                "sources": [
                    {
                        "source_id": "daily-rss",
                        "name": "每日 RSS",
                        "enabled": True,
                        "source_kind": "rss",
                        "schedule": "daily",
                        "base_url": f"{self.base_url}/rss.xml",
                        "options": {"feed_url": f"{self.base_url}/rss.xml"},
                    }
                ]
            }
        )
        config = load_app_config().merge(
            {
                "policy_source_enabled": True,
                "policy_source_registry_path": str(config_path),
                "policy_repository_dir": str(self.temp_dir / "executor_repo"),
            }
        )
        service = PolicyFetchService(config)
        executor = PolicyFetchExecutor(service, max_workers=1)
        self.addCleanup(executor.shutdown)

        task_ids = executor.run_due_sources(now=datetime(2026, 4, 1, 8, 0, 0))
        self.assertEqual(len(task_ids), 1)
        result = executor.wait_for_task(task_ids[0], timeout=5)
        self.assertTrue(result.ok)

        snapshot = executor.get_task_snapshot(task_ids[0])
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status, "completed")

        second_wave = executor.run_due_sources(now=datetime(2026, 4, 1, 9, 0, 0))
        self.assertEqual(second_wave, [])


if __name__ == "__main__":
    unittest.main()




