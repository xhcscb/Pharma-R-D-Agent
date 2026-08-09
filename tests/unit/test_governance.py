import json

import pytest
from sqlalchemy import func, select

from pharma_data.connectors.news import NewsAdapter
from pharma_data.connectors.research_reports import ResearchReportManifestAdapter
from pharma_data.contracts import AccessClass, ReviewStatus
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.storage.canonical.models import (
    AssertionRecord,
    Document,
    RawArtifactRecord,
    SourceRecord,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore


def test_unresolved_license_is_metadata_only_and_quarantined(db_session, tmp_path) -> None:
    article = tmp_path / "unknown.html"
    article.write_text("<p>Do not fetch this content.</p>", encoding="utf-8")
    manifest = tmp_path / "unknown.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "UNKNOWN-1",
                    "title": "Unknown-license record",
                    "local_path": str(article),
                    "license_status": "unknown",
                    "access_class": "team_internal",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = IngestionService(db_session, LocalObjectStore(tmp_path / "objects")).ingest(
        NewsAdapter(manifest), {"manifest_path": str(manifest)}
    )

    source_record = db_session.scalar(select(SourceRecord))
    assert report.quarantined_records == 1
    assert report.artifacts_stored == 0
    assert source_record.status == "QUARANTINED"
    assert db_session.scalar(select(func.count()).select_from(RawArtifactRecord)) == 0


def test_restricted_version_cannot_enter_public_snapshot(db_session, tmp_path) -> None:
    report_pdf = tmp_path / "authorized.pdf"
    report_pdf.write_bytes(b"%PDF-1.4\n% authorized fixture")
    manifest = tmp_path / "research.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "RR-1",
                    "title": "Authorized research report",
                    "local_path": str(report_pdf),
                    "license_status": "authorized_restricted",
                    "access_class": "restricted",
                }
            ]
        ),
        encoding="utf-8",
    )
    IngestionService(db_session, LocalObjectStore(tmp_path / "objects")).ingest(
        ResearchReportManifestAdapter(manifest),
        {"manifest_path": str(manifest)},
    )
    document = db_session.scalar(select(Document))

    with pytest.raises(ValueError, match="Public snapshots"):
        CanonicalRepository(db_session).create_snapshot(
            name="invalid-public",
            specification={},
            manifest={"document_version_ids": [document.current_version_id]},
            access_class=AccessClass.PUBLIC,
            created_by="test",
        )


def test_publicly_accessible_version_cannot_enter_public_snapshot(db_session, tmp_path) -> None:
    page = tmp_path / "official.html"
    page.write_text("<p>官方公开页面，仅供内部解析。</p>", encoding="utf-8")
    manifest = tmp_path / "official.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "OFFICIAL-1",
                    "title": "官方公开页面",
                    "local_path": str(page),
                    "license_status": "public_access",
                    "access_class": "team_internal",
                }
            ]
        ),
        encoding="utf-8",
    )
    IngestionService(db_session, LocalObjectStore(tmp_path / "objects")).ingest(
        NewsAdapter(manifest), {"manifest_path": str(manifest)}
    )
    document = db_session.scalar(select(Document))

    with pytest.raises(ValueError, match="Public snapshots"):
        CanonicalRepository(db_session).create_snapshot(
            name="invalid-public-access",
            specification={},
            manifest={"document_version_ids": [document.current_version_id]},
            access_class=AccessClass.PUBLIC,
            created_by="test",
        )


def test_assertion_without_evidence_cannot_be_approved(db_session) -> None:
    assertion = AssertionRecord(
        subject_mention_id="missing-mention",
        predicate="REPORTS",
        object_value="1",
        assertion_mode="stated",
        extraction_method="test",
        confidence=1.0,
        review_status="candidate",
        assertion_key="a" * 64,
    )
    db_session.add(assertion)
    db_session.flush()

    with pytest.raises(ValueError, match="without evidence"):
        CanonicalRepository(db_session).record_review(
            target_type="assertion",
            target_id=assertion.id,
            decision=ReviewStatus.APPROVED,
            reviewer="test",
            rationale="must fail",
        )


def test_rss_dates_support_rfc_2822_and_iso8601() -> None:
    rfc = NewsAdapter._published_at("Wed, 06 Aug 2025 12:30:00 +0000")
    iso = NewsAdapter._published_at("2025-08-06T12:30:00Z")

    assert rfc is not None and rfc.isoformat() == "2025-08-06T12:30:00+00:00"
    assert iso is not None and iso.isoformat() == "2025-08-06T12:30:00+00:00"
