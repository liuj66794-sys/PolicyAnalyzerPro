from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .errors import PolicyFetchAdapterError, PolicyFetchValidationError
from .service import PolicySourceAdapter
from .types import (
    FetchLogEntry,
    PolicyFetchContext,
    PolicyFetchResult,
    PolicyRecord,
    PolicySourceDefinition,
    _normalize_text,
)


def create_policy_source_adapter(definition: PolicySourceDefinition) -> PolicySourceAdapter:
    normalized = definition.normalized()
    if normalized.source_kind == "rss":
        return RssPolicySourceAdapter(normalized)
    if normalized.source_kind == "json_api":
        return JsonApiPolicySourceAdapter(normalized)
    if normalized.source_kind == "html_list_detail":
        return HtmlListDetailPolicySourceAdapter(normalized)
    raise PolicyFetchValidationError(f"Unsupported policy source kind: {normalized.source_kind}")


class BaseConfiguredPolicySourceAdapter(PolicySourceAdapter):
    def __init__(self, definition: PolicySourceDefinition) -> None:
        self.definition = definition.normalized()
        self._logs: list[FetchLogEntry] = []

    def get_source_id(self) -> str:
        return self.definition.source_id

    def get_source_name(self) -> str:
        return self.definition.name

    def get_source_definition(self) -> PolicySourceDefinition | None:
        return self.definition

    def can_fetch(self) -> bool:
        return self.definition.enabled and bool(self._get_root_url())

    def fetch(
        self,
        incremental: bool = False,
        context: PolicyFetchContext | None = None,
    ) -> PolicyFetchResult:
        self._logs = []
        started_at = datetime.now()
        try:
            records = self._fetch_records(incremental=incremental, context=context)
            filtered = self._filter_incremental(records, incremental=incremental, context=context)
            self._log(
                "records_filtered",
                "ok",
                f"Incremental filter kept {len(filtered)} records.",
                document_count=len(filtered),
            )
            return PolicyFetchResult(
                ok=True,
                source_id=self.get_source_id(),
                status="completed",
                records=filtered,
                log_entries=list(self._logs),
                started_at=started_at,
                finished_at=datetime.now(),
            )
        except PolicyFetchAdapterError as exc:
            self._log("adapter_failed", "error", str(exc), error_type=type(exc).__name__)
            return PolicyFetchResult(
                ok=False,
                source_id=self.get_source_id(),
                status="failed",
                errors=[str(exc)],
                log_entries=list(self._logs),
                started_at=started_at,
                finished_at=datetime.now(),
            )

    def _fetch_records(
        self,
        *,
        incremental: bool,
        context: PolicyFetchContext | None,
    ) -> list[PolicyRecord]:
        raise NotImplementedError

    def _get_root_url(self) -> str:
        return self.definition.base_url or _normalize_text(self.definition.options.get("url"))

    def _filter_incremental(
        self,
        records: list[PolicyRecord],
        *,
        incremental: bool,
        context: PolicyFetchContext | None,
    ) -> list[PolicyRecord]:
        if not incremental or context is None:
            return [record.normalized() for record in records]

        state = dict(context.source_state or {})
        seen_urls = {str(item) for item in list(state.get("recent_urls", []))}
        seen_policy_ids = {str(item) for item in list(state.get("recent_policy_ids", []))}
        last_published_at = context.definition and context.source_state and state.get("last_published_at")
        last_published = None if last_published_at in (None, "") else _coerce_datetime_for_filter(last_published_at)
        filtered: list[PolicyRecord] = []

        for record in records:
            normalized = record.normalized()
            if normalized.source_url and normalized.source_url in seen_urls:
                continue
            if normalized.policy_id and normalized.policy_id in seen_policy_ids:
                continue
            published_at = normalized.publish_time
            if last_published is not None and published_at is not None and published_at <= last_published:
                continue
            filtered.append(normalized)
        return filtered

    def _request_text(
        self,
        url: str,
        *,
        context: PolicyFetchContext | None,
        expect_json: bool = False,
    ) -> str:
        timeout = context.request_timeout_sec if context is not None else self.definition.request_timeout_sec
        retry_times = context.retry_times if context is not None else self.definition.retry_times
        headers = {"User-Agent": "PolicyAnalyzerPro/Task3"}
        headers.update(self.definition.headers)
        headers.update({str(key): str(value) for key, value in dict(self.definition.options.get("headers", {})).items()})

        last_error: Exception | None = None
        for attempt in range(retry_times + 1):
            try:
                request = Request(url, headers=headers)
                with urlopen(request, timeout=timeout) as response:
                    payload = response.read()
                    encoding = response.headers.get_content_charset() or self.definition.encoding_hint or "utf-8"
                    return payload.decode(encoding, errors="ignore")
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < retry_times:
                    self._log(
                        "request_retry",
                        "warning",
                        f"Request failed, retrying: {url}",
                        error_type=type(exc).__name__,
                        retry_count=attempt + 1,
                        extra={"url": url, "expect_json": expect_json},
                    )
                    continue
                self._log(
                    "request_failed",
                    "error",
                    f"Request failed: {url}",
                    error_type=type(exc).__name__,
                    retry_count=attempt,
                    extra={"url": url, "expect_json": expect_json},
                )
        raise PolicyFetchAdapterError(str(last_error or "Unknown request failure"))

    def _load_json(self, url: str, *, context: PolicyFetchContext | None) -> Any:
        text = self._request_text(url, context=context, expect_json=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise PolicyFetchAdapterError(f"JSON decode failed: {url}") from exc

    def _strip_html(self, text: str) -> str:
        return re.sub(r"<[^>]+>", "", unescape(text or "")).strip()

    def _absolute_url(self, url: str) -> str:
        return urljoin(self._get_root_url(), url)

    def _extract_path(self, payload: Any, path: str, default: Any = "") -> Any:
        current = payload
        for part in [segment for segment in str(path or "").split(".") if segment]:
            if isinstance(current, dict):
                current = current.get(part, default)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (TypeError, ValueError, IndexError):
                    return default
            else:
                return default
        return current

    def _normalize_pattern(self, pattern: str) -> str:
        return str(pattern or "").replace("(?<", "(?P<")

    def _log(
        self,
        event_type: str,
        status: str,
        message: str,
        *,
        document_count: int = 0,
        error_type: str = "",
        retry_count: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._logs.append(
            FetchLogEntry(
                timestamp=datetime.now(),
                event_type=event_type,
                status=status,
                message=message,
                source_id=self.get_source_id(),
                source_name=self.get_source_name(),
                document_count=document_count,
                error_type=error_type,
                retry_count=retry_count,
                extra=dict(extra or {}),
            )
        )


class RssPolicySourceAdapter(BaseConfiguredPolicySourceAdapter):
    def _fetch_records(
        self,
        *,
        incremental: bool,
        context: PolicyFetchContext | None,
    ) -> list[PolicyRecord]:
        feed_url = _normalize_text(self.definition.options.get("feed_url")) or self.definition.base_url
        xml_text = self._request_text(feed_url, context=context)
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise PolicyFetchAdapterError(f"RSS parse failed: {feed_url}") from exc

        items = [element for element in root.iter() if element.tag.lower().endswith("item")]
        records: list[PolicyRecord] = []
        for item in items:
            title = self._find_xml_text(item, "title")
            link = self._find_xml_text(item, "link")
            description = self._find_xml_text(item, "description") or self._find_xml_text(item, "encoded")
            published_at = self._find_xml_text(item, "pubdate") or self._find_xml_text(item, "published")
            guid = self._find_xml_text(item, "guid")
            records.append(
                PolicyRecord(
                    policy_id=guid or link,
                    title=title,
                    content=self._strip_html(description),
                    source_name=self.get_source_name(),
                    source_url=self._absolute_url(link) if link else "",
                    published_at=published_at,
                    fetched_at=datetime.now(),
                    source_type="rss",
                    metadata={"feed_url": feed_url},
                    raw_published_at=published_at,
                )
            )
        self._log("rss_feed_loaded", "ok", f"RSS feed returned {len(records)} records.", document_count=len(records))
        return records

    def _find_xml_text(self, node: ET.Element, suffix: str) -> str:
        suffix_lower = suffix.lower()
        for child in node.iter():
            if child.tag.lower().endswith(suffix_lower):
                return _normalize_text(child.text)
        return ""


class JsonApiPolicySourceAdapter(BaseConfiguredPolicySourceAdapter):
    def _fetch_records(
        self,
        *,
        incremental: bool,
        context: PolicyFetchContext | None,
    ) -> list[PolicyRecord]:
        api_url = _normalize_text(self.definition.options.get("api_url")) or self.definition.base_url
        payload = self._load_json(api_url, context=context)
        items_path = _normalize_text(self.definition.options.get("items_path")) or "items"
        items = self._extract_path(payload, items_path, default=[])
        if not isinstance(items, list):
            raise PolicyFetchAdapterError(f"JSON list path is invalid: {items_path}")

        field_mapping = dict(self.definition.options.get("field_mapping") or {})
        records: list[PolicyRecord] = []
        for item in items:
            title = self._extract_path(item, field_mapping.get("title", "title"), default="")
            content = self._extract_path(item, field_mapping.get("content", "content"), default="")
            url = self._extract_path(item, field_mapping.get("source_url", "url"), default="")
            published_at = self._extract_path(item, field_mapping.get("published_at", "published_at"), default="")
            policy_id = self._extract_path(item, field_mapping.get("policy_id", "id"), default="")
            records.append(
                PolicyRecord(
                    policy_id=_normalize_text(policy_id) or _normalize_text(url),
                    title=_normalize_text(title),
                    content=_normalize_text(content),
                    source_name=self.get_source_name(),
                    source_url=self._absolute_url(_normalize_text(url)) if _normalize_text(url) else "",
                    published_at=_normalize_text(published_at),
                    fetched_at=datetime.now(),
                    source_type="json_api",
                    metadata={"api_url": api_url, "raw_item": item},
                    raw_published_at=_normalize_text(published_at),
                )
            )
        self._log("json_api_loaded", "ok", f"JSON source returned {len(records)} records.", document_count=len(records))
        return records


class HtmlListDetailPolicySourceAdapter(BaseConfiguredPolicySourceAdapter):
    def _fetch_records(
        self,
        *,
        incremental: bool,
        context: PolicyFetchContext | None,
    ) -> list[PolicyRecord]:
        list_url = _normalize_text(self.definition.options.get("list_url")) or self.definition.base_url
        list_html = self._request_text(list_url, context=context)
        list_pattern = _normalize_text(self.definition.options.get("list_item_pattern"))
        if not list_pattern:
            raise PolicyFetchAdapterError("HTML source is missing list_item_pattern.")

        normalized_list_pattern = self._normalize_pattern(list_pattern)
        matches = list(re.finditer(normalized_list_pattern, list_html, flags=re.S | re.M))
        detail_content_pattern = _normalize_text(self.definition.options.get("detail_content_pattern"))
        detail_title_pattern = _normalize_text(self.definition.options.get("detail_title_pattern"))
        detail_published_pattern = _normalize_text(self.definition.options.get("detail_published_at_pattern"))
        records: list[PolicyRecord] = []
        for match in matches:
            groups = match.groupdict()
            title = _normalize_text(groups.get("title"))
            detail_url = self._absolute_url(_normalize_text(groups.get("url")))
            published_at = _normalize_text(groups.get("published_at"))
            if not detail_url:
                continue
            detail_html = self._request_text(detail_url, context=context)
            content = self._extract_with_pattern(detail_html, detail_content_pattern)
            detail_title = self._extract_with_pattern(detail_html, detail_title_pattern)
            detail_published_at = self._extract_with_pattern(detail_html, detail_published_pattern)
            records.append(
                PolicyRecord(
                    policy_id=detail_url,
                    title=detail_title or title,
                    content=self._strip_html(content),
                    source_name=self.get_source_name(),
                    source_url=detail_url,
                    published_at=detail_published_at or published_at,
                    fetched_at=datetime.now(),
                    source_type="html_list_detail",
                    metadata={"list_url": list_url},
                    raw_published_at=detail_published_at or published_at,
                )
            )
        self._log("html_list_loaded", "ok", f"HTML list returned {len(records)} records.", document_count=len(records))
        return records

    def _extract_with_pattern(self, text: str, pattern: str) -> str:
        if not pattern:
            return ""
        normalized_pattern = self._normalize_pattern(pattern)
        match = re.search(normalized_pattern, text, flags=re.S | re.M)
        if not match:
            return ""
        groups = match.groupdict()
        if "value" in groups:
            return _normalize_text(groups["value"])
        return _normalize_text(match.group(1) if match.groups() else match.group(0))


def _coerce_datetime_for_filter(value: Any) -> datetime | None:
    from .types import _coerce_datetime

    return _coerce_datetime(value)
