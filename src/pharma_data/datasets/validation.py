from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    DocumentVersion,
    RawArtifactRecord,
    SourceRecord,
)


class DataQualityValidator:
    def __init__(self, session: Session):
        self.session = session

    def run(self) -> dict[str, Any]:
        source_records = self.session.scalar(select(func.count()).select_from(SourceRecord)) or 0
        artifacts = self.session.scalar(select(func.count()).select_from(RawArtifactRecord)) or 0
        versions = self.session.scalar(select(func.count()).select_from(DocumentVersion)) or 0
        assertions = self.session.scalar(select(func.count()).select_from(AssertionRecord)) or 0
        approved_assertions = (
            self.session.scalar(
                select(func.count())
                .select_from(AssertionRecord)
                .where(AssertionRecord.review_status == "approved")
            )
            or 0
        )
        approved_with_evidence = (
            self.session.scalar(
                select(func.count(func.distinct(AssertionEvidenceRecord.assertion_id)))
                .join(
                    AssertionRecord,
                    AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
                )
                .where(AssertionRecord.review_status == "approved")
            )
            or 0
        )
        unknown_licenses = (
            self.session.scalar(
                select(func.count())
                .select_from(DocumentVersion)
                .where(DocumentVersion.license_status.in_(["unknown", "prohibited"]))
            )
            or 0
        )
        missing_hashes = (
            self.session.scalar(
                select(func.count())
                .select_from(RawArtifactRecord)
                .where(RawArtifactRecord.content_hash == "")
            )
            or 0
        )
        evidence_coverage = (
            approved_with_evidence / approved_assertions if approved_assertions else 1.0
        )
        checks = {
            "non_empty_corpus": source_records > 0 and versions > 0,
            "assertions_present": assertions > 0,
            "approved_assertions_present": approved_assertions > 0,
            "approved_evidence_coverage": evidence_coverage == 1.0,
            "no_unknown_or_prohibited_versions": unknown_licenses == 0,
            "all_artifacts_hashed": missing_hashes == 0,
            "artifact_version_consistency": artifacts >= versions,
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "metrics": {
                "source_records": source_records,
                "artifacts": artifacts,
                "document_versions": versions,
                "assertions": assertions,
                "approved_assertions": approved_assertions,
                "approved_evidence_coverage": evidence_coverage,
                "unknown_or_prohibited_versions": unknown_licenses,
            },
        }
