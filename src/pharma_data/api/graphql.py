import strawberry
from sqlalchemy import or_, select

from pharma_data.storage.canonical import session_scope
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    ConflictGroupRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
)


@strawberry.type
class DocumentNode:
    id: str
    title: str
    document_type: str
    language: str


@strawberry.type
class EntityNode:
    id: str
    canonical_name: str
    entity_type: str
    review_status: str


@strawberry.type
class AssertionNode:
    id: str
    predicate: str
    subject_entity_id: str | None
    object_entity_id: str | None
    object_value: str | None
    review_status: str


@strawberry.type
class EvidenceNode:
    id: str
    assertion_id: str
    document_version_id: str
    text: str
    page_number: int | None


@strawberry.type
class TimelineEntry:
    assertion_id: str
    predicate: str
    event_time: str | None
    object_value: str | None


@strawberry.type
class ConflictNode:
    id: str
    conflict_type: str
    assertion_ids: list[str]
    status: str
    rationale: str


def _public_assertions():
    return (
        select(AssertionRecord)
        .join(
            AssertionEvidenceRecord,
            AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
        )
        .join(DocumentVersion, AssertionEvidenceRecord.document_version_id == DocumentVersion.id)
        .where(DocumentVersion.access_class == "public")
    )


@strawberry.type
class Query:
    @strawberry.field
    def document(self, id: str) -> DocumentNode | None:
        with session_scope() as session:
            row = session.scalar(
                select(Document)
                .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
                .where(Document.id == id, DocumentVersion.access_class == "public")
            )
            if row is None:
                return None
            return DocumentNode(
                id=row.id,
                title=row.title,
                document_type=row.document_type,
                language=row.language,
            )

    @strawberry.field
    def entity(self, id: str) -> EntityNode | None:
        with session_scope() as session:
            row = session.scalar(
                select(EntityRecord)
                .join(EntityMentionRecord, EntityMentionRecord.entity_id == EntityRecord.id)
                .join(
                    DocumentVersion,
                    EntityMentionRecord.document_version_id == DocumentVersion.id,
                )
                .where(EntityRecord.id == id, DocumentVersion.access_class == "public")
            )
            if row is None:
                return None
            return EntityNode(
                id=row.id,
                canonical_name=row.canonical_name,
                entity_type=row.entity_type,
                review_status=row.review_status,
            )

    @strawberry.field
    def entity_neighbors(
        self, id: str, relation_types: list[str] | None = None
    ) -> list[AssertionNode]:
        with session_scope() as session:
            statement = _public_assertions().where(
                or_(
                    AssertionRecord.subject_entity_id == id,
                    AssertionRecord.object_entity_id == id,
                ),
                AssertionRecord.review_status == "approved",
            )
            if relation_types:
                statement = statement.where(AssertionRecord.predicate.in_(relation_types))
            return [
                AssertionNode(
                    id=row.id,
                    predicate=row.predicate,
                    subject_entity_id=row.subject_entity_id,
                    object_entity_id=row.object_entity_id,
                    object_value=row.object_value,
                    review_status=row.review_status,
                )
                for row in session.scalars(statement)
            ]

    @strawberry.field
    def search_documents(self, query: str, limit: int = 20) -> list[DocumentNode]:
        with session_scope() as session:
            statement = (
                select(Document)
                .join(DocumentVersion, Document.current_version_id == DocumentVersion.id)
                .join(
                    DocumentElementRecord,
                    DocumentElementRecord.document_version_id == DocumentVersion.id,
                )
                .where(
                    DocumentElementRecord.text.ilike(f"%{query}%"),
                    DocumentVersion.access_class == "public",
                )
                .distinct()
                .limit(min(limit, 100))
            )
            return [
                DocumentNode(
                    id=row.id,
                    title=row.title,
                    document_type=row.document_type,
                    language=row.language,
                )
                for row in session.scalars(statement)
            ]

    @strawberry.field
    def search_evidence(self, query: str, limit: int = 20) -> list[EvidenceNode]:
        with session_scope() as session:
            statement = (
                select(AssertionEvidenceRecord)
                .join(
                    DocumentVersion,
                    AssertionEvidenceRecord.document_version_id == DocumentVersion.id,
                )
                .where(
                    AssertionEvidenceRecord.evidence_text.ilike(f"%{query}%"),
                    DocumentVersion.access_class == "public",
                )
                .limit(min(limit, 100))
            )
            return [
                EvidenceNode(
                    id=row.id,
                    assertion_id=row.assertion_id,
                    document_version_id=row.document_version_id,
                    text=row.evidence_text,
                    page_number=row.page_number,
                )
                for row in session.scalars(statement)
            ]

    @strawberry.field
    def assertion(self, id: str) -> AssertionNode | None:
        with session_scope() as session:
            row = session.scalar(_public_assertions().where(AssertionRecord.id == id))
            if row is None:
                return None
            return AssertionNode(
                id=row.id,
                predicate=row.predicate,
                subject_entity_id=row.subject_entity_id,
                object_entity_id=row.object_entity_id,
                object_value=row.object_value,
                review_status=row.review_status,
            )

    @strawberry.field
    def entity_timeline(self, id: str, limit: int = 100) -> list[TimelineEntry]:
        with session_scope() as session:
            statement = (
                _public_assertions()
                .where(
                    AssertionRecord.subject_entity_id == id,
                    AssertionRecord.review_status == "approved",
                )
                .order_by(
                    AssertionRecord.as_of_date,
                    AssertionRecord.valid_from,
                    AssertionRecord.created_at,
                )
                .limit(min(limit, 500))
            )
            return [
                TimelineEntry(
                    assertion_id=row.id,
                    predicate=row.predicate,
                    event_time=str(row.as_of_date or row.valid_from or row.created_at),
                    object_value=row.object_value,
                )
                for row in session.scalars(statement)
            ]

    @strawberry.field
    def conflict_group(self, id: str) -> ConflictNode | None:
        with session_scope() as session:
            row = session.get(ConflictGroupRecord, id)
            if row is None:
                return None
            public_ids = set(
                session.scalars(
                    _public_assertions().where(AssertionRecord.id.in_(row.assertion_ids))
                )
            )
            if {item.id for item in public_ids} != set(row.assertion_ids):
                return None
            return ConflictNode(
                id=row.id,
                conflict_type=row.conflict_type,
                assertion_ids=row.assertion_ids,
                status=row.status,
                rationale=row.rationale,
            )


schema = strawberry.Schema(query=Query)
