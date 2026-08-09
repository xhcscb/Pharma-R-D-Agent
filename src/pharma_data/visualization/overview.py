from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    ConflictGroupRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
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


def build_data_layer_overview(
    session: Session,
    allowed_access_classes: list[str],
) -> dict[str, Any]:
    """返回按调用者权限过滤的数据层总览。

    文档、元素、实体和关系统计只计算每份文档的当前版本；版本、任务和运行统计
    保留历史记录。这样既避免动态网页版本重复放大业务数据，也能展示版本血缘。
    """
    visible_versions = (
        select(DocumentVersion.id.label("id"))
        .where(DocumentVersion.access_class.in_(allowed_access_classes))
        .subquery()
    )
    current_versions = (
        select(DocumentVersion.id.label("id"))
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(DocumentVersion.access_class.in_(allowed_access_classes))
        .subquery()
    )

    visible_assertion_ids = set(
        session.scalars(
            select(AssertionEvidenceRecord.assertion_id)
            .join(
                current_versions,
                current_versions.c.id == AssertionEvidenceRecord.document_version_id,
            )
            .distinct()
        )
    )
    visible_conflicts = [
        row
        for row in session.scalars(select(ConflictGroupRecord))
        if row.assertion_ids and set(row.assertion_ids).issubset(visible_assertion_ids)
    ]

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
        .group_by(DocumentElementRecord.document_version_id)
        .subquery()
    )
    mention_counts = (
        select(
            EntityMentionRecord.document_version_id.label("version_id"),
            func.count(EntityMentionRecord.id).label("mentions"),
        )
        .join(
            current_versions,
            current_versions.c.id == EntityMentionRecord.document_version_id,
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
            current_versions,
            current_versions.c.id == AssertionEvidenceRecord.document_version_id,
        )
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
            func.coalesce(element_counts.c.elements, 0).label("elements"),
            func.coalesce(mention_counts.c.mentions, 0).label("mentions"),
            func.coalesce(assertion_counts.c.assertions, 0).label("assertions"),
        )
        .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
        .join(current_versions, current_versions.c.id == DocumentVersion.id)
        .join(SourceRecord, SourceRecord.id == DocumentVersion.source_record_id)
        .join(SourceRegistry, SourceRegistry.id == SourceRecord.source_id)
        .outerjoin(element_counts, element_counts.c.version_id == DocumentVersion.id)
        .outerjoin(mention_counts, mention_counts.c.version_id == DocumentVersion.id)
        .outerjoin(assertion_counts, assertion_counts.c.version_id == DocumentVersion.id)
        .order_by(func.coalesce(element_counts.c.elements, 0).desc()),
    )

    element_types = _grouped_counts(
        session,
        select(
            DocumentElementRecord.element_type.label("label"),
            func.count(DocumentElementRecord.id).label("value"),
            func.round(func.avg(DocumentElementRecord.confidence), 3).label("confidence"),
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
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
            func.round(func.avg(EntityMentionRecord.confidence), 3).label("confidence"),
        )
        .join(
            current_versions,
            current_versions.c.id == EntityMentionRecord.document_version_id,
        )
        .group_by(EntityMentionRecord.entity_type)
        .order_by(func.count(EntityMentionRecord.id).desc()),
    )
    predicates = _grouped_counts(
        session,
        select(
            AssertionRecord.predicate.label("label"),
            func.count(func.distinct(AssertionRecord.id)).label("value"),
            func.round(func.avg(AssertionRecord.confidence), 3).label("confidence"),
            AssertionRecord.review_status,
        )
        .join(
            AssertionEvidenceRecord,
            AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
        )
        .join(
            current_versions,
            current_versions.c.id == AssertionEvidenceRecord.document_version_id,
        )
        .group_by(AssertionRecord.predicate, AssertionRecord.review_status)
        .order_by(func.count(func.distinct(AssertionRecord.id)).desc()),
    )
    parsers = _grouped_counts(
        session,
        select(
            DocumentElementRecord.parser_name.label("label"),
            func.count(DocumentElementRecord.id).label("value"),
            func.round(func.avg(DocumentElementRecord.confidence), 3).label("confidence"),
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
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
            current_versions,
            current_versions.c.id == AssertionEvidenceRecord.document_version_id,
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
            current_versions,
            current_versions.c.id == AssertionEvidenceRecord.document_version_id,
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
    current_evidence_count = _count(
        session,
        select(func.count(AssertionEvidenceRecord.id)).join(
            current_versions,
            current_versions.c.id == AssertionEvidenceRecord.document_version_id,
        ),
    )
    linked_mentions = _count(
        session,
        select(func.count(EntityMentionRecord.id))
        .join(
            current_versions,
            current_versions.c.id == EntityMentionRecord.document_version_id,
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
                current_versions,
                current_versions.c.id == EntityMentionRecord.document_version_id,
            )
            .where(EntityMentionRecord.entity_id.is_not(None)),
        ),
        "assertions": current_assertions_count,
        "evidence": current_evidence_count,
        "conflicts": len(visible_conflicts),
        "entity_link_rate": (
            round(linked_mentions / current_mentions_count, 4) if current_mentions_count else 0.0
        ),
        "assertion_evidence_rate": (
            round(current_evidence_count / current_assertions_count, 4)
            if current_assertions_count
            else 0.0
        ),
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
            {"label": "权威来源", "value": summary["sources"]},
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
