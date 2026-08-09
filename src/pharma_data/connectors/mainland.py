import mimetypes
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from pharma_data.config import get_settings
from pharma_data.connectors.base import FetchResult, SourceAdapter
from pharma_data.connectors.http_client import authoritative_get
from pharma_data.contracts import (
    AccessClass,
    DocumentType,
    LicenseStatus,
    SourceRecordEnvelope,
)
from pharma_data.contracts.models import SourceRecordPage


class MainlandCatalogAdapter(SourceAdapter):
    """读取来源目录中经过人工复核的中国大陆官方样本。

    该适配器不把网页内部接口伪装成公开 API。它只下载目录中明确登记的
    官方页面或文件，并在请求前后校验域名，防止重定向到未登记站点。
    """

    adapter_name = "MainlandCatalogAdapter"
    default_license_status = LicenseStatus.PUBLIC_ACCESS

    def __init__(self, source: dict[str, Any]):
        if source.get("jurisdiction") != "CN-MAINLAND":
            raise ValueError("MainlandCatalogAdapter 只接受中国大陆来源")
        self.source_config = dict(source)
        self.source_name = str(source["source_id"])
        self.authority_tier = str(source["authority_tier"])
        self.base_url = str(source["base_url"]) if source.get("base_url") else None
        self.terms_url = str(source["terms_url"]) if source.get("terms_url") else None
        self.allowed_domains = tuple(str(item).lower() for item in source["allowed_domains"])

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        records_payload = query.get("records") or self.source_config.get("sample_records") or []
        max_records = max(int(query.get("max_records", len(records_payload))), 0)
        records: list[SourceRecordEnvelope] = []
        for payload in records_payload[:max_records]:
            content_url = str(payload["content_url"])
            canonical_url = str(payload.get("canonical_url") or content_url)
            self._validate_url(content_url)
            self._validate_url(canonical_url)
            records.append(
                SourceRecordEnvelope(
                    source_name=self.source_name,
                    source_record_id=str(payload["source_record_id"]),
                    canonical_url=canonical_url,
                    title=str(payload["title"]),
                    published_at=self._parse_date(payload.get("published_at")),
                    content_urls=[content_url],
                    license_status=LicenseStatus(
                        payload.get("license_status", LicenseStatus.PUBLIC_ACCESS.value)
                    ),
                    access_class=AccessClass(
                        payload.get("access_class", AccessClass.TEAM_INTERNAL.value)
                    ),
                    document_type=DocumentType(
                        payload.get(
                            "document_type",
                            self.source_config.get("document_type", DocumentType.OTHER.value),
                        )
                    ),
                    raw_metadata={
                        "_content_url": content_url,
                        "authority": self.source_config["authority"],
                        "jurisdiction": "CN-MAINLAND",
                        "redistribution_policy": self.source_config.get(
                            "redistribution_policy", "metadata_and_derived_only"
                        ),
                        **dict(payload.get("metadata", {})),
                    },
                )
            )
        return SourceRecordPage(records=records, next_cursor=None)

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        content_url = str(record.raw_metadata["_content_url"])
        self._validate_url(content_url)
        response = authoritative_get(
            content_url,
            headers={
                "User-Agent": get_settings().http_user_agent,
                "Accept": "application/pdf,text/html,application/xhtml+xml,application/json,*/*",
            },
            timeout=60,
        )
        self._validate_url(str(response.url))
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if not media_type:
            media_type = mimetypes.guess_type(urlparse(str(response.url)).path)[0]
        return [
            FetchResult(
                content=response.content,
                media_type=media_type or "application/octet-stream",
                original_url=str(response.url),
                metadata={
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "official_source_id": self.source_name,
                    "jurisdiction": "CN-MAINLAND",
                },
            )
        ]

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise ValueError(f"大陆官方样本必须使用 HTTPS: {url}")
        if not any(
            host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains
        ):
            raise ValueError(f"URL 域名不在来源 {self.source_name} 的白名单中: {host}")

    @staticmethod
    def _parse_date(value: Any) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
