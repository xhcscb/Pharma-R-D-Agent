from typing import Any

from pydantic import BaseModel, Field

from pharma_data.contracts import AccessClass, ReviewStatus


class IngestionRequest(BaseModel):
    source_type: str
    query: dict[str, Any] = Field(default_factory=dict)
    max_pages: int | None = Field(default=None, ge=1)


class ReprocessRequest(BaseModel):
    pipeline_step: str = "full_pipeline"
    configuration: dict[str, Any] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    decision: ReviewStatus
    reviewer: str
    rationale: str


class ReviewSubmissionRequest(ReviewRequest):
    target_type: str
    target_id: str


class SearchRequest(BaseModel):
    query: str
    access_class: AccessClass = AccessClass.PUBLIC
    document_types: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=200)


class SnapshotRequest(BaseModel):
    name: str
    document_version_ids: list[str]
    access_class: AccessClass
    created_by: str
    specification: dict[str, Any] = Field(default_factory=dict)


class CompareRequest(BaseModel):
    query: str = Field(min_length=1)
    objects: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time: str | None = None
    scope: str | None = None
    access_class: AccessClass = AccessClass.RESTRICTED
    include_candidates: bool = False


class SummarizeRequest(BaseModel):
    entity: str | None = None
    max_claims: int = Field(default=12, ge=1, le=100)
    access_class: AccessClass = AccessClass.RESTRICTED
    include_candidates: bool = False


class ReasoningContextRequest(BaseModel):
    entity_names: list[str] = Field(default_factory=list)
    access_class: AccessClass = AccessClass.RESTRICTED
    include_candidates: bool = False


class InboxRunRequest(BaseModel):
    run_pipeline: bool = False
    max_files: int | None = Field(default=None, ge=1, le=1000)
