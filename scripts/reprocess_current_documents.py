"""Reprocess current document versions with an auditable, unique pipeline run."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.config import get_settings
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical.database import create_schema, get_engine
from pharma_data.storage.canonical.mineru_backends import sync_configured_mineru_backend
from pharma_data.storage.canonical.models import Document, DocumentVersion
from pharma_data.storage.canonical.repository import CanonicalRepository


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--run-tag")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    run_tag = args.run_tag or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    engine = get_engine()
    create_schema(engine)
    with Session(engine) as session:
        sync_configured_mineru_backend(session, settings)
        session.commit()
        statement = (
            select(Document.id, Document.title, DocumentVersion.id)
            .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
            .order_by(Document.created_at, Document.id)
        )
        if args.document_id:
            statement = statement.where(Document.id.in_(args.document_id))
        if args.limit:
            statement = statement.limit(args.limit)
        targets = list(session.execute(statement).all())

    _emit(
        {
            "event": "start",
            "run_tag": run_tag,
            "target_count": len(targets),
            "mineru_backend": settings.mineru_backend,
            "mineru_node_id": settings.mineru_node_id,
            "mineru_api_url": settings.mineru_api_url,
        }
    )
    failures = 0
    for position, (document_id, title, version_id) in enumerate(targets, start=1):
        with Session(engine, expire_on_commit=False) as session:
            version = session.get(DocumentVersion, version_id)
            if version is None:
                failures += 1
                _emit({"event": "missing_version", "document_id": document_id})
                continue
            repository = CanonicalRepository(session)
            job = repository.enqueue_job(
                document_version_id=version.id,
                pipeline_step="full_pipeline",
                input_hash=version.content_hash,
                component_version=f"0.3.0-mineru-{run_tag}",
                configuration={
                    "mineru_backend": settings.mineru_backend,
                    "mineru_node_id": settings.mineru_node_id,
                    "mineru_device": settings.mineru_device,
                    "quality_gates": "page-region-v1",
                },
                payload={"reprocess_run_tag": run_tag},
            )
            if not args.force and job.status not in {"FETCHED", "FAILED_RETRYABLE"}:
                _emit(
                    {
                        "event": "skip",
                        "position": position,
                        "document_id": document_id,
                        "title": title,
                        "job_id": job.id,
                        "status": job.status,
                    }
                )
                continue
            job.attempts += 1
            job.status = "PROCESSING"
            job.locked_by = f"manual-reprocess:{run_tag}"
            job.locked_at = datetime.now(UTC)
            session.flush()
            _emit(
                {
                    "event": "document_start",
                    "position": position,
                    "target_count": len(targets),
                    "document_id": document_id,
                    "document_version_id": version_id,
                    "title": title,
                    "job_id": job.id,
                }
            )
            started = datetime.now(UTC)
            try:
                result = PipelineRunner(session).run(job.id)
                session.commit()
                _emit(
                    {
                        "event": "document_complete",
                        "duration_seconds": round(
                            (datetime.now(UTC) - started).total_seconds(), 3
                        ),
                        **result,
                    }
                )
            except Exception as exc:
                failures += 1
                session.commit()  # Preserve the failed run and its exact error for audit.
                _emit(
                    {
                        "event": "document_failed",
                        "document_id": document_id,
                        "document_version_id": version_id,
                        "job_id": job.id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                if args.stop_on_error:
                    break
    _emit(
        {
            "event": "finish",
            "run_tag": run_tag,
            "target_count": len(targets),
            "failures": failures,
        }
    )
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
