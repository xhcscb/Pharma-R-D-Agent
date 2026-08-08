import json
from datetime import datetime
from typing import Any

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

DEFAULT_FINANCIAL_FORMS = {"10-K", "10-Q", "20-F", "40-F", "6-K", "8-K"}


def normalize_cik(value: Any) -> str:
    digits = "".join(character for character in str(value) if character.isdigit())
    if not digits or len(digits) > 10:
        raise ValueError("CIK 必须是 1 至 10 位数字")
    return digits.zfill(10)


def _max_filed_date(payload: dict[str, Any]) -> datetime | None:
    dates: list[str] = []
    for taxonomy in payload.get("facts", {}).values():
        for concept in taxonomy.values():
            for facts in concept.get("units", {}).values():
                dates.extend(str(item.get("filed")) for item in facts if item.get("filed"))
    return datetime.fromisoformat(max(dates)) if dates else None


class SecAdapterBase(SourceAdapter):
    authority_tier = "A1"
    base_url = "https://data.sec.gov"
    terms_url = (
        "https://www.sec.gov/about/privacy-information/sec-web-site-privacy-and-security-policy"
    )
    default_license_status = LicenseStatus.PUBLIC

    def __init__(self, *, user_agent: str | None = None):
        self.user_agent = user_agent

    def _headers(self) -> dict[str, str]:
        settings = get_settings()
        identity = self.user_agent or settings.identified_sec_user_agent()
        if "@" not in identity:
            raise ValueError("SEC_USER_AGENT 必须包含可联系邮箱")
        return {
            "User-Agent": identity,
            "Accept": "application/json, text/html, application/xhtml+xml",
            "Accept-Encoding": "gzip, deflate",
        }


class SecEdgarFilingsAdapter(SecAdapterBase):
    """通过 SEC Submissions API 发现并抓取官方申报正文。"""

    source_name = "sec_edgar_filings"
    adapter_name = "SecEdgarFilingsAdapter"

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        settings = get_settings()
        cik = normalize_cik(query.get("cik"))
        response = authoritative_get(
            f"{settings.sec_data_base_url.rstrip('/')}/submissions/CIK{cik}.json",
            headers=self._headers(),
        )
        payload = response.json()
        recent = payload.get("filings", {}).get("recent", {})
        rows = self._rows(recent)

        requested_forms = query.get("forms") or DEFAULT_FINANCIAL_FORMS
        if isinstance(requested_forms, str):
            forms = {item.strip().upper() for item in requested_forms.split(",") if item.strip()}
        else:
            forms = {str(item).upper() for item in requested_forms}
        after_date = str(query.get("after_date") or "")
        rows = [
            row
            for row in rows
            if row.get("form", "").upper() in forms
            and (not after_date or str(row.get("filingDate") or "") >= after_date)
            and row.get("accessionNumber")
            and row.get("primaryDocument")
        ]
        offset = int(cursor or 0)
        page_size = min(max(int(query.get("page_size", 100)), 1), 1000)
        selected = rows[offset : offset + page_size]
        records = [self._record(cik, payload, row) for row in selected]
        next_offset = offset + len(selected)
        return SourceRecordPage(
            records=records,
            next_cursor=str(next_offset) if selected and next_offset < len(rows) else None,
        )

    @staticmethod
    def _rows(recent: dict[str, list[Any]]) -> list[dict[str, Any]]:
        if not recent:
            return []
        count = max((len(values) for values in recent.values()), default=0)
        return [
            {key: values[index] if index < len(values) else None for key, values in recent.items()}
            for index in range(count)
        ]

    def _record(
        self,
        cik: str,
        submissions: dict[str, Any],
        row: dict[str, Any],
    ) -> SourceRecordEnvelope:
        settings = get_settings()
        accession = str(row["accessionNumber"])
        accession_path = accession.replace("-", "")
        cik_path = str(int(cik))
        primary_document = str(row["primaryDocument"])
        url = (
            f"{settings.sec_archives_base_url.rstrip('/')}/"
            f"{cik_path}/{accession_path}/{primary_document}"
        )
        company = str(submissions.get("name") or f"CIK {cik}")
        form = str(row.get("form") or "filing")
        filing_date = str(row.get("filingDate") or "")
        return SourceRecordEnvelope(
            source_name=self.source_name,
            source_record_id=accession,
            canonical_url=url,
            title=f"{company} {form} {filing_date}".strip(),
            published_at=datetime.fromisoformat(filing_date) if filing_date else None,
            content_urls=[url],
            license_status=LicenseStatus.PUBLIC,
            access_class=AccessClass.PUBLIC,
            document_type=DocumentType.FINANCIAL_REPORT,
            raw_metadata={
                "_content_url": url,
                "cik": cik,
                "company_name": company,
                "tickers": submissions.get("tickers", []),
                "exchanges": submissions.get("exchanges", []),
                "filing": row,
            },
        )

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        url = str(record.content_urls[0])
        response = authoritative_get(url, headers=self._headers(), timeout=90)
        media_type = response.headers.get("content-type", "").split(";")[0]
        if media_type not in {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}:
            media_type = "text/html"
        return [
            FetchResult(
                content=response.content,
                media_type=media_type,
                original_url=url,
                metadata={
                    "accession_number": record.source_record_id,
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                },
            )
        ]


class SecCompanyFactsAdapter(SecAdapterBase):
    """通过 SEC CompanyFacts API 获取可比较的官方 XBRL 事实。"""

    source_name = "sec_companyfacts"
    adapter_name = "SecCompanyFactsAdapter"

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        if cursor:
            return SourceRecordPage(records=[])
        settings = get_settings()
        cik = normalize_cik(query.get("cik"))
        url = f"{settings.sec_data_base_url.rstrip('/')}/api/xbrl/companyfacts/CIK{cik}.json"
        response = authoritative_get(url, headers=self._headers())
        payload = response.json()
        entity_name = str(payload.get("entityName") or f"CIK {cik}")
        record = SourceRecordEnvelope(
            source_name=self.source_name,
            source_record_id=f"CIK{cik}:companyfacts",
            canonical_url=url,
            title=f"{entity_name} SEC CompanyFacts",
            published_at=_max_filed_date(payload),
            content_urls=[],
            license_status=LicenseStatus.PUBLIC,
            access_class=AccessClass.PUBLIC,
            document_type=DocumentType.FINANCIAL_REPORT,
            raw_metadata={"cik": cik, "companyfacts": payload, "query": query},
        )
        return SourceRecordPage(records=[record])

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        payload = record.raw_metadata["companyfacts"]
        return [
            FetchResult(
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                media_type="application/json",
                original_url=str(record.canonical_url) if record.canonical_url else None,
                metadata={"cik": record.raw_metadata["cik"], "format": "SEC CompanyFacts JSON"},
            )
        ]
