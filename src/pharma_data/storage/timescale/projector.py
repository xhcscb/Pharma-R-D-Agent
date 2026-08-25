import json

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from pharma_data.config import Settings
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityRecord,
    OutboxEventRecord,
)


class TimescaleProjector:
    name = "timescale"
    tables = (
        "market_price",
        "financial_metric_series",
        "clinical_event",
        "regulatory_event",
        "news_event",
        "assertion_version_event",
    )
    market_metrics = {
        "开盘价",
        "收盘价",
        "最高价",
        "最低价",
        "成交量",
        "成交额",
        "总市值",
    }

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(settings.timescale_url, pool_pre_ping=True)

    def _ensure_schema(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            for table in self.tables:
                connection.execute(
                    text(
                        f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                          event_time TIMESTAMPTZ NOT NULL,
                          published_time TIMESTAMPTZ NOT NULL,
                          assertion_id TEXT NOT NULL,
                          subject_entity_id TEXT,
                          predicate TEXT NOT NULL,
                          object_entity_id TEXT,
                          object_value TEXT,
                          object_unit TEXT,
                          qualifiers JSONB NOT NULL,
                          review_status TEXT NOT NULL,
                          PRIMARY KEY (event_time, assertion_id)
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        f"""
                        SELECT create_hypertable(
                          '{table}', 'event_time',
                          if_not_exists => TRUE,
                          migrate_data => TRUE
                        )
                        """
                    )
                )

    def _target_tables(self, session: Session, assertion: AssertionRecord) -> set[str]:
        targets = {"assertion_version_event"}
        if assertion.predicate == "REPORTS":
            metric_name = str(assertion.qualifiers.get("metric_name") or "")
            if metric_name in self.market_metrics:
                targets.add("market_price")
            else:
                targets.add("financial_metric_series")
        if assertion.predicate in {
            "SPONSORS",
            "IN_TRIAL",
            "STUDIES",
            "HAS_STAGE",
        }:
            targets.add("clinical_event")

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
        if evidence is not None:
            version = session.get(DocumentVersion, evidence.document_version_id)
            document = session.get(Document, version.document_id) if version else None
            if document and document.document_type == "news":
                targets.add("news_event")
            if document and document.document_type == "regulatory":
                targets.add("regulatory_event")
            if document and document.document_type == "market_data":
                targets.add("market_price")

        subject = (
            session.get(EntityRecord, assertion.subject_entity_id)
            if assertion.subject_entity_id
            else None
        )
        if subject and subject.entity_type == "RegulatoryAgency":
            targets.add("regulatory_event")
        return targets

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
        event_time = (
            assertion.as_of_date
            or assertion.valid_from
            or (version.published_at if version else None)
            or assertion.created_at
        )
        published_time = (
            version.published_at if version and version.published_at else assertion.created_at
        )
        self._ensure_schema()
        parameters = {
            "event_time": event_time,
            "published_time": published_time,
            "assertion_id": assertion.id,
            "subject_entity_id": assertion.subject_entity_id,
            "predicate": assertion.predicate,
            "object_entity_id": assertion.object_entity_id,
            "object_value": assertion.object_value,
            "object_unit": assertion.object_unit,
            "qualifiers": json.dumps(assertion.qualifiers),
            "review_status": assertion.review_status,
        }
        with self.engine.begin() as connection:
            for table in self._target_tables(session, assertion):
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {table} (
                          event_time, published_time, assertion_id, subject_entity_id,
                          predicate, object_entity_id, object_value, object_unit,
                          qualifiers, review_status
                        ) VALUES (
                          :event_time, :published_time, :assertion_id, :subject_entity_id,
                          :predicate, :object_entity_id, :object_value, :object_unit,
                          CAST(:qualifiers AS JSONB), :review_status
                        )
                        ON CONFLICT (event_time, assertion_id) DO UPDATE SET
                          published_time = EXCLUDED.published_time,
                          object_value = EXCLUDED.object_value,
                          object_unit = EXCLUDED.object_unit,
                          qualifiers = EXCLUDED.qualifiers,
                          review_status = EXCLUDED.review_status
                        """
                    ),
                    parameters,
                )

    def rebuild(self, session: Session) -> dict[str, int]:
        self._ensure_schema()
        with self.engine.begin() as connection:
            for table in self.tables:
                connection.execute(text(f"TRUNCATE {table}"))
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
        counts = {table: 0 for table in self.tables}
        for assertion in assertions:
            for table in self._target_tables(session, assertion):
                counts[table] += 1
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
        return counts
