from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.config import Settings
from pharma_data.storage.canonical.access import version_access_classes
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    AudioUtteranceRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    OutboxEventRecord,
)


class ElasticsearchProjector:
    name = "elasticsearch"
    indices = (
        "documents",
        "document_elements",
        "news_articles",
        "earnings_call_utterances",
    )

    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self) -> Any:
        from elasticsearch import Elasticsearch

        return Elasticsearch(self.settings.elasticsearch_url)

    def _ensure_indices(self, client: Any) -> None:
        mappings = {
            "documents": {
                "title": {"type": "text"},
                "document_type": {"type": "keyword"},
                "access_class": {"type": "keyword"},
                "access_classes": {"type": "keyword"},
                "published_at": {"type": "date"},
            },
            "document_elements": {
                "text": {"type": "text"},
                "element_type": {"type": "keyword"},
                "access_class": {"type": "keyword"},
                "access_classes": {"type": "keyword"},
                "document_version_id": {"type": "keyword"},
                "page_number": {"type": "integer"},
                "assertion_id": {"type": "keyword"},
            },
            "news_articles": {
                "title": {"type": "text"},
                "body": {"type": "text"},
                "access_class": {"type": "keyword"},
                "published_at": {"type": "date"},
            },
            "earnings_call_utterances": {
                "text": {"type": "text"},
                "speaker_name": {"type": "keyword"},
                "speaker_role": {"type": "keyword"},
                "access_class": {"type": "keyword"},
                "start_ms": {"type": "long"},
                "end_ms": {"type": "long"},
            },
        }
        for index, properties in mappings.items():
            if not client.indices.exists(index=index):
                client.indices.create(index=index, mappings={"properties": properties})

    def project(self, session: Session, event: OutboxEventRecord) -> None:
        assertion = session.get(AssertionRecord, event.aggregate_id)
        if assertion is None or assertion.review_status != "approved":
            raise ValueError("Only approved assertions may be projected")
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
        if evidence is None:
            raise ValueError("Approved assertion has no evidence")
        version = session.get(DocumentVersion, evidence.document_version_id)
        client = self._client()
        self._ensure_indices(client)
        client.index(
            index="document_elements",
            id=f"assertion:{evidence.id}",
            document={
                "assertion_id": assertion.id,
                "predicate": assertion.predicate,
                "text": evidence.evidence_text,
                "document_version_id": evidence.document_version_id,
                "page_number": evidence.page_number,
                "bbox": evidence.bbox,
                "access_class": version.access_class if version else "restricted",
                "access_classes": (
                    version_access_classes(session, version) if version else []
                ),
                "record_kind": "assertion_evidence",
            },
            refresh=False,
        )

    def rebuild(self, session: Session) -> dict[str, int]:
        client = self._client()
        for index in self.indices:
            if client.indices.exists(index=index):
                client.indices.delete(index=index)
        self._ensure_indices(client)
        counts = {index: 0 for index in self.indices}

        documents = list(
            session.execute(
                select(Document, DocumentVersion).join(
                    DocumentVersion,
                    Document.current_version_id == DocumentVersion.id,
                )
            )
        )
        for document, version in documents:
            client.index(
                index="documents",
                id=document.id,
                document={
                    "title": document.title,
                    "document_type": document.document_type,
                    "document_version_id": version.id,
                    "published_at": version.published_at,
                    "access_class": version.access_class,
                    "access_classes": version_access_classes(session, version),
                    "license_status": version.license_status,
                },
                refresh=False,
            )
            counts["documents"] += 1

            elements = list(
                session.scalars(
                    select(DocumentElementRecord).where(
                        DocumentElementRecord.document_version_id == version.id,
                        DocumentElementRecord.parse_run_id == version.active_parse_run_id,
                    )
                )
            )
            for element in elements:
                payload = {
                    "document_id": document.id,
                    "document_version_id": version.id,
                    "text": element.text,
                    "element_type": element.element_type,
                    "page_number": element.page_number,
                    "bbox": element.bbox,
                    "access_class": version.access_class,
                    "access_classes": version_access_classes(session, version),
                }
                client.index(
                    index="document_elements",
                    id=element.id,
                    document=payload,
                    refresh=False,
                )
                counts["document_elements"] += 1
            if document.document_type == "news":
                client.index(
                    index="news_articles",
                    id=version.id,
                    document={
                        "document_id": document.id,
                        "title": document.title,
                        "body": "\n".join(item.text for item in elements),
                        "published_at": version.published_at,
                        "access_class": version.access_class,
                        "access_classes": version_access_classes(session, version),
                    },
                    refresh=False,
                )
                counts["news_articles"] += 1

            for utterance in session.scalars(
                select(AudioUtteranceRecord).where(
                    AudioUtteranceRecord.document_version_id == version.id,
                    AudioUtteranceRecord.parse_run_id == version.active_parse_run_id,
                )
            ):
                client.index(
                    index="earnings_call_utterances",
                    id=utterance.id,
                    document={
                        "document_id": document.id,
                        "document_version_id": version.id,
                        "text": utterance.normalized_transcript,
                        "speaker_name": utterance.speaker_name,
                        "speaker_role": utterance.speaker_role,
                        "start_ms": utterance.start_ms,
                        "end_ms": utterance.end_ms,
                        "access_class": version.access_class,
                        "access_classes": version_access_classes(session, version),
                    },
                    refresh=False,
                )
                counts["earnings_call_utterances"] += 1

        for index in self.indices:
            client.indices.refresh(index=index)
        return counts
