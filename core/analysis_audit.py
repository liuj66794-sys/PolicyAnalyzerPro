from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core.analysis_errors import coerce_analysis_error_info
from core.config import get_project_root


def get_analysis_audit_dir() -> Path:
    override = os.environ.get("POLICY_ANALYZER_AUDIT_DIR", "").strip()
    if override:
        root = Path(override)
    elif hasattr(os, "name") and os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            root = Path(local_appdata) / "PolicyAnalyzerPro" / "audit"
        else:
            root = get_project_root() / "tmp" / "audit"
    else:
        root = get_project_root() / "tmp" / "audit"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_analysis_audit_log_path() -> Path:
    return get_analysis_audit_dir() / "analysis-events.jsonl"


def build_analysis_audit_record(
    event_type: str,
    *,
    result: dict[str, Any] | None = None,
    error: Any | None = None,
    export_format: str = "",
    export_path: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": str(event_type or "unknown").strip() or "unknown",
    }

    if result is not None:
        payload = dict(result)
        record.update(
            {
                "task_mode": str(payload.get("mode", "") or ""),
                "analysis_status": str(payload.get("analysis_status", "ok") or "ok"),
                "requested_analysis_mode": str(payload.get("requested_analysis_mode", "") or ""),
                "executed_analysis_mode": str(payload.get("executed_analysis_mode", "") or ""),
                "analysis_route_status": str(payload.get("analysis_route_status", "") or ""),
                "analysis_route_message": str(payload.get("analysis_route_message", "") or ""),
            }
        )
        if payload.get("analysis_error"):
            info = coerce_analysis_error_info(payload.get("analysis_error"))
            record.update(
                {
                    "analysis_error_mode": info.mode,
                    "analysis_error_stage": info.stage,
                    "analysis_error_title": info.title,
                    "analysis_error_message": info.user_message,
                    "analysis_error_detail": info.detail,
                    "analysis_error_category": info.category,
                }
            )

    if error is not None:
        info = coerce_analysis_error_info(error)
        record.update(
            {
                "analysis_status": "error",
                "task_mode": info.task_mode,
                "requested_analysis_mode": info.requested_mode,
                "executed_analysis_mode": info.executed_mode,
                "analysis_error_mode": info.mode,
                "analysis_error_stage": info.stage,
                "analysis_error_title": info.title,
                "analysis_error_message": info.user_message,
                "analysis_error_detail": info.detail,
                "analysis_error_category": info.category,
            }
        )

    if export_format:
        record["export_format"] = str(export_format)
    if export_path:
        record["export_path"] = str(export_path)
    if extra:
        record.update({str(key): value for key, value in extra.items()})

    return record


def append_analysis_audit_event(
    event_type: str,
    *,
    result: dict[str, Any] | None = None,
    error: Any | None = None,
    export_format: str = "",
    export_path: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    path = get_analysis_audit_log_path()
    record = build_analysis_audit_record(
        event_type,
        result=result,
        error=error,
        export_format=export_format,
        export_path=export_path,
        extra=extra,
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
