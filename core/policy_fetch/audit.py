from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.config import get_project_root

from .types import FetchLogEntry

POLICY_FETCH_AUDIT_FILE_NAME = "policy-fetch-events.jsonl"


def get_policy_fetch_audit_dir() -> Path:
    override = os.environ.get("POLICY_FETCH_AUDIT_DIR", "").strip()
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    candidates.append(get_project_root() / "tmp" / "audit")

    if hasattr(os, "name") and os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            candidates.append(Path(local_appdata) / "PolicyAnalyzerPro" / "audit")

    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root
        except OSError:
            continue
    raise OSError("Unable to prepare policy fetch audit directory.")


def get_policy_fetch_audit_log_path() -> Path:
    return get_policy_fetch_audit_dir() / POLICY_FETCH_AUDIT_FILE_NAME


def build_policy_fetch_audit_record(
    event: FetchLogEntry,
    *,
    result_status: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = event.to_dict()
    payload["domain"] = "policy_fetch"
    if result_status:
        payload["result_status"] = str(result_status)
    if extra:
        payload.update({str(key): value for key, value in extra.items()})
    return payload


def append_policy_fetch_audit_event(
    event: FetchLogEntry,
    *,
    result_status: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    path = get_policy_fetch_audit_log_path()
    record = build_policy_fetch_audit_record(event, result_status=result_status, extra=extra)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
