from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pharma_data.storage.canonical.database import Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


def new_uuid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceRegistry(Base, TimestampMixin):
    __tablename__ = "source_registry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    authority_tier: Mapped[str] = mapped_column(String(8), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    adapter_name: Mapped[str] = mapped_column(String(160), nullable=False)
    terms_url: Mapped[str | None] = mapped_column(Text)
    default_license_status: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class SourceRecord(Base, TimestampMixin):
    __tablename__ = "source_record"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external_record"),
        Index("ix_source_record_published_at", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_registry.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    license_status: Mapped[str] = mapped_column(String(40), nullable=False)
    access_class: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="DISCOVERED", nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RawArtifactRecord(Base, TimestampMixin):
    __tablename__ = "raw_artifact"
    __table_args__ = (
        UniqueConstraint("source_record_id", "content_hash", name="uq_artifact_record_hash"),
        Index("ix_raw_artifact_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("source_record.id", ondelete="CASCADE"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    object_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    license_status: Mapped[str] = mapped_column(String(40), nullable=False)
    access_class: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class Document(Base, TimestampMixin):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    stable_key: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="und", nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(36))


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_version"
    __table_args__ = (
        UniqueConstraint("document_id", "content_hash", name="uq_document_version_hash"),
        Index("ix_document_version_published_at", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("source_record.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("raw_artifact.id", ondelete="RESTRICT"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    license_status: Mapped[str] = mapped_column(String(40), nullable=False)
    access_class: Mapped[str] = mapped_column(String(40), nullable=False)
    active_parse_run_id: Mapped[str | None] = mapped_column(String(36))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class DocumentAccessGrantRecord(Base, TimestampMixin):
    """Independent authorization for a content-addressed document version."""

    __tablename__ = "document_access_grant"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "access_class", name="uq_version_access_grant"
        ),
        Index("ix_access_grant_class_active", "access_class", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    source_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_record.id", ondelete="SET NULL")
    )
    access_class: Mapped[str] = mapped_column(String(40), nullable=False)
    license_status: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance_status: Mapped[str] = mapped_column(
        String(80), default="unverified", nullable=False
    )
    authorization_reference: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class MineruBackendRecord(Base, TimestampMixin):
    __tablename__ = "mineru_backend"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    backend: Mapped[str] = mapped_column(String(80), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    model_name: Mapped[str | None] = mapped_column(String(200))
    model_version: Mapped[str | None] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    health_status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    allowed_access_classes: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    tls_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class ProcessingJob(Base, TimestampMixin):
    __tablename__ = "processing_job"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_processing_job_idempotency"),
        Index("ix_processing_job_claim", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_step: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(160))
    last_error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class ProcessingRun(Base):
    __tablename__ = "processing_run"
    __table_args__ = (Index("ix_processing_run_trace", "trace_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("processing_job.id", ondelete="CASCADE"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    producer: Mapped[str] = mapped_column(String(160), nullable=False)
    producer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    errors: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentElementRecord(Base):
    __tablename__ = "document_element"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "content_hash", "reading_order", name="uq_element_run"),
        Index("ix_document_element_version_page", "document_version_id", "page_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_run.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    element_type: Mapped[str] = mapped_column(String(40), nullable=False)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSON_TYPE)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    footnote_links: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ParseCandidateRecord(Base, TimestampMixin):
    __tablename__ = "parse_candidate"
    __table_args__ = (
        Index("ix_parse_candidate_version_page", "document_version_id", "page_number"),
        Index("ix_parse_candidate_run_selected", "parse_run_id", "selected"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_run.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    region_key: Mapped[str | None] = mapped_column(String(160))
    backend_name: Mapped[str] = mapped_column(String(120), nullable=False)
    backend_version: Mapped[str | None] = mapped_column(String(120))
    node_id: Mapped[str | None] = mapped_column(String(120))
    selected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    raw_output_path: Mapped[str | None] = mapped_column(Text)
    raw_output_hash: Mapped[str | None] = mapped_column(String(64))


class CharacterSpanRecord(Base):
    __tablename__ = "character_span"
    __table_args__ = (
        UniqueConstraint("element_id", "char_start", "char_end", name="uq_element_span"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    element_id: Mapped[str] = mapped_column(
        ForeignKey("document_element.id", ondelete="CASCADE"), nullable=False
    )
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSON_TYPE)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class TableCellRecord(Base):
    __tablename__ = "table_cell"
    __table_args__ = (
        UniqueConstraint("element_id", "row_index", "column_index", name="uq_table_cell"),
        Index("ix_table_cell_period", "period_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    element_id: Mapped[str] = mapped_column(
        ForeignKey("document_element.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    row_span: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    column_span: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSON_TYPE)
    header_path: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    numeric_value: Mapped[Any | None] = mapped_column(Numeric(38, 12))
    unit: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(20))
    scale: Mapped[str | None] = mapped_column(String(40))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ParseReviewItemRecord(Base, TimestampMixin):
    __tablename__ = "parse_review_item"
    __table_args__ = (
        Index("ix_parse_review_open", "status", "document_version_id", "page_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_run.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region_key: Mapped[str | None] = mapped_column(String(160))
    gate_code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open", nullable=False)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class AudioUtteranceRecord(Base):
    __tablename__ = "audio_utterance"
    __table_args__ = (Index("ix_audio_utterance_version_time", "document_version_id", "start_ms"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_run.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[str | None] = mapped_column(String(160))
    speaker_name: Mapped[str | None] = mapped_column(String(300))
    speaker_role: Mapped[str | None] = mapped_column(String(160))
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_transcript: Mapped[str] = mapped_column(Text, nullable=False)
    asr_confidence: Mapped[float | None] = mapped_column(Float)
    audio_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("raw_artifact.id", ondelete="RESTRICT"), nullable=False
    )
    review_status: Mapped[str] = mapped_column(String(40), nullable=False)


class EntityRecord(Base, TimestampMixin):
    __tablename__ = "entity"
    __table_args__ = (
        UniqueConstraint("entity_type", "normalized_name", name="uq_entity_type_name"),
        Index("ix_entity_external_ids", "entity_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    external_ids: Mapped[dict[str, str]] = mapped_column(JSON_TYPE, default=dict)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False)


class EntityAliasRecord(Base, TimestampMixin):
    __tablename__ = "entity_alias"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_alias", name="uq_entity_alias"),
        Index("ix_entity_alias_normalized", "normalized_alias"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(500), nullable=False)
    language: Mapped[str] = mapped_column(String(20), default="und", nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class EntityMentionRecord(Base):
    __tablename__ = "entity_mention"
    __table_args__ = (
        Index("ix_entity_mention_element", "element_id"),
        Index("ix_entity_mention_entity", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    element_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_element.id", ondelete="CASCADE")
    )
    utterance_id: Mapped[str | None] = mapped_column(
        ForeignKey("audio_utterance.id", ondelete="CASCADE")
    )
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entity.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    audio_start_ms: Mapped[int | None] = mapped_column(BigInteger)
    audio_end_ms: Mapped[int | None] = mapped_column(BigInteger)
    extraction_method: Mapped[str] = mapped_column(String(160), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    link_status: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class MetricDefinitionRecord(Base, TimestampMixin):
    __tablename__ = "metric_definition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    canonical_name: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    value_type: Mapped[str] = mapped_column(String(40), nullable=False)
    allowed_units: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    scope_rules: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    definition: Mapped[str] = mapped_column(Text, nullable=False)


class MetricObservationRecord(Base, TimestampMixin):
    __tablename__ = "metric_observation"
    __table_args__ = (Index("ix_metric_observation_entity_period", "entity_id", "period_end"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entity.id", ondelete="CASCADE"), nullable=False
    )
    metric_definition_id: Mapped[str] = mapped_column(
        ForeignKey("metric_definition.id", ondelete="RESTRICT"), nullable=False
    )
    assertion_id: Mapped[str | None] = mapped_column(String(36))
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    numeric_value: Mapped[Any | None] = mapped_column(Numeric(38, 12))
    unit: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(20))
    scale: Mapped[str | None] = mapped_column(String(40))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    as_of_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scope: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    evidence_id: Mapped[str | None] = mapped_column(String(36))
    review_status: Mapped[str] = mapped_column(String(40), nullable=False)


class AssertionRecord(Base, TimestampMixin):
    __tablename__ = "assertion"
    __table_args__ = (
        Index("ix_assertion_subject_predicate", "subject_entity_id", "predicate"),
        Index("ix_assertion_review_status", "review_status"),
        Index("ix_assertion_fact_group", "fact_group_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subject_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entity.id", ondelete="SET NULL")
    )
    subject_mention_id: Mapped[str] = mapped_column(
        ForeignKey("entity_mention.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(80), nullable=False)
    object_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entity.id", ondelete="SET NULL")
    )
    object_mention_id: Mapped[str | None] = mapped_column(
        ForeignKey("entity_mention.id", ondelete="SET NULL")
    )
    object_value: Mapped[str | None] = mapped_column(Text)
    object_unit: Mapped[str | None] = mapped_column(String(80))
    qualifiers: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    as_of_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assertion_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(160), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False)
    assertion_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_group_key: Mapped[str | None] = mapped_column(String(64))


class AssertionEvidenceRecord(Base):
    __tablename__ = "assertion_evidence"
    __table_args__ = (
        UniqueConstraint(
            "assertion_id",
            "element_id",
            "utterance_id",
            "table_cell_id",
            name="uq_assertion_evidence_locator",
        ),
        Index("ix_assertion_evidence_hash", "assertion_id", "evidence_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    assertion_id: Mapped[str] = mapped_column(
        ForeignKey("assertion.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
    )
    element_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_element.id", ondelete="CASCADE")
    )
    utterance_id: Mapped[str | None] = mapped_column(
        ForeignKey("audio_utterance.id", ondelete="CASCADE")
    )
    evidence_role: Mapped[str] = mapped_column(String(40), default="support", nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict[str, float] | None] = mapped_column(JSON_TYPE)
    char_span: Mapped[dict[str, int] | None] = mapped_column(JSON_TYPE)
    table_cell_id: Mapped[str | None] = mapped_column(
        ForeignKey("table_cell.id", ondelete="SET NULL")
    )
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    audio_range: Mapped[dict[str, int] | None] = mapped_column(JSON_TYPE)


class ConflictGroupRecord(Base, TimestampMixin):
    __tablename__ = "conflict_group"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conflict_type: Mapped[str] = mapped_column(String(80), nullable=False)
    assertion_ids: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class ReviewDecisionRecord(Base):
    __tablename__ = "review_decision"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(160), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class OutboxEventRecord(Base):
    __tablename__ = "outbox_event"
    __table_args__ = (Index("ix_outbox_unpublished", "projection", "published_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    projection: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class ProjectionCheckpointRecord(Base, TimestampMixin):
    __tablename__ = "projection_checkpoint"

    projection: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_event_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)


class DatasetSnapshotRecord(Base):
    __tablename__ = "dataset_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    specification: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    access_class: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_event"
    __table_args__ = (Index("ix_audit_event_target", "target_type", "target_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(36))
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
