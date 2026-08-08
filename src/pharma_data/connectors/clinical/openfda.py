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
from pharma_data.utils.hashing import stable_hash

OPENFDA_DATASETS = {
    "label": "/drug/label.json",
    "drugsfda": "/drug/drugsfda.json",
    "enforcement": "/drug/enforcement.json",
    "shortages": "/drug/shortages.json",
}


class OpenFdaDrugAdapter(SourceAdapter):
    """接入 FDA 官方药品标签、审批、召回和短缺结构化记录。"""

    source_name = "openfda_drug"
    adapter_name = "OpenFdaDrugAdapter"
    authority_tier = "A1"
    base_url = "https://api.fda.gov"
    terms_url = "https://open.fda.gov/terms/"
    default_license_status = LicenseStatus.PUBLIC

    def discover(self, query: dict[str, Any], cursor: str | None = None) -> SourceRecordPage:
        settings = get_settings()
        dataset = str(query.get("dataset") or "label")
        endpoint = OPENFDA_DATASETS.get(dataset)
        if endpoint is None:
            raise ValueError(f"不支持的 openFDA 数据集: {dataset}")

        limit = min(max(int(query.get("page_size", 100)), 1), 1000)
        skip = int(cursor or query.get("skip", 0))
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if query.get("search"):
            params["search"] = query["search"]
        if query.get("sort"):
            params["sort"] = query["sort"]
        if settings.openfda_api_key:
            params["api_key"] = settings.openfda_api_key

        response = authoritative_get(
            f"{settings.openfda_base_url.rstrip('/')}{endpoint}",
            params=params,
            headers={"User-Agent": settings.http_user_agent, "Accept": "application/json"},
        )
        payload = response.json()
        results = payload.get("results", [])
        records = [self._record(dataset, item, query) for item in results]
        total = int(payload.get("meta", {}).get("results", {}).get("total", len(results)))
        next_offset = skip + len(results)
        next_cursor = str(next_offset) if results and next_offset < total else None
        return SourceRecordPage(records=records, next_cursor=next_cursor)

    def _record(
        self,
        dataset: str,
        item: dict[str, Any],
        query: dict[str, Any],
    ) -> SourceRecordEnvelope:
        record_id = self._record_id(dataset, item)
        title = self._title(dataset, item, record_id)
        return SourceRecordEnvelope(
            source_name=self.source_name,
            source_record_id=f"{dataset}:{record_id}",
            canonical_url=f"https://open.fda.gov/apis/drug/{dataset}/",
            title=title,
            published_at=self._published_at(item),
            content_urls=[],
            license_status=LicenseStatus.PUBLIC,
            access_class=AccessClass.PUBLIC,
            document_type=DocumentType.REGULATORY,
            raw_metadata={"dataset": dataset, "record": item, "query": query},
        )

    @staticmethod
    def _record_id(dataset: str, item: dict[str, Any]) -> str:
        candidates: list[Any] = []
        if dataset == "label":
            candidates.extend([item.get("id"), item.get("set_id")])
            candidates.extend(item.get("openfda", {}).get("spl_set_id", []))
        elif dataset == "drugsfda":
            candidates.append(item.get("application_number"))
        elif dataset == "enforcement":
            candidates.extend([item.get("recall_number"), item.get("event_id")])
        elif dataset == "shortages":
            candidates.extend([item.get("initial_posting_date"), item.get("generic_name")])
        for value in candidates:
            if value:
                return str(value)
        return stable_hash(item)[:24]

    @staticmethod
    def _title(dataset: str, item: dict[str, Any], record_id: str) -> str:
        openfda = item.get("openfda", {})
        names = openfda.get("brand_name") or openfda.get("generic_name") or []
        if not names and item.get("products"):
            names = [item["products"][0].get("brand_name")]
        if isinstance(names, str):
            names = [names]
        name = next((str(value) for value in names if value), None) if names else None
        if dataset == "enforcement":
            name = item.get("product_description") or name
        if dataset == "shortages":
            name = item.get("generic_name") or name
        return f"openFDA {dataset}: {name or record_id}"[:500]

    @staticmethod
    def _published_at(item: dict[str, Any]) -> datetime | None:
        for field in (
            "effective_time",
            "report_date",
            "initial_posting_date",
            "update_date",
        ):
            value = str(item.get(field) or "").replace("-", "")
            if len(value) == 8 and value.isdigit():
                return datetime.strptime(value, "%Y%m%d")
        return None

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        content = json.dumps(
            record.raw_metadata["record"], ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        return [
            FetchResult(
                content=content,
                media_type="application/json",
                original_url=str(record.canonical_url) if record.canonical_url else None,
                metadata={
                    "dataset": record.raw_metadata["dataset"],
                    "source_record_id": record.source_record_id,
                },
            )
        ]
