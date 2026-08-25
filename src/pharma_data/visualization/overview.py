from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.orm import Session

from pharma_data.config import get_settings
from pharma_data.inbox import build_inbox_coordinator
from pharma_data.parsers.mineru import mineru_status
from pharma_data.storage.canonical.access import version_access_classes, visible_version_ids
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    ConflictGroupRecord,
    Document,
    DocumentAccessGrantRecord,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    MetricObservationRecord,
    MineruBackendRecord,
    ParseReviewItemRecord,
    ProcessingJob,
    ProcessingRun,
    RawArtifactRecord,
    SourceRecord,
    SourceRegistry,
)
from pharma_data.visualization.graph import (
    build_entity_extraction_example,
    build_relation_graph,
)


def _count(session: Session, statement: Any) -> int:
    return int(session.scalar(statement) or 0)


def _grouped_counts(session: Session, statement: Any) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in session.execute(statement)]


def _rounded_average(column: Any) -> Any:
    """Return a two-argument ROUND expression valid on SQLite and PostgreSQL."""
    return func.round(cast(func.avg(column), Numeric), 3)


def _evidence_locator_complete(row: AssertionEvidenceRecord) -> bool:
    if row.element_id:
        bbox = row.bbox or {}
        try:
            bbox_valid = (
                0 <= float(bbox["x0"]) <= float(bbox["x1"])
                and 0 <= float(bbox["y0"]) <= float(bbox["y1"])
            )
        except (KeyError, TypeError, ValueError):
            bbox_valid = False
        return bool(
            row.page_number is not None
            and bbox_valid
            and (row.char_span is not None or row.table_cell_id is not None)
            and row.evidence_hash
        )
    if row.utterance_id:
        return bool(row.audio_range and row.evidence_hash)
    return False


