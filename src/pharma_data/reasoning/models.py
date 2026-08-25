from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ClaimEdgeType(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    CITES = "cites"
    SUPPLEMENTS = "supplements"


class GateAction(StrEnum):
    PASS = "pass"
    REVISE = "revise"
    FLAG_CONFLICT = "flag_conflict"
    ABSTAIN = "abstain"


class RiskType(StrEnum):
    NUMERIC = "numeric"
    STAGE = "stage"
    REGULATORY = "regulatory"
    STRONG_JUDGMENT = "strong_judgment"
    GENERAL = "general"


class ClaimPosture(StrEnum):
    CONSENSUS = "consensus"
    CONFLICT = "conflict"
    PENDING = "pending"


class MetricDimension(BaseModel):
    id: str
    name: str
    parent: str
    entity_types: list[str]
    predicates: list[str]
    metric_names: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    value_type: str
    allowed_units: list[str] = Field(default_factory=list)
    investment_importance: float = Field(ge=0, le=1)
    definition: str


class EvidenceRef(BaseModel):
    evidence_id: str
    evidence_hash: str | None = None
    document_version_id: str
    source_name: str | None = None
    authority_tier: str | None = None
    published_at: datetime | None = None
    text: str
    page_number: int | None = None
    bbox: dict[str, float] | None = None
    char_span: dict[str, int] | None = None
    table_cell_id: str | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    parse_run_id: str | None = None
    audio_range: dict[str, int] | None = None
    visual_context: dict[str, Any] | None = None


class ResearchClaim(BaseModel):
    id: str
    assertion_key: str | None = None
    fact_group_key: str | None = None
    subject_entity_id: str | None = None
    subject_name: str | None = None
    subject_type: str | None = None
    predicate: str
    object_entity_id: str | None = None
    object_name: str | None = None
    object_value: str | None = None
    object_unit: str | None = None
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    as_of_date: datetime | None = None
    confidence: float
    review_status: str
    evidence: list[EvidenceRef] = Field(default_factory=list)

    @property
    def displayed_value(self) -> str | None:
        return self.object_value or self.object_name


class ClaimEdge(BaseModel):
    source_claim_id: str
    target_claim_id: str
    edge_type: ClaimEdgeType
    rationale: str
    conflict_group_id: str | None = None


class ClaimEvidenceLink(BaseModel):
    claim_id: str
    evidence_id: str
    edge_type: ClaimEdgeType = ClaimEdgeType.CITES


class ClaimGraph(BaseModel):
    claims: list[ResearchClaim] = Field(default_factory=list)
    edges: list[ClaimEdge] = Field(default_factory=list)
    evidence_links: list[ClaimEvidenceLink] = Field(default_factory=list)


class GateDecision(BaseModel):
    claim_id: str
    action: GateAction
    risk_type: RiskType
    reasons: list[str]


class CompareDSL(BaseModel):
    objects: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(min_length=1)
    time: str | None = None
    scope: str | None = None
    output_goal: str = "evidence_aligned_comparison"


class ComparisonCell(BaseModel):
    object_name: str
    dimension_id: str
    values: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    gate_actions: list[GateAction] = Field(default_factory=list)
    missing_reason: str | None = None


class CompareResult(BaseModel):
    dsl: CompareDSL
    cells: list[ComparisonCell]
    coverage: float = Field(ge=0, le=1)
    conflict_claim_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SummaryLayer(BaseModel):
    posture: ClaimPosture
    claim_ids: list[str]
    text: str


class SummaryResult(BaseModel):
    entity: str | None = None
    tldr: str
    key_points: list[SummaryLayer]
    full: list[SummaryLayer]
    evidence_ids: list[str]
    gate_decisions: list[GateDecision]
    warnings: list[str] = Field(default_factory=list)
