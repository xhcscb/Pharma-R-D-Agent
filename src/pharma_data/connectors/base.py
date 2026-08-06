import csv
import json
import mimetypes
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from pharma_data.contracts import (
    AccessClass,
    DocumentType,
    LicenseStatus,
    SourceRecordEnvelope,
)
from pharma_data.contracts.models import SourceCheckpoint, SourceRecordPage


@dataclass(frozen=True)
class FetchResult:
    content: bytes
    media_type: str
    original_url: str | None
    metadata: dict[str, Any]


class SourceAdapter(ABC):
    source_name: str
    adapter_name: str
    authority_tier: str
    base_url: str | None = None
    terms_url: str | None = None
    default_license_status: LicenseStatus = LicenseStatus.UNKNOWN

    @abstractmethod
    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        raise NotImplementedError

    def checkpoint(self, cursor: str | None = None) -> SourceCheckpoint:
        return SourceCheckpoint(source_name=self.source_name, cursor=cursor)


class ManifestSourceAdapter(SourceAdapter):
    document_type: DocumentType
    allowed_media_types: set[str] | None = None

    def __init__(self, manifest_path: str | Path | None = None):
        self.manifest_path = Path(manifest_path) if manifest_path else None

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        path = Path(query.get("manifest_path") or self.manifest_path or "")
        if not path.is_file():
            raise FileNotFoundError(f"Manifest not found: {path}")
        rows = self._read_rows(path)
        records = [self._row_to_record(row, path.parent) for row in rows]
        return SourceRecordPage(records=records, next_cursor=None)

    def _read_rows(self, path: Path) -> list[dict[str, Any]]:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                return list(csv.DictReader(stream))
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            with path.open("r", encoding="utf-8") as stream:
                return [json.loads(line) for line in stream if line.strip()]
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else payload["records"]
        raise ValueError("Manifest must be CSV, JSON, or JSONL")

    def _row_to_record(self, row: dict[str, Any], base_dir: Path) -> SourceRecordEnvelope:
        record_id = str(row.get("source_record_id") or row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not record_id or not title:
            raise ValueError("Each manifest row requires source_record_id and title")
        license_status = LicenseStatus(
            row.get("license_status") or self.default_license_status.value
        )
        access_default = (
            AccessClass.PUBLIC
            if license_status == LicenseStatus.PUBLIC
            else AccessClass.TEAM_INTERNAL
        )
        access_class = AccessClass(row.get("access_class") or access_default.value)
        local_path = row.get("local_path")
        if license_status != LicenseStatus.PUBLIC and access_class == AccessClass.PUBLIC:
            raise ValueError("Non-public content cannot use public access_class")
        if local_path and not Path(local_path).is_absolute():
            local_path = str((base_dir / local_path).resolve())
        raw_metadata = self._metadata(row)
        raw_metadata["_local_path"] = local_path
        raw_metadata["_content_url"] = row.get("content_url")
        return SourceRecordEnvelope(
            source_name=self.source_name,
            source_record_id=record_id,
            canonical_url=row.get("canonical_url") or row.get("content_url") or None,
            title=title,
            published_at=self._date(row.get("published_at")),
            content_urls=[row["content_url"]] if row.get("content_url") else [],
            license_status=license_status,
            access_class=access_class,
            document_type=DocumentType(row.get("document_type") or self.document_type.value),
            raw_metadata=raw_metadata,
        )

    def _metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata_json")
        if isinstance(metadata, str) and metadata.strip():
            parsed = json.loads(metadata)
        elif isinstance(metadata, dict):
            parsed = metadata
        else:
            parsed = {}
        excluded = {
            "source_record_id",
            "id",
            "title",
            "canonical_url",
            "content_url",
            "local_path",
            "license_status",
            "access_class",
            "document_type",
            "published_at",
            "metadata_json",
        }
        parsed.update({key: value for key, value in row.items() if key not in excluded and value})
        return parsed

    @staticmethod
    def _date(value: Any) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        local_path = record.raw_metadata.get("_local_path")
        content_url = record.raw_metadata.get("_content_url")
        if local_path:
            path = Path(local_path)
            if not path.is_file():
                raise FileNotFoundError(path)
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self._check_media_type(media_type)
            return [
                FetchResult(
                    content=path.read_bytes(),
                    media_type=media_type,
                    original_url=content_url,
                    metadata={"filename": path.name},
                )
            ]
        if content_url:
            with httpx.Client(follow_redirects=True, timeout=60) as client:
                response = client.get(content_url)
                response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";")[0]
            media_type = media_type or mimetypes.guess_type(content_url)[0]
            media_type = media_type or "application/octet-stream"
            self._check_media_type(media_type)
            return [
                FetchResult(
                    content=response.content,
                    media_type=media_type,
                    original_url=content_url,
                    metadata={
                        "etag": response.headers.get("etag"),
                        "last_modified": response.headers.get("last-modified"),
                    },
                )
            ]
        raise ValueError(f"Record {record.source_record_id} has no local_path or content_url")

    def _check_media_type(self, media_type: str) -> None:
        if self.allowed_media_types and media_type not in self.allowed_media_types:
            raise ValueError(f"Unsupported media type for {self.source_name}: {media_type}")
