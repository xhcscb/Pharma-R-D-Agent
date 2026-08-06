import json

from sqlalchemy import func, select

from pharma_data.connectors.news import NewsAdapter
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical.models import (
    AssertionRecord,
    DocumentElementRecord,
    EntityMentionRecord,
    ProcessingJob,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore


def test_explicit_reprocessing_does_not_duplicate_facts(db_session, tmp_path) -> None:
    article = tmp_path / "news.html"
    article.write_text(
        "<p>\u6052\u745e\u533b\u836f\u7814\u53d1\u5361\u745e\u5229"
        "\u73e0\u5355\u6297\u7528\u4e8e\u6cbb\u7597\u975e\u5c0f"
        "\u7ec6\u80de\u80ba\u764c</p>",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "IDEMPOTENT-1",
                    "title": "Idempotency fixture",
                    "local_path": str(article),
                    "license_status": "public",
                    "access_class": "public",
                }
            ]
        ),
        encoding="utf-8",
    )
    IngestionService(db_session, LocalObjectStore(tmp_path / "objects")).ingest(
        NewsAdapter(manifest), {"manifest_path": str(manifest)}
    )
    first_job = db_session.scalar(select(ProcessingJob))
    PipelineRunner(db_session).run(first_job.id)
    first_counts = (
        db_session.scalar(select(func.count()).select_from(DocumentElementRecord)),
        db_session.scalar(select(func.count()).select_from(EntityMentionRecord)),
        db_session.scalar(select(func.count()).select_from(AssertionRecord)),
    )

    second_job = CanonicalRepository(db_session).enqueue_job(
        document_version_id=first_job.document_version_id,
        pipeline_step="full_pipeline",
        input_hash=first_job.idempotency_key,
        component_version="0.1.0-reprocess-test",
    )
    PipelineRunner(db_session).run(second_job.id)
    second_counts = (
        db_session.scalar(select(func.count()).select_from(DocumentElementRecord)),
        db_session.scalar(select(func.count()).select_from(EntityMentionRecord)),
        db_session.scalar(select(func.count()).select_from(AssertionRecord)),
    )

    assert second_counts == first_counts
