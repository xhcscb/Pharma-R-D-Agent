from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator

from pharma_data.contracts.enums import (
    AccessClass,
    AssertionMode,
    ConflictStatus,
    ConflictType,
    DocumentType,
    ElementType,
    EntityType,
    LicenseStatus,
    PipelineStatus,
    QualityLevel,
    RelationType,
    ReviewStatus,
)


def new_id() -> str:
    return str(uuid4())


class SourceRecordEnvelope(BaseModel):
    source_name: str
    source_record_id: str
    canonical_url: HttpUrl | None = None
    title: str
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_urls: list[HttpUrl] = Field(default_factory=list)
    license_status: LicenseStatus
    access_class: AccessClass
    document_type: DocumentType
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRecordPage(BaseModel):
    records: list[SourceRecordEnvelope]
    next_cursor: str | None = None


class SourceCheckpoint(BaseModel):
    source_name: str
    cursor: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RawArtifact(BaseModel):
    artifact_id: str = Field(default_factory=new_id)
    source_record_id: str
    media_type: str
    local_path: str
    content_hash: str
    size_bytes: int = Field(ge=0)
    license_status: LicenseStatus
    access_class: AccessClass
    original_url: HttpUrl | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @field_validator("x1")
    @classmethod
    def x1_after_x0(cls, value: float, info: Any) -> float:
        x0 = info.data.get("x0")
        if x0 is not None and value < x0:
            raise ValueError("x1 must be greater than or equal to x0")
        return value

    @field_validator("y1")
    @classmethod
    def y1_after_y0(cls, value: float, info: Any) -> float:
        y0 = info.data.get("y0")
        if y0 is not None and value < y0:
            raise ValueError("y1 must be greater than or equal to y0")
        return value


class DocumentElement(BaseModel):
    element_id: str = Field(default_factory=new_id)
    document_version_id: str
    page_number: int | None = Field(default=None, ge=1)
    element_type: ElementType
    bbox: BoundingBox | None = None
    reading_order: int = Field(ge=0)
    text: str = ""
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    footnote_links: list[str] = Field(default_factory=list)
    parser_name: str
    parser_version: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    content_hash: str


class AudioUtterance(BaseModel):
    utterance_id: str = Field(default_factory=new_id)
    document_version_id: str
    speaker_id: str | None = None
    speaker_name: str | None = None
    speaker_role: str | None = None
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    raw_transcript: str
    normalized_transcript: str
    asr_confidence: float | None = Field(default=None, ge=0, le=1)
    audio_artifact_id: str
    review_status: ReviewStatus = ReviewStatus.CANDIDATE

    @field_validator("end_ms")
    @classmethod
    def end_after_start(cls, value: int, info: Any) -> int:
        start = info.data.get("start_ms")
        if start is not None and value < start:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        return value


class ParsedDocument(BaseModel):
    document_id: str
    document_version_id: str
    document_type: DocumentType
    language: str = "und"
    metadata: dict[str, Any] = Field(default_factory=dict)
    elements: list[DocumentElement] = Field(default_factory=list)
    utterances: list[AudioUtterance] = Field(default_factory=list)
    parse_quality: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EntityMention(BaseModel):
    mention_id: str = Field(default_factory=new_id)
    entity_type: EntityType
    original_text: str
    normalized_name: str
    canonical_entity_id: str | None = None
    element_id: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    audio_start_ms: int | None = Field(default=None, ge=0)
    audio_end_ms: int | None = Field(default=None, ge=0)
    extraction_method: str
    confidence: float = Field(ge=0, le=1)
    link_status: ReviewStatus = ReviewStatus.CANDIDATE
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssertionCandidate(BaseModel):
    assertion_id: str = Field(default_factory=new_id)
    subject_mention_id: str
    predicate: RelationType
    object_mention_id: str | None = None
    object_value: str | None = None
    object_unit: str | None = None
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    as_of_date: datetime | None = None
    assertion_mode: AssertionMode = AssertionMode.STATED
    evidence_element_id: str | None = None
    evidence_utterance_id: str | None = None
    evidence_text: str
    extraction_method: str
    confidence: float = Field(ge=0, le=1)
    review_status: ReviewStatus = ReviewStatus.CANDIDATE


class ConflictRecord(BaseModel):
    conflict_id: str = Field(default_factory=new_id)
    conflict_type: ConflictType
    assertion_ids: list[str]
    status: ConflictStatus = ConflictStatus.OPEN
    rationale: str


class CleanResult(BaseModel):
    document_version_id: str
    mentions: list[EntityMention]
    assertions: list[AssertionCandidate]
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    quality_level: QualityLevel
    normalization_log: list[dict[str, Any]] = Field(default_factory=list)


class AgentEnvelope(BaseModel):
    job_id: str = Field(default_factory=new_id)
    trace_id: str = Field(default_factory=new_id)
    document_id: str
    document_version_id: str
    schema_version: str = "1.0"
    producer: str
    producer_version: str
    input_hash: str
    output_hash: str | None = None
    status: PipelineStatus
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
