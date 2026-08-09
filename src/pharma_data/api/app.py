import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from strawberry.fastapi import GraphQLRouter

from pharma_data.api.dependencies import get_session
from pharma_data.api.graphql import schema as graphql_schema
from pharma_data.api.schemas import (
    IngestionRequest,
    ReprocessRequest,
    ReviewRequest,
    ReviewSubmissionRequest,
    SearchRequest,
    SnapshotRequest,
)
from pharma_data.config import get_settings
from pharma_data.connectors import (
    CdeManifestAdapter,
    ChinaDrugTrialsManifestAdapter,
    ClinicalDocumentAdapter,
    EarningsCallAdapter,
    FinancialReportAdapter,
    NewsAdapter,
    ResearchReportManifestAdapter,
)
from pharma_data.contracts import AccessClass
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.storage.canonical import create_schema
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    ConflictGroupRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
    OutboxEventRecord,
    ProcessingJob,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore
from pharma_data.storage.projectors import ProjectionDispatcher
from pharma_data.visualization import build_data_layer_overview

ADAPTERS = {
    "research_reports": ResearchReportManifestAdapter,
    "china_drug_trials": ChinaDrugTrialsManifestAdapter,
    "cde": CdeManifestAdapter,
    "clinical_documents": ClinicalDocumentAdapter,
    "financial_reports": FinancialReportAdapter,
    "news": NewsAdapter,
    "earnings_calls": EarningsCallAdapter,
}
DASHBOARD_PATH = Path(__file__).parent / "static" / "data_layer_dashboard.html"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_schema()
    yield


app = FastAPI(
    title="Pharma Analyst Data Layer",
    version="0.2.0",
    lifespan=lifespan,
)
app.include_router(GraphQLRouter(graphql_schema), prefix="/graphql")


