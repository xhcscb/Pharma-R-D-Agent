import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
    CompareRequest,
    InboxRunRequest,
    IngestionRequest,
    ReasoningContextRequest,
    ReprocessRequest,
    ReviewRequest,
    ReviewSubmissionRequest,
    SearchRequest,
    SnapshotRequest,
    SummarizeRequest,
)
from pharma_data.config import get_settings
from pharma_data.connectors import (
    CdeManifestAdapter,
    ChinaDrugTrialsManifestAdapter,
    ClinicalDocumentAdapter,
    EarningsCallAdapter,
    FinancialReportAdapter,
    MarketDataAdapter,
    NewsAdapter,
    ResearchReportManifestAdapter,
)
from pharma_data.contracts import AccessClass
from pharma_data.inbox import InboxCoordinator, build_inbox_coordinator
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.parsers.mineru import mineru_status
from pharma_data.reasoning import (
    CompareAgent,
    EvidenceGate,
    MetricOntology,
    SummarizeAgent,
    build_claim_graph,
)
from pharma_data.reasoning.models import ClaimGraph, EvidenceRef
from pharma_data.storage.canonical import create_schema
from pharma_data.storage.canonical.access import (
    version_access_classes,
    version_has_access,
    visible_version_ids,
)
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.mineru_backends import sync_configured_mineru_backend
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    ConflictGroupRecord,
    DatasetSnapshotRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
    MetricDefinitionRecord,
    MetricObservationRecord,
    OutboxEventRecord,
    ParseCandidateRecord,
    ParseReviewItemRecord,
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
    "market_data": MarketDataAdapter,
}
DASHBOARD_PATH = Path(__file__).parent / "static" / "data_layer_dashboard.html"


def _metric_observation_payload(
    row: MetricObservationRecord,
    assertion: AssertionRecord,
    evidence: AssertionEvidenceRecord,
) -> dict[str, Any]:
    """Serialize one metric observation after its required joins have been verified."""
    return {
        "id": row.id,
        "entity_id": row.entity_id,
        "metric_definition_id": row.metric_definition_id,
        "assertion_id": assertion.id,
        "assertion_key": assertion.assertion_key,
        "fact_group_key": assertion.fact_group_key,
        "raw_value": row.raw_value,
        "numeric_value": str(row.numeric_value) if row.numeric_value is not None else None,
        "unit": row.unit,
        "currency": row.currency,
        "scale": row.scale,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "scope": row.scope,
        "evidence_id": evidence.id,
        "evidence_hash": evidence.evidence_hash,
        "evidence_locator": {
            "document_version_id": evidence.document_version_id,
            "page_number": evidence.page_number,
            "bbox": evidence.bbox,
            "char_span": evidence.char_span,
            "table_cell_id": evidence.table_cell_id,
        },
        "review_status": row.review_status,
    }


def _evidence_ref_locator_complete(item: EvidenceRef) -> bool:
    if item.page_number is not None:
        bbox = item.bbox or {}
        try:
            bbox_valid = (
                0 <= float(bbox["x0"]) <= float(bbox["x1"])
                and 0 <= float(bbox["y0"]) <= float(bbox["y1"])
            )
        except (KeyError, TypeError, ValueError):
            bbox_valid = False
        return bool(
            bbox_valid
            and (item.char_span is not None or item.table_cell_id is not None)
            and item.evidence_hash
        )
    return bool(item.audio_range and item.evidence_hash)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_schema()
    with Session(get_engine()) as session:
        sync_configured_mineru_backend(session)
        session.commit()
    yield


app = FastAPI(
    title="Pharma Analyst Data Layer",
    version="0.3.0",
    lifespan=lifespan,
)
app.include_router(GraphQLRouter(graphql_schema), prefix="/graphql")


@app.get("/demo/data-layer", include_in_schema=False)
def data_layer_dashboard() -> FileResponse:
    """返回数据层可视化看板。"""
    return FileResponse(DASHBOARD_PATH, media_type="text/html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.3.0"}


