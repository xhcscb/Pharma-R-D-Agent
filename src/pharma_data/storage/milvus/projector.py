import hashlib
import math

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
from pharma_data.utils.hashing import stable_hash


class HashingEmbedder:
    """Deterministic retrieval baseline with explicit model provenance."""

    name = "hashing-baseline-v1"
    version = "1"

    def __init__(self, dimension: int):
        self.dimension = dimension

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        normalized = text.casefold()
        grams = [normalized[index : index + 3] for index in range(max(len(normalized) - 2, 1))]
        for gram in grams:
            digest = hashlib.sha256(gram.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class MilvusProjector:
    name = "milvus"
    collections = (
        "document_chunks",
        "entity_descriptions",
        "assertion_evidence",
    )

    def __init__(self, settings: Settings):
        self.settings = settings
        self.embedder = HashingEmbedder(settings.embedding_dimension)

    def _client(self):
        from pymilvus import MilvusClient

        return MilvusClient(uri=self.settings.milvus_uri)

    def _ensure_collections(self, client) -> None:
        for collection in self.collections:
            if client.has_collection(collection):
                continue
            client.create_collection(
                collection_name=collection,
                dimension=self.settings.embedding_dimension,
                metric_type="COSINE",
                auto_id=False,
                id_type="string",
                max_length=64,
                enable_dynamic_field=True,
            )

    def _vector_record(
        self,
        *,
        record_id: str,
        text: str,
        access_class: str,
        extra: dict[str, object],
    ) -> dict[str, object]:
        return {
            "id": record_id,
            "vector": self.embedder.encode(text),
            "text": text,
            "embedding_model": self.embedder.name,
            "embedding_version": self.embedder.version,
            "configured_semantic_model": self.settings.embedding_model,
            "dimension": self.settings.embedding_dimension,
            "content_hash": stable_hash(text),
            "access_class": access_class,
            **extra,
        }

    def project(self, session: Session, event: OutboxEventRecord) -> None:
        assertion = session.get(AssertionRecord, event.aggregate_id)
        if assertion is None or assertion.review_status != "approved":
            raise ValueError("Only approved assertions may be projected")
        evidence = session.scalar(
            select(AssertionEvidenceRecord)
            .where(AssertionEvidenceRecord.assertion_id == assertion.id)
            .limit(1)
        )
        if evidence is None:
            raise ValueError("Approved assertion has no evidence")
        version = session.get(DocumentVersion, evidence.document_version_id)
        access_class = version.access_class if version else "restricted"
        client = self._client()
        self._ensure_collections(client)
        client.upsert(
            collection_name="assertion_evidence",
            data=[
                self._vector_record(
                    record_id=evidence.id,
                    text=evidence.evidence_text,
                    access_class=access_class,
                    extra={
                        "assertion_id": assertion.id,
                        "document_version_id": evidence.document_version_id,
                    },
                )
            ],
        )

    def rebuild(self, session: Session) -> dict[str, int]:
        client = self._client()
        for collection in self.collections:
            if client.has_collection(collection):
                client.drop_collection(collection)
        self._ensure_collections(client)

        chunk_count = 0
        for element, version in session.execute(
            select(DocumentElementRecord, DocumentVersion).join(
                DocumentVersion,
                DocumentElementRecord.document_version_id == DocumentVersion.id,
            )
        ):
            if not element.text.strip():
                continue
            client.upsert(
                collection_name="document_chunks",
                data=[
                    self._vector_record(
                        record_id=element.id,
                        text=element.text,
                        access_class=version.access_class,
                        extra={
                            "document_version_id": version.id,
                            "element_type": element.element_type,
                            "page_number": element.page_number,
                        },
                    )
                ],
            )
            chunk_count += 1

        entity_count = 0
        for entity in session.scalars(
            select(EntityRecord).where(EntityRecord.review_status == "approved")
        ):
            client.upsert(
                collection_name="entity_descriptions",
                data=[
                    self._vector_record(
                        record_id=entity.id,
                        text=entity.canonical_name,
                        access_class="restricted",
                        extra={"entity_type": entity.entity_type},
                    )
                ],
            )
            entity_count += 1

        assertions = list(
            session.scalars(
                select(AssertionRecord).where(AssertionRecord.review_status == "approved")
            )
        )
        for assertion in assertions:
            self.project(
                session,
                OutboxEventRecord(
                    aggregate_type="assertion",
                    aggregate_id=assertion.id,
                    event_type="assertion.approved",
                    projection=self.name,
                    payload={},
                ),
            )
        return {
            "document_chunks": chunk_count,
            "entity_descriptions": entity_count,
            "assertion_evidence": len(assertions),
        }
