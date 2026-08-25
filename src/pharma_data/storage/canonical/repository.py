from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from pharma_data.contracts import (
    AccessClass,
    CleanResult,
    LicenseStatus,
    ParsedDocument,
    PipelineStatus,
    ReviewStatus,
    SourceRecordEnvelope,
)
from pharma_data.storage.canonical.access import visible_version_ids
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    AudioUtteranceRecord,
    CharacterSpanRecord,
    ConflictGroupRecord,
    DatasetSnapshotRecord,
    Document,
    DocumentAccessGrantRecord,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
    MetricDefinitionRecord,
    MetricObservationRecord,
    OutboxEventRecord,
    ParseCandidateRecord,
    ParseReviewItemRecord,
    ProcessingJob,
    ProcessingRun,
    RawArtifactRecord,
    ReviewDecisionRecord,
    SourceRecord,
    SourceRegistry,
    TableCellRecord,
)
from pharma_data.utils.hashing import stable_hash, stable_uuid
from pharma_data.utils.text import normalize_alias


class CanonicalRepository:
    def __init__(self, session: Session):
        self.session = session

    def ensure_source(
        self,
        *,
        name: str,
        adapter_name: str,
        authority_tier: str,
        default_license_status: LicenseStatus,
        base_url: str | None = None,
        terms_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceRegistry:
        existing = self.session.scalar(select(SourceRegistry).where(SourceRegistry.name == name))
        if existing:
            return existing
        row = SourceRegistry(
            name=name,
            adapter_name=adapter_name,
            authority_tier=authority_tier,
            base_url=base_url,
            terms_url=terms_url,
            default_license_status=default_license_status.value,
            metadata_json=metadata or {},
        )
        self.session.add(row)
        self.session.flush()
        return row
    def upsert_source_record(
        self, source: SourceRegistry, envelope: SourceRecordEnvelope
    ) -> SourceRecord:
        row = self.session.scalar(
            select(SourceRecord).where(
                SourceRecord.source_id == source.id,
                SourceRecord.external_id == envelope.source_record_id,
            )
        )
        record_hash = stable_hash(envelope.model_dump(mode="json"))
        if row:
            row.canonical_url = str(envelope.canonical_url) if envelope.canonical_url else None
            row.title = envelope.title
            row.published_at = envelope.published_at
            row.retrieved_at = envelope.retrieved_at
            row.license_status = envelope.license_status.value
            row.access_class = envelope.access_class.value
            row.raw_metadata = envelope.raw_metadata
            row.record_hash = record_hash
            return row

        row = SourceRecord(
            source_id=source.id,
            external_id=envelope.source_record_id,
            canonical_url=str(envelope.canonical_url) if envelope.canonical_url else None,
            title=envelope.title,
            document_type=envelope.document_type.value,
            published_at=envelope.published_at,
            retrieved_at=envelope.retrieved_at,
            license_status=envelope.license_status.value,
            access_class=envelope.access_class.value,
            raw_metadata=envelope.raw_metadata,
            record_hash=record_hash,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def save_artifact(
        self,
        *,
        source_record: SourceRecord,
        media_type: str,
        object_path: str,
        content_hash: str,
        size_bytes: int,
        original_url: str | None,
        license_status: LicenseStatus,
        access_class: AccessClass,
        metadata: dict[str, Any] | None = None,
    ) -> RawArtifactRecord:
        existing = self.session.scalar(
            select(RawArtifactRecord).where(
                RawArtifactRecord.source_record_id == source_record.id,
                RawArtifactRecord.content_hash == content_hash,
            )
        )
        if existing:
            return existing
        row = RawArtifactRecord(
            source_record_id=source_record.id,
            media_type=media_type,
            object_path=object_path,
            original_url=original_url,
            content_hash=content_hash,
            size_bytes=size_bytes,
            license_status=license_status.value,
            access_class=access_class.value,
            metadata_json=metadata or {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def create_document_version(
        self,
        *,
        source_record: SourceRecord,
        artifact: RawArtifactRecord,
        stable_key: str | None = None,
        language: str = "und",
    ) -> tuple[Document, DocumentVersion, bool]:
        key = stable_key or f"{source_record.source_id}:{source_record.external_id}"
        document = self.session.scalar(select(Document).where(Document.stable_key == key))
        if document is None:
            document = Document(
                stable_key=key,
                document_type=source_record.document_type,
                title=source_record.title,
                language=language,
            )
            self.session.add(document)
            self.session.flush()

        version = self.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.content_hash == artifact.content_hash,
            )
        )
        created = version is None
        if version is None:
            version = DocumentVersion(
                document_id=document.id,
                source_record_id=source_record.id,
                artifact_id=artifact.id,
                content_hash=artifact.content_hash,
                published_at=source_record.published_at,
                retrieved_at=source_record.retrieved_at,
                license_status=source_record.license_status,
                access_class=source_record.access_class,
                metadata_json=source_record.raw_metadata,
            )
            self.session.add(version)
            self.session.flush()
            document.current_version_id = version.id
        self.ensure_access_grant(
            version=version,
            source_record=source_record,
            access_class=AccessClass(source_record.access_class),
            license_status=LicenseStatus(source_record.license_status),
            metadata=source_record.raw_metadata,
        )
        return document, version, created

    def ensure_access_grant(
        self,
        *,
        version: DocumentVersion,
        source_record: SourceRecord,
        access_class: AccessClass,
        license_status: LicenseStatus,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentAccessGrantRecord:
        row = self.session.scalar(
            select(DocumentAccessGrantRecord).where(
                DocumentAccessGrantRecord.document_version_id == version.id,
                DocumentAccessGrantRecord.access_class == access_class.value,
            )
        )
        values = metadata or {}
        if row is None:
            row = DocumentAccessGrantRecord(
                document_version_id=version.id,
                source_record_id=source_record.id,
                access_class=access_class.value,
                license_status=license_status.value,
                provenance_status=str(values.get("provenance_status") or "unverified"),
                authorization_reference=values.get("authorization_reference"),
                active=True,
                metadata_json=values,
            )
            self.session.add(row)
        else:
            row.source_record_id = source_record.id
            row.license_status = license_status.value
            row.provenance_status = str(values.get("provenance_status") or row.provenance_status)
            row.authorization_reference = (
                values.get("authorization_reference") or row.authorization_reference
            )
            row.active = True
            row.metadata_json = {**row.metadata_json, **values}
        # Keep legacy columns as the least restrictive effective grant for old clients.
        if access_class == AccessClass.PUBLIC or version.access_class != AccessClass.PUBLIC.value:
            version.access_class = access_class.value
            version.license_status = license_status.value
        self.session.flush()
        return row

    def enqueue_job(
        self,
        *,
        document_version_id: str,
        pipeline_step: str,
        input_hash: str,
        schema_version: str = "1.0",
        component_version: str = "0.2.0",
        configuration: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ProcessingJob:
        idempotency_key = stable_hash(
            {
                "document_version_id": document_version_id,
                "pipeline_step": pipeline_step,
                "input_hash": input_hash,
                "schema_version": schema_version,
                "component_version": component_version,
                "configuration": configuration or {},
            }
        )
        existing = self.session.scalar(
            select(ProcessingJob).where(ProcessingJob.idempotency_key == idempotency_key)
        )
        if existing:
            return existing
        job = ProcessingJob(
            document_version_id=document_version_id,
            pipeline_step=pipeline_step,
            status=PipelineStatus.FETCHED.value,
            idempotency_key=idempotency_key,
            payload=payload or {},
        )
        self.session.add(job)
        self.session.flush()
        return job

    def claim_job(self, worker_id: str, lock_seconds: int) -> ProcessingJob | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=lock_seconds)
        statement: Select[tuple[ProcessingJob]] = (
            select(ProcessingJob)
            .where(
                ProcessingJob.status.in_(
                    [PipelineStatus.FETCHED.value, PipelineStatus.FAILED_RETRYABLE.value]
                ),
                ProcessingJob.available_at <= now,
                or_(ProcessingJob.locked_at.is_(None), ProcessingJob.locked_at < stale_before),
            )
            .order_by(ProcessingJob.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = self.session.scalar(statement)
        if job:
            job.locked_at = now
            job.locked_by = worker_id
            job.attempts += 1
            job.status = PipelineStatus.PROCESSING.value
            self.session.flush()
        return job

    def start_run(
        self,
        job: ProcessingJob,
        *,
        trace_id: str,
        producer: str,
        producer_version: str,
        schema_version: str,
        input_hash: str,
    ) -> ProcessingRun:
        run = ProcessingRun(
            job_id=job.id,
            trace_id=trace_id,
            producer=producer,
            producer_version=producer_version,
            schema_version=schema_version,
            input_hash=input_hash,
            status=job.status,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def save_parsed_document(self, parsed: ParsedDocument, run: ProcessingRun) -> tuple[int, int]:
        run.warnings = sorted(set([*run.warnings, *parsed.warnings]))
        element_count = 0
        for element in parsed.elements:
            exists = self.session.get(DocumentElementRecord, element.element_id)
            if exists:
                continue
            element_row = DocumentElementRecord(
                id=element.element_id,
                document_version_id=parsed.document_version_id,
                parse_run_id=run.id,
                page_number=element.page_number,
                element_type=element.element_type.value,
                bbox=element.bbox.model_dump() if element.bbox else None,
                reading_order=element.reading_order,
                text=element.text,
                structured_payload=element.structured_payload,
                footnote_links=element.footnote_links,
                parser_name=element.parser_name,
                parser_version=element.parser_version,
                confidence=element.confidence,
                content_hash=element.content_hash,
            )
            self.session.add(element_row)
            self.session.flush()
            for span in element.character_spans:
                self.session.add(
                    CharacterSpanRecord(
                        element_id=element_row.id,
                        char_start=span.char_start,
                        char_end=span.char_end,
                        text=span.text,
                        bbox=span.bbox.model_dump() if span.bbox else None,
                        confidence=span.confidence,
                    )
                )
            for cell in element.table_cells:
                self.session.add(
                    TableCellRecord(
                        element_id=element_row.id,
                        row_index=cell.row_index,
                        column_index=cell.column_index,
                        row_span=cell.row_span,
                        column_span=cell.column_span,
                        text=cell.text,
                        bbox=cell.bbox.model_dump() if cell.bbox else None,
                        header_path=cell.header_path,
                        normalized_value=cell.normalized_value,
                        numeric_value=_decimal_or_none(cell.numeric_value),
                        unit=cell.unit,
                        currency=cell.currency,
                        scale=cell.scale,
                        period_start=cell.period_start,
                        period_end=cell.period_end,
                        confidence=cell.confidence,
                    )
                )
            element_count += 1

        utterance_count = 0
        for utterance in parsed.utterances:
            if self.session.get(AudioUtteranceRecord, utterance.utterance_id):
                continue
            utterance_row = AudioUtteranceRecord(
                id=utterance.utterance_id,
                document_version_id=parsed.document_version_id,
                parse_run_id=run.id,
                speaker_id=utterance.speaker_id,
                speaker_name=utterance.speaker_name,
                speaker_role=utterance.speaker_role,
                start_ms=utterance.start_ms,
                end_ms=utterance.end_ms,
                raw_transcript=utterance.raw_transcript,
                normalized_transcript=utterance.normalized_transcript,
                asr_confidence=utterance.asr_confidence,
                audio_artifact_id=utterance.audio_artifact_id,
                review_status=utterance.review_status.value,
            )
            self.session.add(utterance_row)
            utterance_count += 1

        version = self.session.get(DocumentVersion, parsed.document_version_id)
        if version:
            version.active_parse_run_id = run.id
            version.metadata_json = {
                **version.metadata_json,
                "parse_quality": parsed.parse_quality,
                "parse_warnings": parsed.warnings,
                "language": parsed.language,
            }
        for candidate in parsed.metadata.get("parse_candidates", []):
            if not isinstance(candidate, dict):
                continue
            pages = candidate.get("pages")
            page_numbers = pages if isinstance(pages, list) and pages else [None]
            for page_number in page_numbers:
                self.session.add(
                    ParseCandidateRecord(
                        document_version_id=parsed.document_version_id,
                        parse_run_id=run.id,
                        page_number=int(page_number) if page_number is not None else None,
                        region_key=candidate.get("region_key"),
                        backend_name=str(candidate.get("backend_name") or "unknown"),
                        backend_version=candidate.get("backend_version"),
                        node_id=candidate.get("node_id"),
                        selected=bool(candidate.get("selected")),
                        status=str(candidate.get("status") or "candidate"),
                        score=float(candidate["score"])
                        if candidate.get("score") is not None
                        else None,
                        diagnostics={
                            **(candidate.get("diagnostics") or {}),
                            "health": candidate.get("health"),
                            "endpoint": candidate.get("endpoint"),
                        },
                        parameters=candidate.get("parameters") or {},
                        raw_output_path=candidate.get("raw_output_path"),
                        raw_output_hash=candidate.get("raw_output_hash"),
                    )
                )
        quality_by_page = {
            int(item["page_number"]): item
            for item in parsed.metadata.get("page_quality", [])
            if isinstance(item, dict) and item.get("page_number") is not None
        }
        for page_number in parsed.metadata.get("failed_pages", []):
            diagnostic = quality_by_page.get(int(page_number), {})
            failures = diagnostic.get("failures") or [
                str(parsed.metadata.get("degradation_reason") or "parser_degraded")
            ]
            for gate_code in failures:
                self.session.add(
                    ParseReviewItemRecord(
                        document_version_id=parsed.document_version_id,
                        parse_run_id=run.id,
                        page_number=int(page_number),
                        gate_code=str(gate_code),
                        severity="hard",
                        status="open",
                        diagnostics=diagnostic,
                    )
                )
        self.session.flush()
        return element_count, utterance_count

    def save_clean_result(self, result: CleanResult) -> tuple[int, int, int]:
        for mention in result.mentions:
            entity = self._find_or_create_entity(mention)
            mention_row = self.session.get(EntityMentionRecord, mention.mention_id)
            if mention_row is None:
                mention_row = EntityMentionRecord(
                    id=mention.mention_id,
                    document_version_id=result.document_version_id,
                    element_id=mention.element_id,
                    entity_id=entity.id if entity else None,
                    entity_type=mention.entity_type.value,
                    original_text=mention.original_text,
                    normalized_name=mention.normalized_name,
                    char_start=mention.char_start,
                    char_end=mention.char_end,
                    audio_start_ms=mention.audio_start_ms,
                    audio_end_ms=mention.audio_end_ms,
                    extraction_method=mention.extraction_method,
                    confidence=mention.confidence,
                    link_status=mention.link_status.value,
                    metadata_json=mention.metadata,
                )
                self.session.add(mention_row)
        self.session.flush()

        assertion_count = 0
        generated_conflict_count = 0
        assertion_id_map: dict[str, str] = {}
        version = self.session.get(DocumentVersion, result.document_version_id)
        for assertion in result.assertions:
            subject = self.session.get(EntityMentionRecord, assertion.subject_mention_id)
            obj = (
                self.session.get(EntityMentionRecord, assertion.object_mention_id)
                if assertion.object_mention_id
                else None
            )
            subject_entity_id = subject.entity_id if subject else None
            if assertion.predicate.value == "REPORTS" and version is not None:
                subject_entity = (
                    self.session.get(EntityRecord, subject_entity_id)
                    if subject_entity_id
                    else None
                )
                if subject_entity is None or subject_entity.entity_type != "Company":
                    issuer_entity = self._issuer_entity(version)
                    subject_entity_id = issuer_entity.id if issuer_entity else subject_entity_id
            assertion_key, fact_group_key = _assertion_keys(
                assertion,
                version,
                subject_entity_id or assertion.subject_mention_id,
                obj.entity_id if obj else None,
            )
            assertion_row = self.session.scalar(
                select(AssertionRecord)
                .where(AssertionRecord.assertion_key == assertion_key)
                .order_by(AssertionRecord.created_at, AssertionRecord.id)
                .limit(1)
            )
            if assertion_row is None:
                by_id = self.session.get(AssertionRecord, assertion.assertion_id)
                assertion_row = by_id
            if assertion_row is None:
                assertion_row = AssertionRecord(
                    id=assertion.assertion_id,
                    subject_entity_id=subject_entity_id,
                    subject_mention_id=assertion.subject_mention_id,
                    predicate=assertion.predicate.value,
                    object_entity_id=obj.entity_id if obj else None,
                    object_mention_id=assertion.object_mention_id,
                    object_value=assertion.object_value,
                    object_unit=assertion.object_unit,
                    qualifiers=assertion.qualifiers,
                    valid_from=assertion.valid_from,
                    valid_to=assertion.valid_to,
                    as_of_date=assertion.as_of_date,
                    assertion_mode=assertion.assertion_mode.value,
                    extraction_method=assertion.extraction_method,
                    confidence=assertion.confidence,
                    review_status=assertion.review_status.value,
                    assertion_key=assertion_key,
                    fact_group_key=fact_group_key,
                )
                self.session.add(assertion_row)
                self.session.flush()
                assertion_count += 1
            else:
                assertion_row.assertion_key = assertion_key
                assertion_row.fact_group_key = fact_group_key
                if subject_entity_id:
                    assertion_row.subject_entity_id = subject_entity_id
            assertion_id_map[assertion.assertion_id] = assertion_row.id
            evidence_element = (
                self.session.get(DocumentElementRecord, assertion.evidence_element_id)
                if assertion.evidence_element_id
                else None
            )
            char_span = _evidence_char_span(assertion, evidence_element)
            table_cell = None
            if assertion.evidence_table_cell and assertion.evidence_element_id:
                table_cell = self.session.scalar(
                    select(TableCellRecord).where(
                        TableCellRecord.element_id == assertion.evidence_element_id,
                        TableCellRecord.row_index == assertion.evidence_table_cell[0],
                        TableCellRecord.column_index == assertion.evidence_table_cell[1],
                    )
                )
            evidence_hash = _evidence_hash(
                version,
                assertion,
                evidence_element,
                table_cell,
                char_span,
            )
            approved_evidence_match = self.session.scalar(
                select(AssertionEvidenceRecord.id)
                .where(
                    AssertionEvidenceRecord.assertion_id == assertion_row.id,
                    AssertionEvidenceRecord.evidence_hash == evidence_hash,
                )
                .limit(1)
            )
            if assertion_row.review_status == ReviewStatus.APPROVED.value and not (
                approved_evidence_match
            ):
                assertion_row.review_status = ReviewStatus.CANDIDATE.value
            evidence = self.session.scalar(
                select(AssertionEvidenceRecord).where(
                    AssertionEvidenceRecord.assertion_id == assertion_row.id,
                    AssertionEvidenceRecord.document_version_id == result.document_version_id,
                    AssertionEvidenceRecord.element_id == assertion.evidence_element_id,
                    AssertionEvidenceRecord.utterance_id == assertion.evidence_utterance_id,
                    AssertionEvidenceRecord.table_cell_id
                    == (table_cell.id if table_cell else None),
                )
            )
            if evidence is None:
                evidence = AssertionEvidenceRecord(
                    assertion_id=assertion_row.id,
                    document_version_id=result.document_version_id,
                    element_id=assertion.evidence_element_id,
                    utterance_id=assertion.evidence_utterance_id,
                    evidence_text=assertion.evidence_text,
                    page_number=evidence_element.page_number if evidence_element else None,
                    bbox=evidence_element.bbox if evidence_element else None,
                    char_span=char_span,
                    table_cell_id=table_cell.id if table_cell else None,
                    evidence_hash=evidence_hash,
                )
                self.session.add(evidence)
                self.session.flush()
            if assertion.predicate.value == "REPORTS":
                self._save_metric_observation(
                    result.document_version_id,
                    assertion_row,
                    evidence,
                    subject,
                )
                generated_conflict_count += self._sync_fact_conflict(fact_group_key)

        for conflict in result.conflicts:
            assertion_ids = sorted(
                {
                    assertion_id_map.get(assertion_id, assertion_id)
                    for assertion_id in conflict.assertion_ids
                }
            )
            # Canonical-key merging can collapse multiple extracted candidates to
            # one assertion. A one-member "conflict" is not a conflict.
            if len(assertion_ids) < 2:
                continue
            conflict_id = stable_uuid([conflict.conflict_type.value, assertion_ids])
            if not self.session.get(ConflictGroupRecord, conflict_id):
                self.session.add(
                    ConflictGroupRecord(
                        id=conflict_id,
                        conflict_type=conflict.conflict_type.value,
                        assertion_ids=assertion_ids,
                        status=conflict.status.value,
                        rationale=conflict.rationale,
                    )
                )
        self.session.flush()
        return (
            len(result.mentions),
            assertion_count,
            len(result.conflicts) + generated_conflict_count,
        )

    def _issuer_entity(self, version: DocumentVersion) -> EntityRecord | None:
        issuer = str((version.metadata_json or {}).get("issuer") or "").strip()
        if not issuer:
            return None
        normalized = normalize_alias(issuer)
        entity = self.session.scalar(
            select(EntityRecord).where(
                EntityRecord.entity_type == "Company",
                EntityRecord.normalized_name == normalized,
            )
        )
        if entity is None:
            entity = EntityRecord(
                entity_type="Company",
                canonical_name=issuer,
                normalized_name=normalized,
                external_ids={},
                properties={"source": "document_metadata"},
                review_status="candidate",
            )
            self.session.add(entity)
            self.session.flush()
        return entity

    def _sync_fact_conflict(self, fact_group_key: str) -> int:
        rows = list(
            self.session.scalars(
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
                .where(AssertionRecord.fact_group_key == fact_group_key)
                .where(
                    DocumentElementRecord.parse_run_id
                    == DocumentVersion.active_parse_run_id
                )
                .distinct()
                .order_by(AssertionRecord.id)
            )
        )
        values = {
            (
                str(row.qualifiers.get("normalized_numeric_value") or row.object_value),
                row.object_unit,
                row.qualifiers.get("currency"),
            )
            for row in rows
        }
        if len(rows) < 2 or len(values) < 2:
            return 0
        units = {row.object_unit for row in rows if row.object_unit}
        currencies = {
            str(row.qualifiers.get("currency"))
            for row in rows
            if row.qualifiers.get("currency")
        }
        if len(units) > 1:
            conflict_type = "UNIT_DIFFERENCE"
            rationale = "Canonical fact candidates use different units"
        elif len(currencies) > 1:
            conflict_type = "CURRENCY_DIFFERENCE"
            rationale = "Canonical fact candidates use different currencies"
        else:
            conflict_type = "TRUE_CONTRADICTION"
            rationale = "Canonical fact candidates share metric, period and scope but differ"
        assertion_ids = [row.id for row in rows]
        conflict_id = stable_uuid([conflict_type, assertion_ids])
        if self.session.get(ConflictGroupRecord, conflict_id):
            return 0
        self.session.add(
            ConflictGroupRecord(
                id=conflict_id,
                conflict_type=conflict_type,
                assertion_ids=assertion_ids,
                status="open",
                rationale=rationale,
            )
        )
        return 1

    def _save_metric_observation(
        self,
        document_version_id: str,
        assertion: AssertionRecord,
        evidence: AssertionEvidenceRecord,
        subject_mention: EntityMentionRecord | None,
    ) -> None:
        metric_name = str(assertion.qualifiers.get("metric_name") or "").strip()
        if not metric_name or assertion.object_value is None:
            return
        definition = self.session.scalar(
            select(MetricDefinitionRecord).where(
                MetricDefinitionRecord.canonical_name == metric_name
            )
        )
        if definition is None:
            definition = MetricDefinitionRecord(
                canonical_name=metric_name,
                aliases=[metric_name],
                value_type="number",
                allowed_units=[assertion.object_unit] if assertion.object_unit else [],
                scope_rules={
                    "required_dimensions": ["entity", "period", "consolidation_scope"]
                },
                definition=f"从正式报告表格或正文提取的{metric_name}观测值",
            )
            self.session.add(definition)
            self.session.flush()
        entity = (
            self.session.get(EntityRecord, subject_mention.entity_id)
            if subject_mention and subject_mention.entity_id
            else None
        )
        version = self.session.get(DocumentVersion, document_version_id)
        if entity is None or entity.entity_type != "Company":
            if version is None:
                return
            entity = self._issuer_entity(version)
            if entity is None:
                return
        existing = self.session.scalar(
            select(MetricObservationRecord).where(
                MetricObservationRecord.assertion_id == assertion.id,
                MetricObservationRecord.metric_definition_id == definition.id,
                MetricObservationRecord.entity_id == entity.id,
            )
        )
        period_start, period_end = _observation_period(
            (version.metadata_json if version else {}).get("report_period"),
            assertion.qualifiers,
            metric_name,
        )
        numeric_value = _decimal_or_none(
            assertion.qualifiers.get("normalized_numeric_value")
            or assertion.object_value
        )
        if existing is not None:
            existing.raw_value = assertion.object_value
            existing.numeric_value = numeric_value
            existing.unit = assertion.object_unit
            existing.currency = assertion.qualifiers.get("currency")
            existing.scale = str(assertion.qualifiers.get("scale") or "1")
            existing.period_start = period_start
            existing.period_end = period_end
            existing.as_of_date = assertion.as_of_date or (
                version.published_at if version else None
            )
            existing.scope = {
                "consolidation_scope": assertion.qualifiers.get(
                    "consolidation_scope", "unspecified"
                ),
                "period_semantics": assertion.qualifiers.get(
                    "period_semantics", "unspecified"
                ),
                "period_label": assertion.qualifiers.get("period_label"),
                "reported_column": assertion.qualifiers.get("reported_column"),
                "document_version_id": document_version_id,
                "source_kind": "assertion",
            }
            existing.evidence_id = evidence.id
            existing.review_status = assertion.review_status
            return
        self.session.add(
            MetricObservationRecord(
                entity_id=entity.id,
                metric_definition_id=definition.id,
                assertion_id=assertion.id,
                raw_value=assertion.object_value,
                numeric_value=numeric_value,
                unit=assertion.object_unit,
                currency=assertion.qualifiers.get("currency"),
                scale=str(assertion.qualifiers.get("scale") or "1"),
                period_start=period_start,
                period_end=period_end,
                as_of_date=assertion.as_of_date or (version.published_at if version else None),
                scope={
                    "consolidation_scope": assertion.qualifiers.get(
                        "consolidation_scope", "unspecified"
                    ),
                    "period_semantics": assertion.qualifiers.get(
                        "period_semantics", "unspecified"
                    ),
                    "period_label": assertion.qualifiers.get("period_label"),
                    "reported_column": assertion.qualifiers.get("reported_column"),
                    "document_version_id": document_version_id,
                    "source_kind": "assertion",
                },
                evidence_id=evidence.id,
                review_status=assertion.review_status,
            )
        )

    def _find_or_create_entity(self, mention: Any) -> EntityRecord:
        normalized = normalize_alias(mention.normalized_name)
        entity = self.session.scalar(
            select(EntityRecord).where(
                EntityRecord.entity_type == mention.entity_type.value,
                EntityRecord.normalized_name == normalized,
            )
        )
        if entity:
            return entity
        entity = EntityRecord(
            entity_type=mention.entity_type.value,
            canonical_name=mention.normalized_name,
            normalized_name=normalized,
            external_ids=mention.metadata.get("external_ids", {}),
            properties={},
            review_status=mention.link_status.value,
        )
        self.session.add(entity)
        self.session.flush()
        return entity

    def record_review(
        self,
        *,
        target_type: str,
        target_id: str,
        decision: ReviewStatus,
        reviewer: str,
        rationale: str,
    ) -> ReviewDecisionRecord:
        if decision == ReviewStatus.APPROVED:
            if target_type == "assertion":
                assertion = self.session.get(AssertionRecord, target_id)
                if assertion is None:
                    raise KeyError(target_id)
                evidence_count = self.session.scalar(
                    select(AssertionEvidenceRecord.id)
                    .where(AssertionEvidenceRecord.assertion_id == target_id)
                    .limit(1)
                )
                if evidence_count is None:
                    raise ValueError("Assertions cannot be approved without evidence")
                assertion.review_status = decision.value
                for projection in ("neo4j", "milvus", "timescale", "elasticsearch"):
                    self.session.add(
                        OutboxEventRecord(
                            aggregate_type="assertion",
                            aggregate_id=assertion.id,
                            event_type="assertion.approved",
                            projection=projection,
                            payload={"assertion_id": assertion.id},
                        )
                    )
            elif target_type == "entity":
                entity = self.session.get(EntityRecord, target_id)
                if entity is None:
                    raise KeyError(target_id)
                entity.review_status = decision.value
        row = ReviewDecisionRecord(
            target_type=target_type,
            target_id=target_id,
            decision=decision.value,
            reviewer=reviewer,
            rationale=rationale,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def review_queue(self, limit: int = 100) -> list[dict[str, Any]]:
        assertions = self.session.scalars(
            select(AssertionRecord)
            .where(AssertionRecord.review_status.in_(["candidate", "pending"]))
            .order_by(AssertionRecord.created_at)
            .limit(limit)
        )
        return [
            {
                "target_type": "assertion",
                "target_id": item.id,
                "predicate": item.predicate,
                "confidence": item.confidence,
                "review_status": item.review_status,
            }
            for item in assertions
        ]

    def create_snapshot(
        self,
        *,
        name: str,
        specification: dict[str, Any],
        manifest: dict[str, Any],
        access_class: AccessClass,
        created_by: str,
    ) -> DatasetSnapshotRecord:
        if access_class == AccessClass.PUBLIC:
            requested_ids = set(manifest.get("document_version_ids", []))
            public_versions = visible_version_ids((AccessClass.PUBLIC.value,)).subquery()
            visible_ids = set(
                self.session.scalars(
                    select(public_versions.c.id).where(
                        public_versions.c.id.in_(requested_ids)
                    )
                )
            )
            if requested_ids - visible_ids:
                raise ValueError(
                    "Public snapshots can contain only versions with an active public grant"
                )
        snapshot_hash = stable_hash(
            {"specification": specification, "manifest": manifest, "access": access_class.value}
        )
        existing = self.session.scalar(
            select(DatasetSnapshotRecord).where(
                DatasetSnapshotRecord.snapshot_hash == snapshot_hash
            )
        )
        if existing:
            return existing
        row = DatasetSnapshotRecord(
            name=name,
            snapshot_hash=snapshot_hash,
            specification=specification,
            manifest=manifest,
            access_class=access_class.value,
            created_by=created_by,
        )
        self.session.add(row)
        self.session.flush()
        return row


EVIDENCE_QUALIFIER_KEYS = {
    "raw_value",
    "source_structure",
    "row_index",
    "column_index",
    "header_path",
    "reported_column",
    "cell_confidence",
    "unit_inference",
}


def _assertion_keys(
    assertion: Any,
    version: DocumentVersion | None,
    subject_identity: str,
    object_entity_id: str | None,
) -> tuple[str, str]:
    qualifiers = dict(assertion.qualifiers or {})
    metric_name = str(qualifiers.get("metric_name") or "")
    report_period = (version.metadata_json or {}).get("report_period") if version else None
    period_start, period_end = _observation_period(
        report_period,
        qualifiers,
        metric_name,
    )
    if assertion.predicate.value == "REPORTS":
        dimensions = {
            key: qualifiers.get(key)
            for key in (
                "metric_name",
                "consolidation_scope",
                "business_scope",
                "region",
                "value_kind",
                "accounting_standard",
            )
            if qualifiers.get(key) is not None
        }
        dimensions.update(
            {
                "period_start": period_start,
                "period_end": period_end,
            }
        )
        if period_start is None and period_end is None:
            dimensions.update(
                {
                    "period_semantics": qualifiers.get("period_semantics"),
                    "period_label": qualifiers.get("period_label"),
                }
            )
    else:
        dimensions = {
            key: value
            for key, value in qualifiers.items()
            if key not in EVIDENCE_QUALIFIER_KEYS
        }
    group_identity = {
        "subject": subject_identity,
        "predicate": assertion.predicate.value,
        "dimensions": dimensions,
        "valid_from": assertion.valid_from,
        "valid_to": assertion.valid_to,
        "as_of_date": assertion.as_of_date,
    }
    normalized_value = qualifiers.get("normalized_numeric_value")
    object_identity = object_entity_id or (
        str(normalized_value)
        if normalized_value is not None
        else assertion.object_value
    )
    assertion_key = stable_hash(
        {
            **group_identity,
            "object": object_identity,
            "unit": assertion.object_unit,
            "currency": qualifiers.get("currency"),
        }
    )
    return assertion_key, stable_hash(group_identity)


def _evidence_hash(
    version: DocumentVersion | None,
    assertion: Any,
    element: DocumentElementRecord | None,
    table_cell: TableCellRecord | None,
    char_span: dict[str, int] | None,
) -> str:
    return stable_hash(
        {
            "document_content_hash": version.content_hash if version else None,
            "page_number": element.page_number if element else None,
            "bbox": element.bbox if element else None,
            "char_span": char_span,
            "table_cell": (
                {
                    "row_index": table_cell.row_index,
                    "column_index": table_cell.column_index,
                    "text": table_cell.text,
                    "bbox": table_cell.bbox,
                }
                if table_cell
                else None
            ),
            "audio_range": None,
            "evidence_text": assertion.evidence_text,
        }
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").rstrip("%"))
    except (InvalidOperation, ValueError):
        return None


def _report_period(value: Any) -> tuple[datetime | None, datetime | None]:
    if not isinstance(value, str) or len(value) < 4 or not value[:4].isdigit():
        return None, None
    year = int(value[:4])
    start = datetime(year, 1, 1, tzinfo=UTC)
    normalized = value.upper()
    if "Q1" in normalized:
        return start, datetime(year, 3, 31, tzinfo=UTC)
    if "H1" in normalized or "半年度" in normalized:
        return start, datetime(year, 6, 30, tzinfo=UTC)
    if "Q3" in normalized:
        return start, datetime(year, 9, 30, tzinfo=UTC)
    return start, datetime(year, 12, 31, tzinfo=UTC)


def _observation_period(
    report_period: Any,
    qualifiers: dict[str, Any],
    metric_name: str,
) -> tuple[datetime | None, datetime | None]:
    explicit_start = _datetime_or_none(qualifiers.get("period_start"))
    explicit_end = _datetime_or_none(qualifiers.get("period_end"))
    if explicit_start or explicit_end:
        return explicit_start, explicit_end

    start, end = _report_period(report_period)
    if end is None:
        return start, end
    semantics = str(qualifiers.get("period_semantics") or "unspecified")
    balance_sheet_metrics = {
        "资产总计",
        "负债合计",
        "所有者权益合计",
        "归属于母公司所有者权益",
        "货币资金",
        "应收账款",
        "存货",
        "固定资产",
        "无形资产",
    }
    is_point_in_time = metric_name in balance_sheet_metrics
    if semantics == "prior_year_same_period":
        prior_start = _replace_year(start, -1)
        prior_end = _replace_year(end, -1)
        return (prior_end, prior_end) if is_point_in_time else (prior_start, prior_end)
    if semantics == "prior_year_end":
        prior_end = datetime(end.year - 1, 12, 31, tzinfo=UTC)
        return (prior_end, prior_end) if is_point_in_time else (
            datetime(end.year - 1, 1, 1, tzinfo=UTC),
            prior_end,
        )
    if semantics == "period_start" and start is not None:
        return start, start
    return (end, end) if is_point_in_time else (start, end)


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _replace_year(value: datetime | None, delta: int) -> datetime | None:
    if value is None:
        return None
    try:
        return value.replace(year=value.year + delta)
    except ValueError:
        return value.replace(year=value.year + delta, day=28)


def _evidence_char_span(
    assertion: Any, element: DocumentElementRecord | None
) -> dict[str, int] | None:
    if assertion.evidence_char_start is not None and assertion.evidence_char_end is not None:
        return {
            "start": int(assertion.evidence_char_start),
            "end": int(assertion.evidence_char_end),
        }
    if element is None or not assertion.evidence_text:
        return None
    start = element.text.find(assertion.evidence_text)
    if start < 0:
        return None
    return {"start": start, "end": start + len(assertion.evidence_text)}
