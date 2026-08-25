from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.config import Settings
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    DocumentElementRecord,
    DocumentVersion,
    EntityRecord,
    OutboxEventRecord,
)


class Neo4jProjector:
    name = "neo4j"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _driver(self) -> Any:
        from neo4j import GraphDatabase

        return GraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )

    def project(self, session: Session, event: OutboxEventRecord) -> None:
        assertion = session.get(AssertionRecord, event.aggregate_id)
        if assertion is None or assertion.review_status != "approved":
            return
        subject = (
            session.get(EntityRecord, assertion.subject_entity_id)
            if assertion.subject_entity_id
            else None
        )
        obj = (
            session.get(EntityRecord, assertion.object_entity_id)
            if assertion.object_entity_id
            else None
        )
        evidence = session.scalar(
            select(AssertionEvidenceRecord)
            .join(
                DocumentVersion,
                DocumentVersion.id == AssertionEvidenceRecord.document_version_id,
            )
            .join(
                DocumentElementRecord,
                DocumentElementRecord.id == AssertionEvidenceRecord.element_id,
            )
            .where(AssertionEvidenceRecord.assertion_id == assertion.id)
            .where(DocumentElementRecord.parse_run_id == DocumentVersion.active_parse_run_id)
            .limit(1)
        )
        if subject is None or subject.review_status != "approved":
            raise ValueError("Neo4j projection requires an approved subject entity")
        if obj is not None and obj.review_status != "approved":
            raise ValueError("Neo4j projection requires an approved object entity")
        with self._driver() as driver:
            driver.execute_query(
                """
                MERGE (s:Entity {id: $subject_id})
                SET s.name = $subject_name, s.entity_type = $subject_type
                MERGE (a:Assertion {id: $assertion_id})
                SET a.predicate = $predicate,
                    a.mode = $mode,
                    a.confidence = $confidence,
                    a.qualifiers = $qualifiers
                MERGE (s)-[:SUBJECT_OF]->(a)
                WITH a
                FOREACH (_ IN CASE WHEN $object_id IS NULL THEN [] ELSE [1] END |
                  MERGE (o:Entity {id: $object_id})
                  SET o.name = $object_name, o.entity_type = $object_type
                  MERGE (a)-[:OBJECT]->(o)
                )
                MERGE (e:Evidence {id: $evidence_id})
                SET e.text = $evidence_text,
                    e.document_version_id = $document_version_id,
                    e.page_number = $page_number
                MERGE (a)-[:SUPPORTED_BY]->(e)
                """,
                subject_id=subject.id,
                subject_name=subject.canonical_name,
                subject_type=subject.entity_type,
                assertion_id=assertion.id,
                predicate=assertion.predicate,
                mode=assertion.assertion_mode,
                confidence=assertion.confidence,
                qualifiers=str(assertion.qualifiers),
                object_id=obj.id if obj else None,
                object_name=obj.canonical_name if obj else assertion.object_value,
                object_type=obj.entity_type if obj else "Literal",
                evidence_id=evidence.id if evidence else f"missing:{assertion.id}",
                evidence_text=evidence.evidence_text if evidence else "",
                document_version_id=evidence.document_version_id if evidence else None,
                page_number=evidence.page_number if evidence else None,
                database_="neo4j",
            )

    def rebuild(self, session: Session) -> dict[str, int]:
        assertions = list(
            session.scalars(
                select(AssertionRecord)
                .join(
                    AssertionEvidenceRecord,
                    AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
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
                    AssertionRecord.review_status == "approved",
                    DocumentElementRecord.parse_run_id
                    == DocumentVersion.active_parse_run_id,
                )
                .distinct()
            )
        )
        with self._driver() as driver:
            driver.execute_query("MATCH (n) DETACH DELETE n", database_="neo4j")
        for assertion in assertions:
            self.project(
                session,
                OutboxEventRecord(
                    aggregate_type="assertion",
                    aggregate_id=assertion.id,
                    event_type="assertion.approved",
                    projection=self.name,
                    payload={"assertion_id": assertion.id},
                ),
            )
        return {"assertions": len(assertions)}
