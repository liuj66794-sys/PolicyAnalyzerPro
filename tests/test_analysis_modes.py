from __future__ import annotations

import json
import shutil
import uuid
import unittest
from pathlib import Path

from core.analysis_router import (
    ANALYSIS_MODE_HYBRID,
    ANALYSIS_MODE_OFFLINE,
    ANALYSIS_MODE_ONLINE,
    build_analysis_route_text,
    build_capability_snapshot,
    resolve_analysis_route,
)
from core.config import AppConfig, load_app_config
from core.hybrid_pipeline import HybridPipelineService
from core.online_llm import OnlineLLMService
from core.policy_fetch import PolicyFetchService


class AnalysisModeTests(unittest.TestCase):
    def _create_temp_dir(self) -> Path:
        temp_dir = Path("tests/_tmp_analysis_modes") / f"case_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(temp_dir, ignore_errors=True))
        return temp_dir

    def test_legacy_config_keeps_new_defaults(self) -> None:
        temp_dir = self._create_temp_dir()
        config_path = temp_dir / "legacy_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "app_name": "PolicyAnalyzerPro",
                    "model_dir": "models/hfl/chinese-roberta-wwm-ext",
                    "font_path": "assets/fonts/simhei.ttf",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        config = AppConfig.from_json(config_path)
        self.assertEqual(config.analysis_mode, ANALYSIS_MODE_OFFLINE)
        self.assertFalse(config.policy_source_enabled)
        self.assertEqual(config.llm_provider, "")
        self.assertFalse(config.cloud_fallback_enabled)

    def test_invalid_analysis_mode_falls_back_to_offline(self) -> None:
        config = load_app_config().merge({"analysis_mode": "invalid-mode"})
        self.assertEqual(config.analysis_mode, ANALYSIS_MODE_OFFLINE)

    def test_router_keeps_offline_by_default(self) -> None:
        config = load_app_config()
        decision = resolve_analysis_route(config.analysis_mode, config=config)
        self.assertEqual(decision.requested_mode, ANALYSIS_MODE_OFFLINE)
        self.assertEqual(decision.executed_mode, ANALYSIS_MODE_OFFLINE)
        self.assertFalse(decision.degraded)

    def test_router_degrades_online_to_offline_when_unavailable(self) -> None:
        config = load_app_config().merge({"analysis_mode": ANALYSIS_MODE_ONLINE})
        decision = resolve_analysis_route(ANALYSIS_MODE_ONLINE, config=config)
        self.assertEqual(decision.requested_mode, ANALYSIS_MODE_ONLINE)
        self.assertEqual(decision.executed_mode, ANALYSIS_MODE_OFFLINE)
        self.assertTrue(decision.degraded)
        self.assertIn("\u56de\u9000", decision.message)

    def test_router_degrades_hybrid_to_offline_when_unavailable(self) -> None:
        config = load_app_config().merge({"analysis_mode": ANALYSIS_MODE_HYBRID})
        decision = resolve_analysis_route(ANALYSIS_MODE_HYBRID, config=config)
        self.assertEqual(decision.requested_mode, ANALYSIS_MODE_HYBRID)
        self.assertEqual(decision.executed_mode, ANALYSIS_MODE_OFFLINE)
        self.assertTrue(decision.degraded)
        self.assertIn("\u56de\u9000", decision.message)

    def test_route_summary_text_mentions_requested_and_executed_modes(self) -> None:
        text = build_analysis_route_text(
            {
                "requested_analysis_mode": ANALYSIS_MODE_ONLINE,
                "executed_analysis_mode": ANALYSIS_MODE_OFFLINE,
            }
        )
        self.assertIn("\u5728\u7ebf\u5206\u6790", text)
        self.assertIn("\u79bb\u7ebf\u5206\u6790", text)

    def test_capability_snapshot_and_new_modules_initialize(self) -> None:
        config = load_app_config()
        snapshot = build_capability_snapshot(config)
        self.assertFalse(snapshot.online_ready)
        self.assertFalse(snapshot.hybrid_ready)

        online_status = OnlineLLMService(config).get_status()
        hybrid_status = HybridPipelineService(config).get_status()
        policy_status = PolicyFetchService(config).get_status()

        self.assertEqual(online_status.state, "disabled")
        self.assertEqual(hybrid_status.state, "disabled")
        self.assertEqual(policy_status.state, "disabled")


if __name__ == "__main__":
    unittest.main()