@app.get("/v1/visualizations/data-layer")
def data_layer_visualization(
    caller_access: AccessClass = Query(default=AccessClass.PUBLIC),
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """返回数据处理、质量和证据链的可视化聚合数据。"""
    caller_access = _verified_access(caller_access, x_internal_api_key)
    return build_data_layer_overview(session, _allowed_classes(caller_access))


def _reasoning_graph(
    session: Session,
    access_class: AccessClass,
    include_candidates: bool,
    entity_names: list[str] | None = None,
) -> ClaimGraph:
    statuses = ("approved", "candidate", "pending") if include_candidates else ("approved",)
    return build_claim_graph(
        session,
        allowed_access_classes=_allowed_classes(access_class),
        review_statuses=statuses,
        entity_names=entity_names,
    )


def _inbox_coordinator() -> InboxCoordinator:
    return build_inbox_coordinator(get_settings())


@app.get("/v1/inbox/status")
def inbox_status(
    x_internal_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """返回公开/受限投递箱、归档回执和 metadata 复核状态。"""
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    return _inbox_coordinator().status()


@app.post("/v1/inbox/run")
def run_inbox(
    request: InboxRunRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """立即扫描一次投递箱；常驻 worker 会按配置自动执行同一流程。"""
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    return _inbox_coordinator().run_once(
        session,
        LocalObjectStore(get_settings().object_store_root),
        run_pipeline=request.run_pipeline,
        max_files=request.max_files,
    )


@app.post("/v1/reasoning/context")
def reasoning_context(
    request: ReasoningContextRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """向下一层返回版本化主张图、证据定位、门控决策和本体契约。"""
    caller_access = _verified_access(request.access_class, x_internal_api_key)
    graph = _reasoning_graph(
        session,
        caller_access,
        request.include_candidates,
        request.entity_names or None,
    )
    decisions = [EvidenceGate().evaluate(claim, graph) for claim in graph.claims]
    action_counts: dict[str, int] = {}
    for decision in decisions:
        action_counts[decision.action.value] = action_counts.get(decision.action.value, 0) + 1
    ontology = MetricOntology.load(get_settings().metric_ontology_path)
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "access_classes": _allowed_classes(caller_access),
            "review_statuses": (
                ["approved", "candidate", "pending"]
                if request.include_candidates
                else ["approved"]
            ),
            "entity_names": request.entity_names,
        },
        "readiness": {
            "claim_count": len(graph.claims),
            "evidence_count": len(graph.evidence_links),
            "edge_count": len(graph.edges),
            "gate_actions": action_counts,
            "reasoning_ready": bool(graph.claims)
            and all(decision.action.value == "pass" for decision in decisions),
        },
        "metric_ontology": [item.model_dump(mode="json") for item in ontology.dimensions],
        "claim_graph": graph.model_dump(mode="json"),
        "gate_decisions": [item.model_dump(mode="json") for item in decisions],
    }


@app.post("/v2/reasoning/context")
def reasoning_context_v2(
    request: ReasoningContextRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return snapshot, metrics, claim graph, evidence locators and parse diagnostics."""
    caller_access = _verified_access(request.access_class, x_internal_api_key)
    allowed = _allowed_classes(caller_access)
    statuses = (
        ["approved", "candidate", "pending"]
        if request.include_candidates
        else ["approved"]
    )
    graph = _reasoning_graph(
        session,
        caller_access,
        request.include_candidates,
        request.entity_names or None,
    )
    decisions = [EvidenceGate().evaluate(claim, graph) for claim in graph.claims]
    action_counts: dict[str, int] = {}
    for decision in decisions:
        action_counts[decision.action.value] = action_counts.get(decision.action.value, 0) + 1

    visible_versions = visible_version_ids(allowed).subquery()
    observations = list(
        session.scalars(
            select(MetricObservationRecord)
            .join(
                AssertionRecord,
                AssertionRecord.id == MetricObservationRecord.assertion_id,
            )
            .join(
                AssertionEvidenceRecord,
                AssertionEvidenceRecord.id == MetricObservationRecord.evidence_id,
            )
            .join(
                visible_versions,
                visible_versions.c.id == AssertionEvidenceRecord.document_version_id,
            )
            .join(
                DocumentVersion,
                DocumentVersion.id == AssertionEvidenceRecord.document_version_id,
            )
            .join(
                DocumentElementRecord,
                DocumentElementRecord.id == AssertionEvidenceRecord.element_id,
            )
            .where(AssertionRecord.review_status.in_(statuses))
            .where(DocumentElementRecord.parse_run_id == DocumentVersion.active_parse_run_id)
            .distinct()
        )
    )
    metric_definition_ids = {row.metric_definition_id for row in observations}
    observation_assertions = {
        row.id: row
        for row in session.scalars(
            select(AssertionRecord).where(
                AssertionRecord.id.in_({item.assertion_id for item in observations})
            )
        )
    }
    observation_evidence = {
        row.id: row
        for row in session.scalars(
            select(AssertionEvidenceRecord).where(
                AssertionEvidenceRecord.id.in_({item.evidence_id for item in observations})
            )
        )
    }
    metric_definitions = {
        row.id: row
        for row in session.scalars(
            select(MetricDefinitionRecord).where(
                MetricDefinitionRecord.id.in_(metric_definition_ids)
            )
        )
    }
    snapshots = list(
        session.scalars(
            select(DatasetSnapshotRecord)
            .where(DatasetSnapshotRecord.access_class.in_(allowed))
            .order_by(DatasetSnapshotRecord.created_at.desc())
            .limit(1)
        )
    )
    current_versions = list(
        session.scalars(
            select(DocumentVersion)
            .join(Document, Document.current_version_id == DocumentVersion.id)
            .join(visible_versions, visible_versions.c.id == DocumentVersion.id)
        )
    )
    version_ids = [version.id for version in current_versions]
    parse_candidates = list(
        session.scalars(
            select(ParseCandidateRecord)
            .where(ParseCandidateRecord.document_version_id.in_(version_ids))
            .order_by(ParseCandidateRecord.created_at.desc())
        )
    )
    review_items = list(
        session.scalars(
            select(ParseReviewItemRecord).where(
                ParseReviewItemRecord.document_version_id.in_(version_ids),
                ParseReviewItemRecord.status == "open",
            )
        )
    )
    active_run_ids = {version.active_parse_run_id for version in current_versions}
    parse_candidates = [
        row for row in parse_candidates if row.parse_run_id in active_run_ids
    ]
    review_items = [row for row in review_items if row.parse_run_id in active_run_ids]

    evidence = [item for claim in graph.claims for item in claim.evidence]
    missing_locator_count = sum(
        not _evidence_ref_locator_complete(item) for item in evidence
    )
    documents_needing_metadata_review = sum(
        bool(version.metadata_json.get("metadata_review_required", True))
        for version in current_versions
    )
    visual_required_count = sum(
        int(version.metadata_json.get("parse_quality", {}).get(
            "visual_semantic_required_count", 0
        ))
        for version in current_versions
    )
    visual_verified_count = sum(
        int(version.metadata_json.get("parse_quality", {}).get(
            "visual_semantic_verified_count", 0
        ))
        for version in current_versions
    )
    blockers = []
    if not snapshots:
        blockers.append("dataset_snapshot_missing")
    if not graph.claims:
        blockers.append(
            "approved_claims_missing"
            if not request.include_candidates
            else "candidate_claims_missing"
        )
    if not observations:
        blockers.append("metric_observations_missing")
    if review_items:
        blockers.append("parse_hard_gate_review_open")
    if documents_needing_metadata_review:
        blockers.append("metadata_review_open")
    if missing_locator_count:
        blockers.append("evidence_locator_incomplete")
    if visual_verified_count < visual_required_count:
        blockers.append("visual_semantics_incomplete")
    if any(decision.action.value != "pass" for decision in decisions):
        blockers.append("evidence_gate_not_passed")
    blockers.extend(("human_gold_missing", "g3_gold_gate_not_evaluated"))

    ontology = MetricOntology.load(get_settings().metric_ontology_path)
    return {
        "schema_version": "2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "access_classes": allowed,
            "review_statuses": statuses,
            "entity_names": request.entity_names,
            "active_parse_runs_only": True,
        },
        "dataset_snapshot": (
            {
                "id": snapshots[0].id,
                "name": snapshots[0].name,
                "snapshot_hash": snapshots[0].snapshot_hash,
                "specification": snapshots[0].specification,
                "manifest": snapshots[0].manifest,
                "created_at": snapshots[0].created_at,
            }
            if snapshots
            else None
        ),
        "metric_ontology": [item.model_dump(mode="json") for item in ontology.dimensions],
        "metric_definitions": [
            {
                "id": row.id,
                "canonical_name": row.canonical_name,
                "aliases": row.aliases,
                "value_type": row.value_type,
                "allowed_units": row.allowed_units,
                "definition": row.definition,
            }
            for row in metric_definitions.values()
        ],
        "metric_observations": [
            _metric_observation_payload(
                row,
                observation_assertions[row.assertion_id],
                observation_evidence[row.evidence_id],
            )
            for row in observations
            if row.assertion_id is not None and row.evidence_id is not None
        ],
        "claim_graph": graph.model_dump(mode="json"),
        "gate_decisions": [item.model_dump(mode="json") for item in decisions],
        "parse_provenance": {
            "service": mineru_status(),
            "candidates": [
                {
                    "id": row.id,
                    "document_version_id": row.document_version_id,
                    "parse_run_id": row.parse_run_id,
                    "page_number": row.page_number,
                    "backend_name": row.backend_name,
                    "backend_version": row.backend_version,
                    "node_id": row.node_id,
                    "selected": row.selected,
                    "status": row.status,
                    "score": row.score,
                    "diagnostics": row.diagnostics,
                    "raw_output_hash": row.raw_output_hash,
                }
                for row in parse_candidates
            ],
            "review_queue": [
                {
                    "id": row.id,
                    "document_version_id": row.document_version_id,
                    "parse_run_id": row.parse_run_id,
                    "page_number": row.page_number,
                    "region_key": row.region_key,
                    "gate_code": row.gate_code,
                    "severity": row.severity,
                    "status": row.status,
                    "diagnostics": row.diagnostics,
                }
                for row in review_items
            ],
        },
        "readiness": {
            "claim_count": len(graph.claims),
            "evidence_count": len(evidence),
            "metric_observation_count": len(observations),
            "visual_semantic_required_count": visual_required_count,
            "visual_semantic_verified_count": visual_verified_count,
            "visual_semantic_coverage": (
                round(visual_verified_count / visual_required_count, 6)
                if visual_required_count
                else 1.0
            ),
            "open_parse_review_count": len(review_items),
            "evidence_locator_completeness": (
                round((len(evidence) - missing_locator_count) / len(evidence), 6)
                if evidence
                else 0.0
            ),
            "gate_actions": action_counts,
            "blockers": blockers,
            "can_use_for_formal_reasoning": not blockers,
            "engineering_baseline_only": True,
            "gold_gate": "not_evaluated_no_human_gold",
        },
    }


@app.post("/v1/reasoning/compare")
def compare_entities(
    request: CompareRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """把自然语言比较意图编译为 DSL，并返回逐主张、逐证据的比较结果。"""
    caller_access = _verified_access(request.access_class, x_internal_api_key)
    graph = _reasoning_graph(
        session,
        caller_access,
        request.include_candidates,
        request.objects or None,
    )
    agent = CompareAgent(MetricOntology.load(get_settings().metric_ontology_path))
    try:
        dsl = agent.compile(
            request.query,
            graph,
            objects=request.objects,
            dimensions=request.dimensions,
            time=request.time,
            scope=request.scope,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return agent.run(dsl, graph).model_dump(mode="json")


@app.post("/v1/reasoning/summarize")
def summarize_claims(
    request: SummarizeRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """返回共识、冲突、待复核三层同源摘要。"""
    caller_access = _verified_access(request.access_class, x_internal_api_key)
    graph = _reasoning_graph(
        session,
        caller_access,
        request.include_candidates,
        [request.entity] if request.entity else None,
    )
    result = SummarizeAgent(
        MetricOntology.load(get_settings().metric_ontology_path)
    ).run(graph, entity=request.entity, max_claims=request.max_claims)
    return result.model_dump(mode="json")


@app.post("/v1/ingestions")
def create_ingestion(
    request: IngestionRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
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
def ingestion_status(
    job_id: str,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
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
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
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
        AccessClass.RESTRICTED.value: 1,
    }
    return rank[actual] <= rank[requested.value]


def _allowed_classes(requested: AccessClass) -> list[str]:
    return [item.value for item in AccessClass if _allowed(requested, item.value)]


def _assertion_visible(session: Session, assertion_id: str, caller_access: AccessClass) -> bool:
    visible_versions = visible_version_ids(_allowed_classes(caller_access)).subquery()
    return (
        session.scalar(
            select(AssertionEvidenceRecord.id)
            .join(
                visible_versions,
                visible_versions.c.id == AssertionEvidenceRecord.document_version_id,
            )
            .join(
                DocumentVersion,
                DocumentVersion.id == AssertionEvidenceRecord.document_version_id,
            )
            .join(
                DocumentElementRecord,
                DocumentElementRecord.id == AssertionEvidenceRecord.element_id,
            )
            .where(
                AssertionEvidenceRecord.assertion_id == assertion_id,
                DocumentElementRecord.parse_run_id == DocumentVersion.active_parse_run_id,
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
    if version is None or not version_has_access(
        session, version, _allowed_classes(caller_access)
    ):
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
            "access_classes": version_access_classes(session, version),
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
    if version is None or not version_has_access(
        session, version, _allowed_classes(caller_access)
    ):
        raise HTTPException(404, "Document not found")
    rows = session.scalars(
        select(DocumentElementRecord)
        .where(
            DocumentElementRecord.document_version_id == version.id,
            DocumentElementRecord.parse_run_id == version.active_parse_run_id,
        )
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
    visible_versions = visible_version_ids(_allowed_classes(caller_access)).subquery()
    visible = session.scalar(
        select(EntityMentionRecord.id)
        .join(
            visible_versions,
            visible_versions.c.id == EntityMentionRecord.document_version_id,
        )
        .join(
            DocumentVersion,
            DocumentVersion.id == EntityMentionRecord.document_version_id,
        )
        .join(
            DocumentElementRecord,
            DocumentElementRecord.id == EntityMentionRecord.element_id,
        )
        .where(
            EntityMentionRecord.entity_id == entity_id,
            DocumentElementRecord.parse_run_id == DocumentVersion.active_parse_run_id,
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
    evidence = None
    for candidate in session.scalars(
        select(AssertionEvidenceRecord).where(
            AssertionEvidenceRecord.assertion_id == assertion.id
        )
    ):
        version = session.get(DocumentVersion, candidate.document_version_id)
        if version and version_has_access(
            session, version, _allowed_classes(caller_access)
        ):
            element = (
                session.get(DocumentElementRecord, candidate.element_id)
                if candidate.element_id
                else None
            )
            if (
                element is not None
                and version.active_parse_run_id
                and element.parse_run_id != version.active_parse_run_id
            ):
                continue
            evidence = candidate
            break
    if evidence is not None:
        version = session.get(DocumentVersion, evidence.document_version_id)
        if version is None:
            raise HTTPException(404, "Assertion not found")
    return {
        "id": assertion.id,
        "assertion_key": assertion.assertion_key,
        "fact_group_key": assertion.fact_group_key,
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
                "evidence_hash": evidence.evidence_hash,
                "document_version_id": evidence.document_version_id,
                "element_id": evidence.element_id,
                "utterance_id": evidence.utterance_id,
                "text": evidence.evidence_text,
                "page_number": evidence.page_number,
                "bbox": evidence.bbox,
                "char_span": evidence.char_span,
                "table_cell_id": evidence.table_cell_id,
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
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    return CanonicalRepository(session).review_queue(limit)


@app.post("/v1/reviews/{target_type}/{target_id}")
def submit_review(
    target_type: str,
    target_id: str,
    request: ReviewRequest,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    return _record_review(target_type, target_id, request, session)


def _record_review(
    target_type: str,
    target_id: str,
    request: ReviewRequest,
    session: Session,
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
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    return _record_review(request.target_type, request.target_id, request, session)


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
        if document.id in seen or not version_has_access(
            session, version, _allowed_classes(caller_access)
        ):
            continue
        if version.active_parse_run_id and element.parse_run_id != version.active_parse_run_id:
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
def rebuild_projection(
    name: str,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    dispatcher = ProjectionDispatcher()
    projector = dispatcher.projectors.get(name)
    if projector is None:
        raise HTTPException(404, "Projection not found")
    return projector.rebuild(session)


@app.get("/v1/projections/{name}/status")
def projection_status(
    name: str,
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
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
    x_internal_api_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _verified_access(AccessClass.RESTRICTED, x_internal_api_key)
    row = CanonicalRepository(session).create_snapshot(
        name=request.name,
        specification=request.specification,
        manifest={"document_version_ids": request.document_version_ids},
        access_class=request.access_class,
        created_by=request.created_by,
    )
    return {"id": row.id, "snapshot_hash": row.snapshot_hash, "access_class": row.access_class}
