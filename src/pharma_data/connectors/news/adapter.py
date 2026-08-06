from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx

from pharma_data.connectors.base import ManifestSourceAdapter
from pharma_data.contracts import (
    AccessClass,
    DocumentType,
    LicenseStatus,
    SourceRecordEnvelope,
)
from pharma_data.contracts.models import SourceRecordPage


class NewsAdapter(ManifestSourceAdapter):
    source_name = "official_news"
    adapter_name = "NewsAdapter"
    authority_tier = "A2"
    document_type = DocumentType.NEWS
    default_license_status = LicenseStatus.PUBLIC
    allowed_media_types = {"text/html", "application/xhtml+xml", "application/json"}

    @staticmethod
    def _published_at(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        rss_url = query.get("rss_url")
        if not rss_url:
            return super().discover(query, cursor)
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            response = client.get(rss_url)
            response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        records: list[SourceRecordEnvelope] = []
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or link).strip()
            title = (item.findtext("title") or "").strip()
            pub_date = item.findtext("pubDate")
            if not guid or not title or not link:
                continue
            records.append(
                SourceRecordEnvelope(
                    source_name=self.source_name,
                    source_record_id=guid,
                    canonical_url=link,
                    title=title,
                    published_at=self._published_at(pub_date),
                    content_urls=[link],
                    license_status=LicenseStatus.PUBLIC,
                    access_class=AccessClass.PUBLIC,
                    document_type=DocumentType.NEWS,
                    raw_metadata={"_content_url": link, "rss_url": rss_url},
                )
            )
        return SourceRecordPage(records=records)
