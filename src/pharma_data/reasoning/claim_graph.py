from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.reasoning.models import (
    ClaimEdge,
    ClaimEdgeType,
    ClaimEvidenceLink,
    ClaimGraph,
    EvidenceRef,
    ResearchClaim,
)
from pharma_data.storage.canonical.access import version_has_access, visible_version_ids
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    ConflictGroupRecord,
    DocumentElementRecord,
    DocumentVersion,
    EntityRecord,
    SourceRecord,
    SourceRegistry,
)


def build_claim_graph(
    session: Session,
    *,
    allowed_access_classes: Iterable[str],
    review_statuses: Iterable[str] = ("approved",),
    entity_names: Iterable[str] | None = None,
) -> ClaimGraph:
    """从规范层构建有权限、有证据的主张图谱。"""
    access = tuple(allowed_access_classes)
    statuses = tuple(review_statuses)
    if not access or not statuses:
        return ClaimGraph()
    visible_versions = visible_version_ids(access).subquery()
    visible_ids = (
        select(AssertionEvidenceRecord.assertion_id)
        .join(
            visible_versions,
            visible_versions.c.id == AssertionEvidenceRecord.document_version_id,
        )
        .distinct()
    )
    assertions = list(
        session.scalars(
            select(AssertionRecord)
            .where(
                AssertionRecord.review_status.in_(statuses),
                AssertionRecord.id.in_(visible_ids),
            )
            .order_by(AssertionRecord.created_at, AssertionRecord.id)
        )
    )
    entity_ids = {
        entity_id
        for row in assertions
        for entity_id in (row.subject_entity_id, row.object_entity_id)
        if entity_id
    }
    entities = {
        row.id: row
        for row in session.scalars(select(EntityRecord).where(EntityRecord.id.in_(entity_ids)))
    }
    requested_names = {item.casefold() for item in entity_names or [] if item.strip()}
    claims = []
    for assertion in assertions:
        subject = entities.get(assertion.subject_entity_id or "")
        object_entity = entities.get(assertion.object_entity_id or "")
        if requested_names and not any(
            name and name.casefold() in requested_names
            for name in (
                subject.canonical_name if subject else None,
                object_entity.canonical_name if object_entity else None,
            )
        ):
            continue
        evidence_rows = list(
            session.scalars(
                select(AssertionEvidenceRecord).where(
                    AssertionEvidenceRecord.assertion_id == assertion.id
                )
            )
        )
        evidence_refs = []
        for evidence in evidence_rows:
            version = session.get(DocumentVersion, evidence.document_version_id)
            if version is None or not version_has_access(session, version, access):
                continue
            element = (
                session.get(DocumentElementRecord, evidence.element_id)
                if evidence.element_id
                else None
            )
            if (
                element is not None
                and version.active_parse_run_id
                and element.parse_run_id != version.active_parse_run_id
            ):
                continue
            source_record = session.get(SourceRecord, version.source_record_id)
            source = (
                session.get(SourceRegistry, source_record.source_id) if source_record else None
            )
            evidence_refs.append(
                EvidenceRef(
                    evidence_id=evidence.id,
                    evidence_hash=evidence.evidence_hash,
                    document_version_id=evidence.document_version_id,
                    source_name=source.name if source else None,
                    authority_tier=source.authority_tier if source else None,
                    published_at=version.published_at,
                    text=evidence.evidence_text,
                    page_number=evidence.page_number,
                    bbox=evidence.bbox,
                    char_span=evidence.char_span,
                    table_cell_id=evidence.table_cell_id,
                    parser_name=element.parser_name if element else None,
                    parser_version=element.parser_version if element else None,
                    parse_run_id=element.parse_run_id if element else None,
                    audio_range=evidence.audio_range,
                    visual_context=(
                        element.structured_payload.get("visual_semantics")
                        if element
                        and isinstance(element.structured_payload, dict)
                        and isinstance(
                            element.structured_payload.get("visual_semantics"), dict
                        )
                        else None
                    ),
                )
            )
        if not evidence_refs:
            continue
        claims.append(
            ResearchClaim(
                id=assertion.id,
                assertion_key=assertion.assertion_key,
                fact_group_key=assertion.fact_group_key,
                subject_entity_id=assertion.subject_entity_id,
                subject_name=subject.canonical_name if subject else None,
                subject_type=subject.entity_type if subject else None,
                predicate=assertion.predicate,
                object_entity_id=assertion.object_entity_id,
                object_name=object_entity.canonical_name if object_entity else None,
                object_value=assertion.object_value,
                object_unit=assertion.object_unit,
                qualifiers=assertion.qualifiers,
                as_of_date=assertion.as_of_date,
                confidence=assertion.confidence,
                review_status=assertion.review_status,
                evidence=evidence_refs,
            )
        )
    claim_ids = {claim.id for claim in claims}
    edges: list[ClaimEdge] = []
    edge_keys: set[tuple[str, str, str]] = set()

    equivalent: dict[tuple[object, ...], list[str]] = defaultdict(list)
    for claim in claims:
        equivalent[_claim_signature(claim)].append(claim.id)
    for group in equivalent.values():
        for source_id, target_id in zip(group, group[1:], strict=False):
            _append_edge(
                edges,
                edge_keys,
                ClaimEdge(
                    source_claim_id=source_id,
                    target_claim_id=target_id,
                    edge_type=ClaimEdgeType.SUPPORTS,
                    rationale="不同主张记录表达相同的规范化事实",
                ),
            )

    for conflict in session.scalars(select(ConflictGroupRecord)):
        members = [claim_id for claim_id in conflict.assertion_ids if claim_id in claim_ids]
        if len(members) < 2:
            continue
        edge_type = (
            ClaimEdgeType.REFUTES
            if conflict.conflict_type in {"TRUE_CONTRADICTION", "SOURCE_DISAGREEMENT"}
            else ClaimEdgeType.SUPPLEMENTS
        )
        for source_id, target_id in zip(members, members[1:], strict=False):
            _append_edge(
                edges,
                edge_keys,
                ClaimEdge(
                    source_claim_id=source_id,
                    target_claim_id=target_id,
                    edge_type=edge_type,
                    rationale=conflict.rationale,
                    conflict_group_id=conflict.id,
                ),
            )
    evidence_links = [
        ClaimEvidenceLink(claim_id=claim.id, evidence_id=evidence.evidence_id)
        for claim in claims
        for evidence in claim.evidence
    ]
    return ClaimGraph(claims=claims, edges=edges, evidence_links=evidence_links)


def _claim_signature(claim: ResearchClaim) -> tuple[object, ...]:
    return (
        claim.subject_entity_id or claim.subject_name,
        claim.predicate,
        claim.object_entity_id or claim.object_value,
        claim.object_unit,
        str(claim.qualifiers.get("metric_name") or "").casefold(),
        claim.as_of_date.isoformat() if claim.as_of_date else None,
    )


def _append_edge(
    edges: list[ClaimEdge],
    keys: set[tuple[str, str, str]],
    edge: ClaimEdge,
) -> None:
    key = (edge.source_claim_id, edge.target_claim_id, edge.edge_type.value)
    if key not in keys:
        keys.add(key)
        edges.append(edge)
