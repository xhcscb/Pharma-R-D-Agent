from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
)


def _current_versions(allowed_access_classes: list[str]) -> Any:
    return (
        select(DocumentVersion.id.label("id"))
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(DocumentVersion.access_class.in_(allowed_access_classes))
        .subquery()
    )


def build_relation_graph(
    session: Session,
    allowed_access_classes: list[str],
    max_edges: int = 80,
) -> dict[str, Any]:
    """构建用于检查候选关系的轻量图，而不是已批准知识图谱。"""
    current_versions = _current_versions(allowed_access_classes)
    subject = aliased(EntityMentionRecord)
    object_mention = aliased(EntityMentionRecord)
    rows = session.execute(
        select(
            AssertionRecord.id.label("assertion_id"),
            AssertionRecord.predicate,
            AssertionRecord.object_value,
            AssertionRecord.object_unit,
            AssertionRecord.confidence,
            AssertionRecord.review_status,
            subject.entity_id.label("subject_entity_id"),
            subject.normalized_name.label("subject_name"),
            subject.entity_type.label("subject_type"),
            object_mention.entity_id.label("object_entity_id"),
            object_mention.normalized_name.label("object_name"),
            object_mention.entity_type.label("object_type"),
            AssertionEvidenceRecord.page_number,
            AssertionEvidenceRecord.evidence_text,
            Document.id.label("document_id"),
            Document.title.label("document_title"),
        )
        .join(
            AssertionEvidenceRecord,
            AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
        )
        .join(
            current_versions,
            current_versions.c.id == AssertionEvidenceRecord.document_version_id,
        )
        .join(subject, subject.id == AssertionRecord.subject_mention_id)
        .outerjoin(object_mention, object_mention.id == AssertionRecord.object_mention_id)
        .join(DocumentVersion, DocumentVersion.id == AssertionEvidenceRecord.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .order_by(AssertionRecord.confidence.desc())
        .limit(1000)
    )

    mention_counts: dict[str, int] = {
        str(entity_id): int(count)
        for entity_id, count in session.execute(
            select(
                EntityMentionRecord.entity_id,
                func.count(EntityMentionRecord.id),
            )
            .join(
                current_versions,
                current_versions.c.id == EntityMentionRecord.document_version_id,
            )
            .where(EntityMentionRecord.entity_id.is_not(None))
            .group_by(EntityMentionRecord.entity_id)
        )
        if entity_id is not None
    }

    nodes: dict[str, dict[str, Any]] = {}
    grouped_edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    value_edges: list[dict[str, Any]] = []

    for row in rows:
        if not row.subject_entity_id:
            continue
        source_id = f"entity:{row.subject_entity_id}"
        nodes[source_id] = {
            "id": source_id,
            "entity_id": row.subject_entity_id,
            "label": row.subject_name[:80],
            "type": row.subject_type,
            "mentions": int(mention_counts.get(row.subject_entity_id, 0)),
        }

        if row.object_entity_id:
            target_id = f"entity:{row.object_entity_id}"
            nodes[target_id] = {
                "id": target_id,
                "entity_id": row.object_entity_id,
                "label": row.object_name[:80],
                "type": row.object_type,
                "mentions": int(mention_counts.get(row.object_entity_id, 0)),
            }
            key = (source_id, row.predicate, target_id)
            edge = grouped_edges.get(key)
            if edge is None:
                grouped_edges[key] = {
                    "id": row.assertion_id,
                    "source": source_id,
                    "target": target_id,
                    "predicate": row.predicate,
                    "count": 1,
                    "confidence": round(float(row.confidence), 3),
                    "review_status": row.review_status,
                    "page_number": row.page_number,
                    "evidence": row.evidence_text[:260],
                    "document_id": row.document_id,
                    "document_title": row.document_title,
                    "is_self": source_id == target_id,
                }
            else:
                edge["count"] += 1
                edge["confidence"] = round(
                    max(float(edge["confidence"]), float(row.confidence)), 3
                )
        elif row.object_value:
            target_id = f"value:{row.assertion_id}"
            value_label = str(row.object_value)
            if row.object_unit:
                value_label = f"{value_label} {row.object_unit}"
            nodes[target_id] = {
                "id": target_id,
                "entity_id": None,
                "label": value_label[:80],
                "type": "MetricValue",
                "mentions": 1,
            }
            value_edges.append(
                {
                    "id": row.assertion_id,
                    "source": source_id,
                    "target": target_id,
                    "predicate": row.predicate,
                    "count": 1,
                    "confidence": round(float(row.confidence), 3),
                    "review_status": row.review_status,
                    "page_number": row.page_number,
                    "evidence": row.evidence_text[:260],
                    "document_id": row.document_id,
                    "document_title": row.document_title,
                    "is_self": False,
                }
            )

    entity_edges = sorted(
        grouped_edges.values(),
        key=lambda item: (int(item["count"]), float(item["confidence"])),
        reverse=True,
    )
    value_edges.sort(key=lambda item: float(item["confidence"]), reverse=True)
    value_edge_limit = min(12, max_edges // 4)
    selected_edges = (
        entity_edges[: max_edges - value_edge_limit] + value_edges[:value_edge_limit]
    )
    selected_node_ids = {
        node_id
        for edge in selected_edges
        for node_id in (str(edge["source"]), str(edge["target"]))
    }
    selected_nodes = [nodes[node_id] for node_id in selected_node_ids]
    selected_nodes.sort(key=lambda item: (str(item["type"]), str(item["label"])))

    relation_counts: dict[str, int] = defaultdict(int)
    for edge in selected_edges:
        relation_counts[str(edge["predicate"])] += int(edge["count"])

    return {
        "kind": "candidate_assertion_graph",
        "nodes": selected_nodes,
        "edges": selected_edges,
        "relation_counts": [
            {"label": label, "value": value}
            for label, value in sorted(
                relation_counts.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "hidden_self_edges": sum(1 for edge in selected_edges if edge["is_self"]),
    }


def build_entity_extraction_example(
    session: Session,
    allowed_access_classes: list[str],
) -> dict[str, Any] | None:
    """选择实体类型最丰富的表格元素，返回字符级定位样例。"""
    current_versions = _current_versions(allowed_access_classes)
    top_element = session.execute(
        select(
            DocumentElementRecord.id,
            func.count(EntityMentionRecord.id).label("mention_count"),
            func.count(func.distinct(EntityMentionRecord.entity_type)).label("type_count"),
        )
        .join(
            EntityMentionRecord,
            EntityMentionRecord.element_id == DocumentElementRecord.id,
        )
        .join(
            current_versions,
            current_versions.c.id == DocumentElementRecord.document_version_id,
        )
        .where(DocumentElementRecord.element_type == "table")
        .group_by(DocumentElementRecord.id)
        .order_by(
            func.count(func.distinct(EntityMentionRecord.entity_type)).desc(),
            func.count(EntityMentionRecord.id).desc(),
        )
        .limit(1)
    ).first()
    if top_element is None:
        return None

    element = session.get(DocumentElementRecord, top_element.id)
    if element is None:
        return None
    version = session.get(DocumentVersion, element.document_version_id)
    if version is None:
        return None
    document = session.get(Document, version.document_id)
    if document is None:
        return None

    text = element.text[:5000]
    mentions = [
        {
            "id": row.id,
            "entity_id": row.entity_id,
            "type": row.entity_type,
            "text": row.original_text,
            "normalized_name": row.normalized_name,
            "char_start": row.char_start,
            "char_end": row.char_end,
            "confidence": round(float(row.confidence), 3),
            "link_status": row.link_status,
        }
        for row in session.scalars(
            select(EntityMentionRecord)
            .where(EntityMentionRecord.element_id == element.id)
            .order_by(EntityMentionRecord.char_start, EntityMentionRecord.char_end)
        )
        if row.char_start is not None
        and row.char_end is not None
        and row.char_start < len(text)
        and row.char_end <= len(text)
    ]

    return {
        "document_id": document.id,
        "document_title": document.title,
        "document_version_id": version.id,
        "element_id": element.id,
        "element_type": element.element_type,
        "page_number": element.page_number,
        "bbox": element.bbox,
        "parser_name": element.parser_name,
        "parser_version": element.parser_version,
        "parser_confidence": round(float(element.confidence), 3),
        "text": text,
        "mention_count": int(top_element.mention_count),
        "displayed_mention_count": len(mentions),
        "entity_type_count": int(top_element.type_count),
        "mentions": mentions,
    }
