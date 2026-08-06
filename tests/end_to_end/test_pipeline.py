import json

from sqlalchemy import func, select

from pharma_data.connectors.news import NewsAdapter
from pharma_data.contracts import AccessClass, ReviewStatus
from pharma_data.datasets import DataQualityValidator
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    DocumentElementRecord,
    OutboxEventRecord,
    ProcessingJob,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore


def test_public_news_runs_end_to_end_and_is_idempotent(db_session, tmp_path) -> None:
    article = tmp_path / "news.html"
    article.write_text(
        "<h1>Official update</h1><p>"
        "\u6052\u745e\u533b\u836f\u81ea\u4e3b\u7814\u53d1"
        "\u7684PD-1\u6291\u5236\u5242\u5361\u745e\u5229"
        "\u73e0\u5355\u6297\u7528\u4e8e\u6cbb\u7597"
        "\u975e\u5c0f\u7ec6\u80de\u80ba\u764c\u3002</p>",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "NEWS-E2E-1",
                    "title": "Official update",
                    "local_path": str(article),
                    "license_status": "public",
                    "access_class": "public",
                }
            ]
        ),
        encoding="utf-8",
    )
    service = IngestionService(db_session, LocalObjectStore(tmp_path / "objects"))
    first = service.ingest(NewsAdapter(manifest), {"manifest_path": str(manifest)})
    second = service.ingest(NewsAdapter(manifest), {"manifest_path": str(manifest)})

    assert first.versions_created == 1
    assert second.versions_created == 0

    job = db_session.scalar(select(ProcessingJob))
    result = PipelineRunner(db_session).run(job.id)

    assert result["elements"] >= 2
    assert result["mentions"] >= 4
    assert result["assertions"] >= 3
    assert db_session.scalar(select(func.count()).select_from(DocumentElementRecord)) >= 2
    assert db_session.scalar(select(func.count()).select_from(AssertionEvidenceRecord)) >= 3

    assertion = db_session.scalar(select(AssertionRecord))
    CanonicalRepository(db_session).record_review(
        target_type="assertion",
        target_id=assertion.id,
        decision=ReviewStatus.APPROVED,
        reviewer="test-reviewer",
        rationale="Evidence checked against source fixture",
    )
    assert db_session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 4

    document = db_session.scalar(select(Document))
    snapshot = CanonicalRepository(db_session).create_snapshot(
        name="public-e2e",
        specification={"purpose": "test"},
        manifest={"document_version_ids": [document.current_version_id]},
        access_class=AccessClass.PUBLIC,
        created_by="test",
    )
    assert snapshot.access_class == "public"
    assert DataQualityValidator(db_session).run()["passed"] is True
