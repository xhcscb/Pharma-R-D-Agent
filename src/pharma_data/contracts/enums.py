from enum import StrEnum


class LicenseStatus(StrEnum):
    PUBLIC = "public"
    PUBLIC_ACCESS = "public_access"
    AUTHORIZED_RESTRICTED = "authorized_restricted"
    METADATA_ONLY = "metadata_only"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"


class AccessClass(StrEnum):
    PUBLIC = "public"
    TEAM_INTERNAL = "team_internal"
    RESTRICTED = "restricted"


class PipelineStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    FETCHED = "FETCHED"
    PARSED = "PARSED"
    ENTITY_EXTRACTED = "ENTITY_EXTRACTED"
    RELATION_EXTRACTED = "RELATION_EXTRACTED"
    CLEANED = "CLEANED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    PROJECTED = "PROJECTED"
    QUARANTINED = "QUARANTINED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


class DocumentType(StrEnum):
    RESEARCH_REPORT = "research_report"
    CLINICAL_RECORD = "clinical_record"
    CLINICAL_DOCUMENT = "clinical_document"
    FINANCIAL_REPORT = "financial_report"
    NEWS = "news"
    EARNINGS_CALL = "earnings_call"
    REGULATORY = "regulatory"
    OTHER = "other"


class ElementType(StrEnum):
    TITLE = "title"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CHART = "chart"
    FIGURE = "figure"
    FORMULA = "formula"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    UTTERANCE = "utterance"
    STRUCTURED_RECORD = "structured_record"


class EntityType(StrEnum):
    COMPANY = "Company"
    DRUG = "Drug"
    TARGET = "Target"
    INDICATION = "Indication"
    CLINICAL_TRIAL = "ClinicalTrial"
    PIPELINE_PROGRAM = "PipelineProgram"
    CLINICAL_STAGE = "ClinicalStage"
    REGULATORY_AGENCY = "RegulatoryAgency"
    PERSON = "Person"
    FINANCIAL_METRIC = "FinancialMetric"
    EVENT = "Event"
    DOCUMENT = "Document"
    MARKET = "Market"
    REGION = "Region"


class RelationType(StrEnum):
    DEVELOPS = "DEVELOPS"
    SPONSORS = "SPONSORS"
    PARTNERS_WITH = "PARTNERS_WITH"
    TARGETS = "TARGETS"
    TREATS = "TREATS"
    IN_TRIAL = "IN_TRIAL"
    HAS_STAGE = "HAS_STAGE"
    STUDIES = "STUDIES"
    REPRESENTS = "REPRESENTS"
    MENTIONS = "MENTIONS"
    COMPETES_WITH = "COMPETES_WITH"
    REPORTS = "REPORTS"


class AssertionMode(StrEnum):
    STATED = "stated"
    DERIVED = "derived"
    CALCULATED = "calculated"
    HUMAN_ENTERED = "human_entered"


class ReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class QualityLevel(StrEnum):
    GOLD = "Gold"
    SILVER = "Silver"
    CANDIDATE = "Candidate"
    CONFLICT = "Conflict"
    QUARANTINE = "Quarantine"


class ConflictType(StrEnum):
    TRUE_CONTRADICTION = "TRUE_CONTRADICTION"
    TEMPORAL_DIFFERENCE = "TEMPORAL_DIFFERENCE"
    SCOPE_DIFFERENCE = "SCOPE_DIFFERENCE"
    UNIT_DIFFERENCE = "UNIT_DIFFERENCE"
    CURRENCY_DIFFERENCE = "CURRENCY_DIFFERENCE"
    ESTIMATE_VS_ACTUAL = "ESTIMATE_VS_ACTUAL"
    RESTATEMENT = "RESTATEMENT"
    SOURCE_DISAGREEMENT = "SOURCE_DISAGREEMENT"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class ConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVED_TEMPORAL = "resolved_temporal"
    RESOLVED_SCOPE = "resolved_scope"
    RESOLVED_AUTHORITY = "resolved_authority"
    CONFIRMED_CONFLICT = "confirmed_conflict"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
