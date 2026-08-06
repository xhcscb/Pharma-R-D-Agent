from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from pharma_data.connectors.base import SourceAdapter
from pharma_data.contracts import LicenseStatus, PipelineStatus
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore


@dataclass
class IngestionReport:
    records_discovered: int = 0
    artifacts_stored: int = 0
    versions_created: int = 0
    jobs_enqueued: int = 0
    quarantined_records: int = 0


class IngestionService:
    def __init__(self, session: Session, object_store: LocalObjectStore):
        self.repository = CanonicalRepository(session)
        self.object_store = object_store

    def ingest(
        self,
        adapter: SourceAdapter,
        query: dict[str, Any],
        *,
        max_pages: int | None = None,
    ) -> IngestionReport:
        report = IngestionReport()
        source = self.repository.ensure_source(
            name=adapter.source_name,
            adapter_name=adapter.adapter_name,
            authority_tier=adapter.authority_tier,
            default_license_status=adapter.default_license_status,
            base_url=adapter.base_url,
            terms_url=adapter.terms_url,
        )
        cursor: str | None = None
        page_count = 0
        while True:
            page = adapter.discover(query, cursor)
            page_count += 1
            for envelope in page.records:
                report.records_discovered += 1
                source_record = self.repository.upsert_source_record(source, envelope)
                if envelope.license_status in {
                    LicenseStatus.METADATA_ONLY,
                    LicenseStatus.PROHIBITED,
                    LicenseStatus.UNKNOWN,
                }:
                    source_record.status = PipelineStatus.QUARANTINED.value
                    source_record.raw_metadata = {
                        **source_record.raw_metadata,
                        "quarantine_reason": "content_fetch_not_permitted_by_license",
                    }
                    report.quarantined_records += 1
                    continue
                for fetched in adapter.fetch(envelope):
                    stored = self.object_store.put_bytes(fetched.content)
                    artifact = self.repository.save_artifact(
                        source_record=source_record,
                        media_type=fetched.media_type,
                        object_path=str(stored.path),
                        content_hash=stored.content_hash,
                        size_bytes=stored.size_bytes,
                        original_url=fetched.original_url,
                        license_status=envelope.license_status,
                        access_class=envelope.access_class,
                        metadata=fetched.metadata,
                    )
                    report.artifacts_stored += 1
                    _, version, created = self.repository.create_document_version(
                        source_record=source_record,
                        artifact=artifact,
                    )
                    report.versions_created += int(created)
                    job = self.repository.enqueue_job(
                        document_version_id=version.id,
                        pipeline_step="full_pipeline",
                        input_hash=version.content_hash,
                        payload={"artifact_id": artifact.id},
                    )
                    if job.attempts == 0:
                        report.jobs_enqueued += 1
            cursor = page.next_cursor
            if not cursor or (max_pages is not None and page_count >= max_pages):
                break
        return report
