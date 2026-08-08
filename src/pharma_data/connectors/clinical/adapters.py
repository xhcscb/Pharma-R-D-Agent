import json
from datetime import datetime
from typing import Any

from pharma_data.config import get_settings
from pharma_data.connectors.base import FetchResult, ManifestSourceAdapter, SourceAdapter
from pharma_data.connectors.http_client import authoritative_get
from pharma_data.contracts import (
    AccessClass,
    DocumentType,
    LicenseStatus,
    SourceRecordEnvelope,
)
from pharma_data.contracts.models import SourceRecordPage


class ClinicalTrialsGovAdapter(SourceAdapter):
    source_name = "clinicaltrials.gov"
    adapter_name = "ClinicalTrialsGovAdapter"
    authority_tier = "A1"
    base_url = "https://clinicaltrials.gov"
    terms_url = "https://clinicaltrials.gov/about-site/terms-conditions"
    default_license_status = LicenseStatus.PUBLIC

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        settings = get_settings()
        params: dict[str, Any] = {
            "pageSize": min(int(query.get("page_size", 100)), 1000),
            "format": "json",
        }
        condition = query.get("condition")
        intervention = query.get("intervention")
        if condition:
            params["query.cond"] = condition
        if intervention:
            params["query.intr"] = intervention
        if query.get("overall_status"):
            params["filter.overallStatus"] = query["overall_status"]
        if cursor:
            params["pageToken"] = cursor
        response = authoritative_get(
            f"{settings.clinicaltrials_base_url.rstrip('/')}/studies",
            params=params,
            headers={"User-Agent": settings.http_user_agent, "Accept": "application/json"},
        )
        payload = response.json()

        records: list[SourceRecordEnvelope] = []
        for study in payload.get("studies", []):
            protocol = study.get("protocolSection", {})
            identity = protocol.get("identificationModule", {})
            nct_id = identity.get("nctId")
            title = identity.get("briefTitle") or identity.get("officialTitle") or nct_id
            if not nct_id:
                continue
            status_module = protocol.get("statusModule", {})
            updated = status_module.get("studyFirstPostDateStruct", {}).get("date")
            records.append(
                SourceRecordEnvelope(
                    source_name=self.source_name,
                    source_record_id=nct_id,
                    canonical_url=f"https://clinicaltrials.gov/study/{nct_id}",
                    title=title,
                    published_at=datetime.fromisoformat(updated) if updated else None,
                    content_urls=[],
                    license_status=LicenseStatus.PUBLIC,
                    access_class=AccessClass.PUBLIC,
                    document_type=DocumentType.CLINICAL_RECORD,
                    raw_metadata={"study": study, "query": query},
                )
            )
        return SourceRecordPage(
            records=records,
            next_cursor=payload.get("nextPageToken"),
        )

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        content = json.dumps(
            record.raw_metadata["study"], ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        return [
            FetchResult(
                content=content,
                media_type="application/json",
                original_url=str(record.canonical_url) if record.canonical_url else None,
                metadata={"nct_id": record.source_record_id},
            )
        ]


class ChinaDrugTrialsManifestAdapter(ManifestSourceAdapter):
    source_name = "chinadrugtrials"
    adapter_name = "ChinaDrugTrialsManifestAdapter"
    authority_tier = "A1"
    base_url = "https://www.chinadrugtrials.org.cn"
    document_type = DocumentType.CLINICAL_RECORD
    default_license_status = LicenseStatus.PUBLIC


class CdeManifestAdapter(ManifestSourceAdapter):
    source_name = "cde_nmpa"
    adapter_name = "CdeManifestAdapter"
    authority_tier = "A1"
    base_url = "https://www.cde.org.cn"
    document_type = DocumentType.REGULATORY
    default_license_status = LicenseStatus.PUBLIC


class ClinicalDocumentAdapter(ManifestSourceAdapter):
    source_name = "clinical_documents"
    adapter_name = "ClinicalDocumentAdapter"
    authority_tier = "B2"
    document_type = DocumentType.CLINICAL_DOCUMENT
    default_license_status = LicenseStatus.PUBLIC
    allowed_media_types = {"application/pdf", "text/html", "application/json"}
