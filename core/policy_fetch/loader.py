from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters import create_policy_source_adapter
from .service import PolicySourceRegistry
from .types import PolicySourceDefinition


POLICY_SOURCE_CONFIG_KEY = "sources"


def load_policy_source_definitions(path: str | Path) -> list[PolicySourceDefinition]:
    source_path = Path(path)
    if not source_path.exists():
        return []

    payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        raw_items = payload.get(POLICY_SOURCE_CONFIG_KEY, [])
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    definitions: list[PolicySourceDefinition] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        definitions.append(_build_definition(item))
    return definitions


def build_registry_from_definitions(
    definitions: list[PolicySourceDefinition],
    *,
    include_disabled: bool = True,
) -> PolicySourceRegistry:
    registry = PolicySourceRegistry()
    for definition in definitions:
        normalized = definition.normalized()
        registry.register_definition(normalized)
        if not include_disabled and not normalized.enabled:
            continue
        try:
            adapter = create_policy_source_adapter(normalized)
        except Exception:
            continue
        registry.register(adapter)
    return registry


def load_policy_source_registry(
    path: str | Path,
    *,
    include_disabled: bool = True,
) -> PolicySourceRegistry:
    definitions = load_policy_source_definitions(path)
    return build_registry_from_definitions(definitions, include_disabled=include_disabled)


def _build_definition(payload: dict[str, Any]) -> PolicySourceDefinition:
    return PolicySourceDefinition(
        source_id=str(payload.get("source_id", "")).strip(),
        name=str(payload.get("name", "")).strip(),
        base_url=str(payload.get("base_url", "")).strip(),
        enabled=bool(payload.get("enabled", True)),
        source_kind=str(payload.get("source_kind", payload.get("source_type", "html_list_detail"))).strip().lower(),
        schedule=str(payload.get("schedule", "manual")).strip().lower(),
        list_fetch_strategy=str(payload.get("list_fetch_strategy", "")).strip(),
        detail_fetch_strategy=str(payload.get("detail_fetch_strategy", "")).strip(),
        incremental_strategy=str(payload.get("incremental_strategy", "")).strip(),
        encoding_hint=str(payload.get("encoding_hint", "utf-8")).strip(),
        timezone_hint=str(payload.get("timezone_hint", "Asia/Shanghai")).strip(),
        rate_limit=str(payload.get("rate_limit", "")).strip(),
        notes=str(payload.get("notes", "")).strip(),
        request_timeout_sec=int(payload.get("request_timeout_sec", 20) or 20),
        retry_times=int(payload.get("retry_times", 2) or 0),
        headers={str(key): str(value) for key, value in dict(payload.get("headers", {})).items()},
        options=dict(payload.get("options", {})),
    )