def build_data_layer_overview(
    session: Session,
    allowed_access_classes: list[str],
) -> dict[str, Any]:
    """返回按调用者权限过滤的数据层总览。

    文档、元素、实体和关系统计只计算每份文档的当前版本；版本、任务和运行统计
    保留历史记录。这样既避免动态网页版本重复放大业务数据，也能展示版本血缘。
    """
    visible_versions = visible_version_ids(allowed_access_classes).subquery()
    current_versions = (
        select(
            DocumentVersion.id.label("id"),
            DocumentVersion.active_parse_run_id.label("active_parse_run_id"),
        )
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .join(visible_versions, visible_versions.c.id == DocumentVersion.id)
        .subquery()
    )
    active_elements = (
        select(
            DocumentElementRecord.id.label("id"),
            DocumentElementRecord.document_version_id.label("document_version_id"),
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
        .where(DocumentElementRecord.parse_run_id == current_versions.c.active_parse_run_id)
        .subquery()
    )

    visible_assertion_ids = set(
        session.scalars(
            select(AssertionEvidenceRecord.assertion_id)
            .join(
                active_elements,
                active_elements.c.id == AssertionEvidenceRecord.element_id,
            )
            .distinct()
        )
    )
    # Conflict rows are immutable audit records and may contain assertions from
    # older parses. Collapse them by their currently active members so historical
    # supersets neither disappear nor inflate the dashboard.
    visible_conflicts_by_members: dict[tuple[str, ...], ConflictGroupRecord] = {}
    for row in session.scalars(select(ConflictGroupRecord).order_by(ConflictGroupRecord.id)):
        members = tuple(sorted(set(row.assertion_ids) & visible_assertion_ids))
        if len(members) >= 2:
            visible_conflicts_by_members[members] = row
    visible_conflicts = list(visible_conflicts_by_members.values())

    source_rows = _grouped_counts(
        session,
        select(
            SourceRegistry.name.label("source"),
            SourceRegistry.authority_tier,
            func.count(func.distinct(SourceRecord.id)).label("records"),
            func.count(func.distinct(DocumentVersion.id)).label("versions"),
        )
        .join(SourceRecord, SourceRecord.source_id == SourceRegistry.id)
        .join(DocumentVersion, DocumentVersion.source_record_id == SourceRecord.id)
        .join(visible_versions, visible_versions.c.id == DocumentVersion.id)
        .group_by(SourceRegistry.id, SourceRegistry.name, SourceRegistry.authority_tier)
        .order_by(SourceRegistry.name),
    )

    element_counts = (
        select(
            DocumentElementRecord.document_version_id.label("version_id"),
            func.count(DocumentElementRecord.id).label("elements"),
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
        .where(DocumentElementRecord.parse_run_id == current_versions.c.active_parse_run_id)
        .group_by(DocumentElementRecord.document_version_id)
        .subquery()
    )
    mention_counts = (
        select(
            EntityMentionRecord.document_version_id.label("version_id"),
            func.count(EntityMentionRecord.id).label("mentions"),
        )
        .join(
            active_elements,
            active_elements.c.id == EntityMentionRecord.element_id,
        )
        .group_by(EntityMentionRecord.document_version_id)
        .subquery()
    )
    assertion_counts = (
        select(
            AssertionEvidenceRecord.document_version_id.label("version_id"),
            func.count(func.distinct(AssertionEvidenceRecord.assertion_id)).label("assertions"),
        )
        .join(
            active_elements,
            active_elements.c.id == AssertionEvidenceRecord.element_id,
        )
        .group_by(AssertionEvidenceRecord.document_version_id)
        .subquery()
    )
    approved_assertion_counts = (
        select(
            AssertionEvidenceRecord.document_version_id.label("version_id"),
            func.count(func.distinct(AssertionEvidenceRecord.assertion_id)).label(
                "approved_assertions"
            ),
        )
        .join(AssertionRecord, AssertionRecord.id == AssertionEvidenceRecord.assertion_id)
        .join(
            active_elements,
            active_elements.c.id == AssertionEvidenceRecord.element_id,
        )
        .where(AssertionRecord.review_status == "approved")
        .group_by(AssertionEvidenceRecord.document_version_id)
        .subquery()
    )
    document_rows = _grouped_counts(
        session,
        select(
            Document.id,
            Document.title,
            Document.document_type,
            SourceRegistry.name.label("source"),
            DocumentVersion.license_status,
            DocumentVersion.access_class,
            DocumentVersion.published_at,
            DocumentVersion.metadata_json.label("metadata_json"),
            func.coalesce(element_counts.c.elements, 0).label("elements"),
            func.coalesce(mention_counts.c.mentions, 0).label("mentions"),
            func.coalesce(assertion_counts.c.assertions, 0).label("assertions"),
            func.coalesce(approved_assertion_counts.c.approved_assertions, 0).label(
                "approved_assertions"
            ),
        )
        .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
        .join(current_versions, current_versions.c.id == DocumentVersion.id)
        .join(SourceRecord, SourceRecord.id == DocumentVersion.source_record_id)
        .join(SourceRegistry, SourceRegistry.id == SourceRecord.source_id)
        .outerjoin(element_counts, element_counts.c.version_id == DocumentVersion.id)
        .outerjoin(mention_counts, mention_counts.c.version_id == DocumentVersion.id)
        .outerjoin(assertion_counts, assertion_counts.c.version_id == DocumentVersion.id)
        .outerjoin(
            approved_assertion_counts,
            approved_assertion_counts.c.version_id == DocumentVersion.id,
        )
        .order_by(func.coalesce(element_counts.c.elements, 0).desc()),
    )
    for item in document_rows:
        metadata = item.pop("metadata_json", {}) or {}
        item["issuer"] = metadata.get("issuer")
        item["stock_code"] = metadata.get("stock_code")
        item["report_period"] = metadata.get("report_period")
        item["provenance_status"] = metadata.get("provenance_status", "legacy_or_manual")
        item["metadata_review_required"] = bool(
            metadata.get("metadata_review_required", True)
        )
        item["reasoning_ready"] = int(item["approved_assertions"]) > 0
        # `id` is the document id here; resolve through current_version for grant display.
        document = session.get(Document, item.get("id"))
        current_version = (
            session.get(DocumentVersion, document.current_version_id)
            if document and document.current_version_id
            else None
        )
        item["access_classes"] = (
            version_access_classes(session, current_version) if current_version else []
        )

    element_types = _grouped_counts(
        session,
        select(
            DocumentElementRecord.element_type.label("label"),
            func.count(DocumentElementRecord.id).label("value"),
            _rounded_average(DocumentElementRecord.confidence).label("confidence"),
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
        .where(DocumentElementRecord.parse_run_id == current_versions.c.active_parse_run_id)
        .group_by(DocumentElementRecord.element_type)
        .order_by(func.count(DocumentElementRecord.id).desc()),
    )
    entity_types = _grouped_counts(
        session,
        select(
            EntityMentionRecord.entity_type.label("label"),
            func.count(EntityMentionRecord.id).label("value"),
            func.sum(
                case((EntityMentionRecord.entity_id.is_not(None), 1), else_=0)
            ).label("linked"),
            _rounded_average(EntityMentionRecord.confidence).label("confidence"),
        )
        .join(
            active_elements,
            active_elements.c.id == EntityMentionRecord.element_id,
        )
        .group_by(EntityMentionRecord.entity_type)
        .order_by(func.count(EntityMentionRecord.id).desc()),
    )
    predicates = _grouped_counts(
        session,
        select(
            AssertionRecord.predicate.label("label"),
            func.count(func.distinct(AssertionRecord.id)).label("value"),
            _rounded_average(AssertionRecord.confidence).label("confidence"),
            AssertionRecord.review_status,
        )
        .join(
            AssertionEvidenceRecord,
            AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
        )
        .join(
            active_elements,
            active_elements.c.id == AssertionEvidenceRecord.element_id,
        )
        .group_by(AssertionRecord.predicate, AssertionRecord.review_status)
        .order_by(func.count(func.distinct(AssertionRecord.id)).desc()),
    )
    parsers = _grouped_counts(
        session,
        select(
            DocumentElementRecord.parser_name.label("label"),
            func.count(DocumentElementRecord.id).label("value"),
            _rounded_average(DocumentElementRecord.confidence).label("confidence"),
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
        .where(DocumentElementRecord.parse_run_id == current_versions.c.active_parse_run_id)
        .group_by(DocumentElementRecord.parser_name)
        .order_by(func.count(DocumentElementRecord.id).desc()),
    )
    jobs = _grouped_counts(
        session,
        select(
            ProcessingJob.status.label("label"),
            func.count(ProcessingJob.id).label("value"),
            func.sum(ProcessingJob.attempts).label("attempts"),
        )
        .join(visible_versions, visible_versions.c.id == ProcessingJob.document_version_id)
        .group_by(ProcessingJob.status)
        .order_by(func.count(ProcessingJob.id).desc()),
    )
    runs = _grouped_counts(
        session,
        select(
            ProcessingRun.status.label("label"),
            func.count(ProcessingRun.id).label("value"),
        )
        .join(ProcessingJob, ProcessingJob.id == ProcessingRun.job_id)
        .join(visible_versions, visible_versions.c.id == ProcessingJob.document_version_id)
        .group_by(ProcessingRun.status)
        .order_by(func.count(ProcessingRun.id).desc()),
    )
    licenses = _grouped_counts(
        session,
        select(
            DocumentVersion.license_status.label("label"),
            DocumentVersion.access_class,
            func.count(DocumentVersion.id).label("value"),
        )
        .join(visible_versions, visible_versions.c.id == DocumentVersion.id)
        .group_by(DocumentVersion.license_status, DocumentVersion.access_class),
    )
    assertion_reviews = _grouped_counts(
        session,
        select(
            AssertionRecord.review_status.label("label"),
            func.count(func.distinct(AssertionRecord.id)).label("value"),
        )
        .join(
            AssertionEvidenceRecord,
            AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
        )
        .join(
            active_elements,
            active_elements.c.id == AssertionEvidenceRecord.element_id,
        )
        .group_by(AssertionRecord.review_status),
    )

    evidence_examples = _grouped_counts(
        session,
        select(
            AssertionRecord.id,
            AssertionRecord.predicate,
            EntityMentionRecord.normalized_name.label("subject"),
            AssertionRecord.object_value,
            AssertionRecord.object_unit,
            AssertionRecord.confidence,
            AssertionRecord.review_status,
            AssertionEvidenceRecord.page_number,
            AssertionEvidenceRecord.evidence_text.label("evidence"),
            Document.title.label("document"),
        )
        .join(
            AssertionEvidenceRecord,
            AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
        )
        .join(
            active_elements,
            active_elements.c.id == AssertionEvidenceRecord.element_id,
        )
        .join(
            EntityMentionRecord,
            EntityMentionRecord.id == AssertionRecord.subject_mention_id,
        )
        .join(DocumentVersion, DocumentVersion.id == AssertionEvidenceRecord.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .order_by(AssertionRecord.confidence.desc())
        .limit(8),
    )
    for item in evidence_examples:
        item["evidence"] = item["evidence"][:240]

    current_documents = len(document_rows)
    current_elements_count = sum(int(row["elements"]) for row in document_rows)
    current_mentions_count = sum(int(row["mentions"]) for row in document_rows)
    current_assertions_count = len(visible_assertion_ids)
    current_evidence_rows = list(
        session.scalars(
            select(AssertionEvidenceRecord)
            .join(
                active_elements,
                active_elements.c.id == AssertionEvidenceRecord.element_id,
            )
            .distinct()
        )
    )
    current_evidence_count = len(current_evidence_rows)
    located_evidence_count = sum(
        _evidence_locator_complete(row) for row in current_evidence_rows
    )
    linked_mentions = _count(
        session,
        select(func.count(EntityMentionRecord.id))
        .join(
            active_elements,
            active_elements.c.id == EntityMentionRecord.element_id,
        )
        .where(EntityMentionRecord.entity_id.is_not(None)),
    )

    summary = {
        "sources": len(source_rows),
        "source_records": _count(
            session,
            select(func.count(func.distinct(SourceRecord.id)))
            .join(DocumentVersion, DocumentVersion.source_record_id == SourceRecord.id)
            .join(visible_versions, visible_versions.c.id == DocumentVersion.id),
        ),
        "artifacts": _count(
            session,
            select(func.count(func.distinct(RawArtifactRecord.id)))
            .join(DocumentVersion, DocumentVersion.artifact_id == RawArtifactRecord.id)
            .join(visible_versions, visible_versions.c.id == DocumentVersion.id),
        ),
        "documents": current_documents,
        "versions": _count(session, select(func.count()).select_from(visible_versions)),
        "elements": current_elements_count,
        "mentions": current_mentions_count,
        "entities": _count(
            session,
            select(func.count(func.distinct(EntityMentionRecord.entity_id)))
            .join(
                active_elements,
                active_elements.c.id == EntityMentionRecord.element_id,
            )
            .where(EntityMentionRecord.entity_id.is_not(None)),
        ),
        "assertions": current_assertions_count,
        "evidence": current_evidence_count,
        "conflicts": len(visible_conflicts),
        "access_grants": _count(
            session,
            select(func.count(DocumentAccessGrantRecord.id))
            .join(
                visible_versions,
                visible_versions.c.id == DocumentAccessGrantRecord.document_version_id,
            )
            .where(DocumentAccessGrantRecord.active.is_(True)),
        ),
        "metric_observations": _count(
            session,
            select(func.count(func.distinct(MetricObservationRecord.id)))
            .join(
                AssertionEvidenceRecord,
                AssertionEvidenceRecord.id == MetricObservationRecord.evidence_id,
            )
            .join(
                active_elements,
                active_elements.c.id == AssertionEvidenceRecord.element_id,
            ),
        ),
        "open_parse_reviews": _count(
            session,
            select(func.count(ParseReviewItemRecord.id))
            .join(
                current_versions,
                current_versions.c.id == ParseReviewItemRecord.document_version_id,
            )
            .where(
                ParseReviewItemRecord.status == "open",
                ParseReviewItemRecord.parse_run_id
                == current_versions.c.active_parse_run_id,
            ),
        ),
        "entity_link_rate": (
            round(linked_mentions / current_mentions_count, 4) if current_mentions_count else 0.0
        ),
        "assertion_evidence_rate": (
            round(current_evidence_count / current_assertions_count, 4)
            if current_assertions_count
            else 0.0
        ),
        "evidence_locator_completeness": (
            round(located_evidence_count / current_evidence_count, 4)
            if current_evidence_count
            else 0.0
        ),
    }
    review_counts = {str(item["label"]): int(item["value"]) for item in assertion_reviews}
    summary["approved_assertions"] = review_counts.get("approved", 0)
    summary["candidate_assertions"] = review_counts.get("candidate", 0)
    summary["verified_sources"] = sum(
        str(item["authority_tier"]) in {"A1", "A2"} for item in source_rows
    )
    summary["metadata_review_required"] = sum(
        bool(item["metadata_review_required"]) for item in document_rows
    )
    settings = get_settings()
    internal_scope = "restricted" in allowed_access_classes
    if settings.inbox_enabled and internal_scope:
        try:
            inbox = build_inbox_coordinator(settings).status(include_files=False)
        except Exception as exc:  # noqa: BLE001 - visualization should survive filesystem issues
            inbox = {"enabled": True, "status": "unavailable", "error": str(exc)}
    else:
        inbox = {"enabled": settings.inbox_enabled, "visible": False}
    reasoning_readiness = {
        "approved_claims": summary["approved_assertions"],
        "candidate_claims": summary["candidate_assertions"],
        "documents_with_approved_claims": sum(
            int(item["approved_assertions"]) > 0 for item in document_rows
        ),
        "documents_needing_metadata_review": summary["metadata_review_required"],
        "reasoning_ready": summary["approved_assertions"] > 0
        and summary["metadata_review_required"] == 0
        and summary["open_parse_reviews"] == 0
        and not visible_conflicts,
        "blockers": [
            code
            for condition, code in (
                (summary["approved_assertions"] == 0, "approved_claims_missing"),
                (summary["open_parse_reviews"] > 0, "parse_hard_gate_review_open"),
                (summary["metadata_review_required"] > 0, "metadata_review_open"),
                (bool(visible_conflicts), "active_conflicts_open"),
                (True, "human_gold_missing"),
            )
            if condition
        ],
        "can_use_for_formal_reasoning": False,
        "engineering_baseline_only": True,
        "gold_gate": "not_evaluated_no_human_gold",
        "interface": "/v2/reasoning/context",
    }

    mineru = mineru_status(settings)
    backend = session.get(MineruBackendRecord, settings.mineru_node_id)
    if backend is not None:
        mineru["registered_backend"] = {
            "node_id": backend.id,
            "endpoint": backend.endpoint,
            "backend": backend.backend,
            "model_version": backend.model_version,
            "health_status": backend.health_status,
            "last_health_check_at": backend.last_health_check_at,
            "allowed_access_classes": backend.allowed_access_classes,
            "metadata": backend.metadata_json,
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "access_classes": allowed_access_classes,
            "document_version_policy": "current_only",
            "historical_version_policy": "versions_jobs_runs_only",
        },
        "summary": summary,
        "pipeline": [
            {"label": "来源登记", "value": summary["sources"]},
            {"label": "来源记录", "value": summary["source_records"]},
            {"label": "原始制品", "value": summary["artifacts"]},
            {"label": "当前文档", "value": summary["documents"]},
            {"label": "解析元素", "value": summary["elements"]},
            {"label": "实体提及", "value": summary["mentions"]},
            {"label": "关系主张", "value": summary["assertions"]},
            {"label": "证据记录", "value": summary["evidence"]},
        ],
        "sources": source_rows,
        "documents": document_rows,
        "element_types": element_types,
        "entity_types": entity_types,
        "predicates": predicates,
        "parsers": parsers,
        "jobs": jobs,
        "runs": runs,
        "licenses": licenses,
        "assertion_reviews": assertion_reviews,
        "inbox": inbox,
        "reasoning_readiness": reasoning_readiness,
        "mineru": mineru,
        "conflicts": [
            {
                "id": row.id,
                "conflict_type": row.conflict_type,
                "status": row.status,
                "assertion_count": len(row.assertion_ids),
            }
            for row in visible_conflicts
        ],
        "evidence_examples": evidence_examples,
        "relation_graph": build_relation_graph(session, allowed_access_classes),
        "entity_extraction_example": build_entity_extraction_example(
            session, allowed_access_classes
        ),
    }