@app.get("/demo/data-layer", include_in_schema=False)
def data_layer_dashboard() -> FileResponse:
    """返回数据层可视化看板。"""
    return FileResponse(DASHBOARD_PATH, media_type="text/html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}


@app.get("/v1/visualizations/data-layer")
def data_layer_visualization(
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """返回数据处理、质量和证据链的可视化聚合数据。"""
    caller_access = _verified_access(caller_access, x_internal_api_key)
    return build_data_layer_overview(session, _allowed_classes(caller_access))


@app.post("/v1/ingestions")
def create_ingestion(
    request: IngestionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    adapter_class = ADAPTERS.get(request.source_type)
    if adapter_class is None:
        raise HTTPException(400, f"Unknown source_type: {request.source_type}")
    adapter = adapter_class()
    report = IngestionService(
        session,
        LocalObjectStore(get_settings().object_store_root),
    ).ingest(adapter, request.query, max_pages=request.max_pages)
    return report.__dict__


@app.get("/v1/ingestions/{job_id}")
def ingestion_status(job_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    job = session.get(ProcessingJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return {
        "id": job.id,
        "document_version_id": job.document_version_id,
        "pipeline_step": job.pipeline_step,
        "status": job.status,
        "attempts": job.attempts,
        "last_error": job.last_error,
    }


@app.post("/v1/documents/{document_id}/reprocess")
def reprocess_document(
    document_id: str,
    request: ReprocessRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    document = session.get(Document, document_id)
    if document is None or not document.current_version_id:
        raise HTTPException(404, "Document not found")
    version = session.get(DocumentVersion, document.current_version_id)
    if version is None:
        raise HTTPException(409, "Current document version is missing")
    job = CanonicalRepository(session).enqueue_job(
        document_version_id=version.id,
        pipeline_step=request.pipeline_step,
        input_hash=version.content_hash,
        configuration=request.configuration,
        component_version=f"0.2.0-reprocess-{len(request.configuration)}",
    )
    return {"job_id": job.id, "status": job.status}


def _allowed(requested: AccessClass, actual: str) -> bool:
    rank = {
        AccessClass.PUBLIC.value: 0,
        AccessClass.TEAM_INTERNAL.value: 1,
        AccessClass.RESTRICTED.value: 2,
    }
    return rank[actual] <= rank[requested.value]


def _allowed_classes(requested: AccessClass) -> list[str]:
    return [item.value for item in AccessClass if _allowed(requested, item.value)]


def _assertion_visible(session: Session, assertion_id: str, caller_access: AccessClass) -> bool:
    return (
        session.scalar(
            select(AssertionEvidenceRecord.id)
            .join(DocumentVersion)
            .where(
                AssertionEvidenceRecord.assertion_id == assertion_id,
                DocumentVersion.access_class.in_(_allowed_classes(caller_access)),
            )
            .limit(1)
        )
        is not None
    )


def _verified_access(requested: AccessClass, api_key: str | None) -> AccessClass:
    if requested == AccessClass.PUBLIC:
        return requested
    expected = get_settings().internal_api_key
    if not expected or not api_key or not secrets.compare_digest(expected, api_key):
        raise HTTPException(403, "Internal API key required for non-public access")
    return requested


@app.get("/v1/documents/{document_id}")
def get_document(
    document_id: str,
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    caller_access = _verified_access(caller_access, x_internal_api_key)
    document = session.get(Document, document_id)
    if document is None or not document.current_version_id:
        raise HTTPException(404, "Document not found")
    version = session.get(DocumentVersion, document.current_version_id)
    if version is None or not _allowed(caller_access, version.access_class):
        raise HTTPException(404, "Document not found")
    return {
        "id": document.id,
        "title": document.title,
        "document_type": document.document_type,
        "language": document.language,
        "current_version": {
            "id": version.id,
            "content_hash": version.content_hash,
            "published_at": version.published_at,
            "retrieved_at": version.retrieved_at,
            "license_status": version.license_status,
            "access_class": version.access_class,
            "metadata": version.metadata_json,
        },
    }


@app.get("/v1/documents/{document_id}/elements")
def get_document_elements(
    document_id: str,
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    caller_access = _verified_access(caller_access, x_internal_api_key)
    document = session.get(Document, document_id)
    if document is None or not document.current_version_id:
        raise HTTPException(404, "Document not found")
    version = session.get(DocumentVersion, document.current_version_id)
    if version is None or not _allowed(caller_access, version.access_class):
        raise HTTPException(404, "Document not found")
    rows = session.scalars(
        select(DocumentElementRecord)
        .where(DocumentElementRecord.document_version_id == version.id)
        .order_by(DocumentElementRecord.page_number, DocumentElementRecord.reading_order)
    )
    return [
        {
            "id": row.id,
            "page_number": row.page_number,
            "element_type": row.element_type,
            "bbox": row.bbox,
            "reading_order": row.reading_order,
            "text": row.text,
            "structured_payload": row.structured_payload,
            "confidence": row.confidence,
        }
        for row in rows
    ]


@app.get("/v1/entities/{entity_id}")
def get_entity(
    entity_id: str,
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    caller_access = _verified_access(caller_access, x_internal_api_key)
    entity = session.get(EntityRecord, entity_id)
    visible = session.scalar(
        select(EntityMentionRecord.id)
        .join(DocumentVersion)
        .where(
            EntityMentionRecord.entity_id == entity_id,
            DocumentVersion.access_class.in_(_allowed_classes(caller_access)),
        )
        .limit(1)
    )
    if entity is None or visible is None:
        raise HTTPException(404, "Entity not found")
    return {
        "id": entity.id,
        "entity_type": entity.entity_type,
        "canonical_name": entity.canonical_name,
        "external_ids": entity.external_ids,
        "properties": entity.properties,
        "review_status": entity.review_status,
    }


@app.get("/v1/assertions/{assertion_id}")
def get_assertion(
    assertion_id: str,
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    caller_access = _verified_access(caller_access, x_internal_api_key)
    assertion = session.get(AssertionRecord, assertion_id)
    if assertion is None or not _assertion_visible(session, assertion_id, caller_access):
        raise HTTPException(404, "Assertion not found")
    evidence = session.scalar(
        select(AssertionEvidenceRecord)
        .where(AssertionEvidenceRecord.assertion_id == assertion.id)
        .limit(1)
    )
    if evidence:
        version = session.get(DocumentVersion, evidence.document_version_id)
        if version is None or not _allowed(caller_access, version.access_class):
            raise HTTPException(404, "Assertion not found")
    return {
        "id": assertion.id,
        "subject_entity_id": assertion.subject_entity_id,
        "predicate": assertion.predicate,
        "object_entity_id": assertion.object_entity_id,
        "object_value": assertion.object_value,
        "qualifiers": assertion.qualifiers,
        "mode": assertion.assertion_mode,
        "confidence": assertion.confidence,
        "review_status": assertion.review_status,
        "evidence": (
            {
                "id": evidence.id,
                "document_version_id": evidence.document_version_id,
                "element_id": evidence.element_id,
                "utterance_id": evidence.utterance_id,
                "text": evidence.evidence_text,
                "page_number": evidence.page_number,
                "bbox": evidence.bbox,
                "audio_range": evidence.audio_range,
            }
            if evidence
            else None
        ),
    }


@app.get("/v1/conflicts")
def list_conflicts(
    status: str | None = None,
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    caller_access = _verified_access(caller_access, x_internal_api_key)
    statement = select(ConflictGroupRecord).order_by(ConflictGroupRecord.created_at.desc())
    if status:
        statement = statement.where(ConflictGroupRecord.status == status)
    return [
        {
            "id": row.id,
            "conflict_type": row.conflict_type,
            "assertion_ids": row.assertion_ids,
            "status": row.status,
            "rationale": row.rationale,
            "resolution": row.resolution,
        }
        for row in session.scalars(statement)
        if all(
            _assertion_visible(session, assertion_id, caller_access)
            for assertion_id in row.assertion_ids
        )
    ]


@app.get("/v1/review-queue")
def review_queue(
    limit: int = Query(default=100, ge=1, le=500),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    _verified_access(AccessClass.TEAM_INTERNAL, x_internal_api_key)
    return CanonicalRepository(session).review_queue(limit)


@app.post("/v1/reviews/{target_type}/{target_id}")
def submit_review(
    target_type: str,
    target_id: str,
    request: ReviewRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        row = CanonicalRepository(session).record_review(
            target_type=target_type,
            target_id=target_id,
            decision=request.decision,
            reviewer=request.reviewer,
            rationale=request.rationale,
        )
    except KeyError:
        raise HTTPException(404, "Review target not found") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"review_id": row.id, "decision": row.decision}


@app.post("/v1/reviews")
def submit_review_body(
    request: ReviewSubmissionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return submit_review(request.target_type, request.target_id, request, session)


@app.post("/v1/search")
def search(
    request: SearchRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    caller_access = _verified_access(request.access_class, x_internal_api_key)
    statement = (
        select(Document, DocumentVersion, DocumentElementRecord)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .join(
            DocumentElementRecord,
            DocumentElementRecord.document_version_id == DocumentVersion.id,
        )
        .where(
            or_(
                Document.title.ilike(f"%{request.query}%"),
                DocumentElementRecord.text.ilike(f"%{request.query}%"),
            )
        )
        .limit(request.limit * 5)
    )
    if request.document_types:
        statement = statement.where(Document.document_type.in_(request.document_types))
    results = []
    seen: set[str] = set()
    for document, version, element in session.execute(statement):
        if document.id in seen or not _allowed(caller_access, version.access_class):
            continue
        seen.add(document.id)
        results.append(
            {
                "document_id": document.id,
                "title": document.title,
                "document_type": document.document_type,
                "version_id": version.id,
                "element_id": element.id,
                "page_number": element.page_number,
                "snippet": element.text[:500],
            }
        )
        if len(results) >= request.limit:
            break
    return results


@app.post("/v1/projections/{name}/rebuild")
def rebuild_projection(name: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    dispatcher = ProjectionDispatcher()
    projector = dispatcher.projectors.get(name)
    if projector is None:
        raise HTTPException(404, "Projection not found")
    return projector.rebuild(session)


@app.get("/v1/projections/{name}/status")
def projection_status(name: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    if name not in ProjectionDispatcher().projectors:
        raise HTTPException(404, "Projection not found")
    pending = session.scalar(
        select(func.count())
        .select_from(OutboxEventRecord)
        .where(
            OutboxEventRecord.projection == name,
            OutboxEventRecord.published_at.is_(None),
        )
    )
    published = session.scalar(
        select(func.count())
        .select_from(OutboxEventRecord)
        .where(
            OutboxEventRecord.projection == name,
            OutboxEventRecord.published_at.is_not(None),
        )
    )
    return {"projection": name, "pending": pending or 0, "published": published or 0}


@app.post("/v1/dataset-snapshots")
def create_snapshot(
    request: SnapshotRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    row = CanonicalRepository(session).create_snapshot(
        name=request.name,
        specification=request.specification,
        manifest={"document_version_ids": request.document_version_ids},
        access_class=request.access_class,
        created_by=request.created_by,
    )
    return {"id": row.id, "snapshot_hash": row.snapshot_hash, "access_class": row.access_class}
