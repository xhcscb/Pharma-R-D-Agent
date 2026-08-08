from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

from pharma_data.config import get_settings
from pharma_data.connectors.base import ManifestSourceAdapter
from pharma_data.connectors.http_client import authoritative_get
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
        settings = get_settings()
        response = authoritative_get(
            rss_url,
            headers={
                "User-Agent": settings.http_user_agent,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            },
            timeout=30,
        )
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
        atom_namespace = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//atom:entry", atom_namespace):
            link_node = entry.find("atom:link", atom_namespace)
            link = (link_node.get("href") if link_node is not None else "") or ""
            guid = (
                entry.findtext("atom:id", default="", namespaces=atom_namespace) or link
            ).strip()
            title = (
                entry.findtext("atom:title", default="", namespaces=atom_namespace) or ""
            ).strip()
            published = entry.findtext("atom:published", namespaces=atom_namespace)
            updated = entry.findtext("atom:updated", namespaces=atom_namespace)
            if not guid or not title or not link:
                continue
            records.append(
                SourceRecordEnvelope(
                    source_name=self.source_name,
                    source_record_id=guid,
                    canonical_url=link,
                    title=title,
                    published_at=self._published_at(published or updated),
                    content_urls=[link],
                    license_status=LicenseStatus.PUBLIC,
                    access_class=AccessClass.PUBLIC,
                    document_type=DocumentType.NEWS,
                    raw_metadata={"_content_url": link, "rss_url": rss_url},
                )
            )
        max_records = query.get("max_records")
        if max_records is not None:
            records = records[: max(int(max_records), 0)]
        return SourceRecordPage(records=records)


class FdaNewsAdapter(NewsAdapter):
    source_name = "fda_news"
    adapter_name = "FdaNewsAdapter"
    authority_tier = "A1"
    base_url = "https://www.fda.gov"
    terms_url = "https://www.fda.gov/about-fda/about-website/website-policies"

    def __init__(self, rss_url: str):
        super().__init__()
        if not rss_url.startswith("https://www.fda.gov/") or not rss_url.endswith("rss.xml"):
            raise ValueError("FdaNewsAdapter 只接受 FDA 官方 HTTPS RSS 地址")
        self.rss_url = rss_url

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        return super().discover({**query, "rss_url": self.rss_url}, cursor)
