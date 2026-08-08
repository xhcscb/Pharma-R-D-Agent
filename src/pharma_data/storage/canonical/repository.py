from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, or_, select
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
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    AudioUtteranceRecord,
    ConflictGroupRecord,
    DatasetSnapshotRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    EntityMentionRecord,
    EntityRecord,
    OutboxEventRecord,
    ProcessingJob,
    ProcessingRun,
    RawArtifactRecord,
    ReviewDecisionRecord,
    SourceRecord,
    SourceRegistry,
)
from pharma_data.utils.hashing import stable_hash
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
        return document, version, created

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
        element_count = 0
        for element in parsed.elements:
            exists = self.session.get(DocumentElementRecord, element.element_id)
            if exists:
                continue
            row = DocumentElementRecord(
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
            self.session.add(row)
            element_count += 1

        utterance_count = 0
        for utterance in parsed.utterances:
            if self.session.get(AudioUtteranceRecord, utterance.utterance_id):
                continue
            row = AudioUtteranceRecord(
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
            self.session.add(row)
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
        self.session.flush()
        return element_count, utterance_count

    def save_clean_result(self, result: CleanResult) -> tuple[int, int, int]:
        for mention in result.mentions:
            entity = self._find_or_create_entity(mention)
            row = self.session.get(EntityMentionRecord, mention.mention_id)
            if row is None:
                row = EntityMentionRecord(
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
                self.session.add(row)
        self.session.flush()

        assertion_count = 0
        for assertion in result.assertions:
            if self.session.get(AssertionRecord, assertion.assertion_id):
                continue
            subject = self.session.get(EntityMentionRecord, assertion.subject_mention_id)
            obj = (
                self.session.get(EntityMentionRecord, assertion.object_mention_id)
                if assertion.object_mention_id
                else None
            )
            assertion_key = stable_hash(
                {
                    "subject": subject.entity_id if subject else assertion.subject_mention_id,
                    "predicate": assertion.predicate.value,
                    "object": obj.entity_id if obj else assertion.object_value,
                    "qualifiers": assertion.qualifiers,
                    "valid_from": assertion.valid_from,
                    "valid_to": assertion.valid_to,
                }
            )
            row = AssertionRecord(
                id=assertion.assertion_id,
                subject_entity_id=subject.entity_id if subject else None,
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
            )
            self.session.add(row)
            self.session.flush()
            evidence_element = (
                self.session.get(DocumentElementRecord, assertion.evidence_element_id)
                if assertion.evidence_element_id
                else None
            )
            self.session.add(
                AssertionEvidenceRecord(
                    assertion_id=row.id,
                    document_version_id=result.document_version_id,
                    element_id=assertion.evidence_element_id,
                    utterance_id=assertion.evidence_utterance_id,
                    evidence_text=assertion.evidence_text,
                    page_number=evidence_element.page_number if evidence_element else None,
                    bbox=evidence_element.bbox if evidence_element else None,
                )
            )
            assertion_count += 1

        for conflict in result.conflicts:
            if not self.session.get(ConflictGroupRecord, conflict.conflict_id):
                self.session.add(
                    ConflictGroupRecord(
                        id=conflict.conflict_id,
                        conflict_type=conflict.conflict_type.value,
                        assertion_ids=conflict.assertion_ids,
                        status=conflict.status.value,
                        rationale=conflict.rationale,
                    )
                )
        self.session.flush()
        return len(result.mentions), assertion_count, len(result.conflicts)

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
            restricted = self.session.scalar(
                select(DocumentVersion.id)
                .where(
                    and_(
                        DocumentVersion.id.in_(manifest.get("document_version_ids", [])),
                        DocumentVersion.license_status != LicenseStatus.PUBLIC.value,
                    )
                )
                .limit(1)
            )
            if restricted:
                raise ValueError("Public snapshots cannot contain restricted document versions")
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
