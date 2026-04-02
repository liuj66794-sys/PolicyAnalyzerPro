from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from core.config import get_project_root

from .types import PolicyRecord


def get_default_policy_repository_dir() -> Path:
    root = get_project_root() / "data" / "policy_repository"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_default_policy_repository_path() -> Path:
    return get_default_policy_repository_dir() / "policies.sqlite3"


class SqlitePolicyRepository:
    """Local policy repository for task3 fetch ingestion and incremental state."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_default_policy_repository_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_url TEXT DEFAULT '',
                    published_at TEXT DEFAULT '',
                    fetched_at TEXT DEFAULT '',
                    content_hash TEXT DEFAULT '',
                    source_type TEXT DEFAULT 'website',
                    metadata_json TEXT DEFAULT '{}',
                    raw_title TEXT DEFAULT '',
                    raw_published_at TEXT DEFAULT '',
                    attachments_json TEXT DEFAULT '[]',
                    summary TEXT DEFAULT '',
                    keywords_json TEXT DEFAULT '[]',
                    region TEXT DEFAULT '',
                    department TEXT DEFAULT '',
                    document_no TEXT DEFAULT '',
                    version INTEGER DEFAULT 1,
                    updated_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_policies_source_url ON policies(source_url);
                CREATE INDEX IF NOT EXISTS idx_policies_content_hash ON policies(content_hash);
                CREATE INDEX IF NOT EXISTS idx_policies_title_published_at ON policies(title, published_at);
                CREATE TABLE IF NOT EXISTS source_state (
                    source_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def upsert_records(self, records: list[PolicyRecord]) -> int:
        changed_count = 0
        with self._connection() as conn:
            for record in records:
                normalized = record.normalized()
                changed_count += self._upsert_record(conn, normalized)
        return changed_count

    def _upsert_record(self, conn: sqlite3.Connection, record: PolicyRecord) -> int:
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = self._find_existing(conn, record)
        payload = self._serialize_record(record)

        if existing is None:
            conn.execute(
                """
                INSERT INTO policies (
                    policy_id, title, content, source_name, source_url, published_at,
                    fetched_at, content_hash, source_type, metadata_json, raw_title,
                    raw_published_at, attachments_json, summary, keywords_json, region,
                    department, document_no, version, updated_at, created_at, modified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["policy_id"],
                    payload["title"],
                    payload["content"],
                    payload["source_name"],
                    payload["source_url"],
                    payload["published_at"],
                    payload["fetched_at"],
                    payload["content_hash"],
                    payload["source_type"],
                    payload["metadata_json"],
                    payload["raw_title"],
                    payload["raw_published_at"],
                    payload["attachments_json"],
                    payload["summary"],
                    payload["keywords_json"],
                    payload["region"],
                    payload["department"],
                    payload["document_no"],
                    int(payload["version"]),
                    payload["updated_at"],
                    now_text,
                    now_text,
                ),
            )
            return 1

        if existing["content_hash"] == payload["content_hash"]:
            conn.execute(
                "UPDATE policies SET fetched_at = ?, modified_at = ? WHERE id = ?",
                (payload["fetched_at"], now_text, existing["id"]),
            )
            return 0

        next_version = int(existing["version"] or 1) + 1
        conn.execute(
            """
            UPDATE policies SET
                title = ?,
                content = ?,
                source_name = ?,
                source_url = ?,
                published_at = ?,
                fetched_at = ?,
                content_hash = ?,
                source_type = ?,
                metadata_json = ?,
                raw_title = ?,
                raw_published_at = ?,
                attachments_json = ?,
                summary = ?,
                keywords_json = ?,
                region = ?,
                department = ?,
                document_no = ?,
                version = ?,
                updated_at = ?,
                modified_at = ?
            WHERE id = ?
            """,
            (
                payload["title"],
                payload["content"],
                payload["source_name"],
                payload["source_url"],
                payload["published_at"],
                payload["fetched_at"],
                payload["content_hash"],
                payload["source_type"],
                payload["metadata_json"],
                payload["raw_title"],
                payload["raw_published_at"],
                payload["attachments_json"],
                payload["summary"],
                payload["keywords_json"],
                payload["region"],
                payload["department"],
                payload["document_no"],
                next_version,
                payload["updated_at"],
                now_text,
                existing["id"],
            ),
        )
        return 1

    def _find_existing(self, conn: sqlite3.Connection, record: PolicyRecord) -> sqlite3.Row | None:
        queries: list[tuple[str, tuple[Any, ...]]] = []
        if record.policy_id:
            queries.append(("SELECT * FROM policies WHERE policy_id = ? LIMIT 1", (record.policy_id,)))
        if record.source_url:
            queries.append(("SELECT * FROM policies WHERE source_url = ? LIMIT 1", (record.source_url,)))
        if record.title and record.publish_time is not None:
            queries.append(
                (
                    "SELECT * FROM policies WHERE title = ? AND published_at = ? LIMIT 1",
                    (record.title, record.publish_time.strftime("%Y-%m-%d %H:%M:%S")),
                )
            )
        if record.content_hash:
            queries.append(("SELECT * FROM policies WHERE content_hash = ? LIMIT 1", (record.content_hash,)))

        for sql, params in queries:
            row = conn.execute(sql, params).fetchone()
            if row is not None:
                return row
        return None

    def list_records(self, *, limit: int = 100, source_name: str = "") -> list[PolicyRecord]:
        sql = "SELECT * FROM policies"
        params: list[Any] = []
        if source_name:
            sql += " WHERE source_name = ?"
            params.append(source_name)
        sql += " ORDER BY published_at DESC, modified_at DESC LIMIT ?"
        params.append(int(limit))

        with self._connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._deserialize_row(row) for row in rows]

    def count_records(self) -> int:
        with self._connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM policies").fetchone()
        return int(row["count"] if row is not None else 0)

    def get_source_state(self, source_id: str) -> dict[str, Any]:
        normalized = str(source_id or "").strip()
        if not normalized:
            return {}
        with self._connection() as conn:
            row = conn.execute(
                "SELECT state_json FROM source_state WHERE source_id = ? LIMIT 1",
                (normalized,),
            ).fetchone()
        if row is None:
            return {}
        try:
            return dict(json.loads(row["state_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def save_source_state(self, source_id: str, state: dict[str, Any]) -> None:
        normalized = str(source_id or "").strip()
        if not normalized:
            return
        payload = json.dumps(dict(state or {}), ensure_ascii=False)
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO source_state (source_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (normalized, payload, now_text),
            )

    def _serialize_record(self, record: PolicyRecord) -> dict[str, str]:
        normalized = record.normalized()
        return {
            "policy_id": normalized.policy_id,
            "title": normalized.title,
            "content": normalized.content,
            "source_name": normalized.source_name,
            "source_url": normalized.source_url,
            "published_at": normalized.publish_time.strftime("%Y-%m-%d %H:%M:%S") if normalized.publish_time else "",
            "fetched_at": normalized.fetched_at.strftime("%Y-%m-%d %H:%M:%S") if isinstance(normalized.fetched_at, datetime) else "",
            "content_hash": normalized.content_hash,
            "source_type": normalized.source_type,
            "metadata_json": json.dumps(normalized.metadata, ensure_ascii=False),
            "raw_title": normalized.raw_title,
            "raw_published_at": normalized.raw_published_at,
            "attachments_json": json.dumps(normalized.attachments, ensure_ascii=False),
            "summary": normalized.summary,
            "keywords_json": json.dumps(normalized.keywords, ensure_ascii=False),
            "region": normalized.region,
            "department": normalized.department,
            "document_no": normalized.document_no,
            "version": normalized.version,
            "updated_at": normalized.updated_at.strftime("%Y-%m-%d %H:%M:%S") if isinstance(normalized.updated_at, datetime) else "",
        }

    def _deserialize_row(self, row: sqlite3.Row) -> PolicyRecord:
        return PolicyRecord(
            policy_id=row["policy_id"],
            title=row["title"],
            content=row["content"],
            source_name=row["source_name"],
            source_url=row["source_url"],
            published_at=row["published_at"] or None,
            fetched_at=row["fetched_at"] or None,
            content_hash=row["content_hash"],
            source_type=row["source_type"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            raw_title=row["raw_title"],
            raw_published_at=row["raw_published_at"],
            attachments=json.loads(row["attachments_json"] or "[]"),
            summary=row["summary"],
            keywords=json.loads(row["keywords_json"] or "[]"),
            region=row["region"],
            department=row["department"],
            document_no=row["document_no"],
            version=str(row["version"] or "1"),
            updated_at=row["updated_at"] or None,
        ).normalized()
