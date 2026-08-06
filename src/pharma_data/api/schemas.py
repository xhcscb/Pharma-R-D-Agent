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
