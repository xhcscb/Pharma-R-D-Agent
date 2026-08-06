from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from pharma_data.cleaning import DataCleanAgent
from pharma_data.contracts import DocumentType, PipelineStatus, QualityLevel
from pharma_data.entity_extraction import DictionaryExtractor, EntityExtractAgent, PatternExtractor
from pharma_data.parsers import DocumentParser
from pharma_data.relation_extraction import RelationExtractAgent
from pharma_data.storage.canonical.models import (
    Document,
    DocumentVersion,
    ProcessingJob,
    RawArtifactRecord,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.utils.hashing import stable_hash


class PipelineRunner:
    def __init__(
        self,
        session: Session,
        *,
        lexicon_path: str | Path | None = "config/entities.json",
        document_parser: DocumentParser | None = None,
    ):
        self.session = session
        self.repository = CanonicalRepository(session)
        self.document_parser = document_parser or DocumentParser()
        dictionary = DictionaryExtractor(lexicon_path) if lexicon_path else DictionaryExtractor()
        self.entity_agent = EntityExtractAgent([dictionary, PatternExtractor()])
        self.relation_agent = RelationExtractAgent()
        self.clean_agent = DataCleanAgent()

    def run(self, job_id: str) -> dict[str, object]:
        job = self.session.get(ProcessingJob, job_id)
        if job is None:
            raise KeyError(job_id)
        version = self.session.get(DocumentVersion, job.document_version_id)
        if version is None:
            raise KeyError(job.document_version_id)
        document = self.session.get(Document, version.document_id)
        artifact = self.session.get(RawArtifactRecord, version.artifact_id)
        if document is None or artifact is None:
            raise RuntimeError("Document version has broken document/artifact references")

        trace_id = str(uuid4())
        run = self.repository.start_run(
            job,
            trace_id=trace_id,
            producer="controlled-data-pipeline",
            producer_version="0.1.0",
            schema_version="1.0",
            input_hash=version.content_hash,
        )
        try:
            parsed = self.document_parser.parse(
                artifact.object_path,
                media_type=artifact.media_type,
                document_id=document.id,
                document_version_id=version.id,
                document_type=DocumentType(document.document_type),
                artifact_id=artifact.id,
            )
            element_count, utterance_count = self.repository.save_parsed_document(parsed, run)
            job.status = PipelineStatus.PARSED.value

            mentions = self.entity_agent.extract(parsed)
            job.status = PipelineStatus.ENTITY_EXTRACTED.value

            assertions = self.relation_agent.extract(parsed, mentions)
            assertions.extend(self.relation_agent.derive_competition(assertions, mentions))
            job.status = PipelineStatus.RELATION_EXTRACTED.value

            clean = self.clean_agent.clean(
                document_version_id=version.id,
                mentions=mentions,
                assertions=assertions,
            )
            mention_count, assertion_count, conflict_count = self.repository.save_clean_result(
                clean
            )
            job.status = (
                PipelineStatus.NEEDS_REVIEW.value
                if clean.quality_level
                in {QualityLevel.CANDIDATE, QualityLevel.SILVER, QualityLevel.CONFLICT}
                else PipelineStatus.CLEANED.value
            )
            job.locked_at = None
            job.locked_by = None
            run.status = job.status
            run.output_hash = stable_hash(clean.model_dump(mode="json"))
            run.finished_at = datetime.now(UTC)
            self.session.flush()
            return {
                "job_id": job.id,
                "trace_id": trace_id,
                "status": job.status,
                "elements": element_count,
                "utterances": utterance_count,
                "mentions": mention_count,
                "assertions": assertion_count,
                "conflicts": conflict_count,
                "quality_level": clean.quality_level.value,
            }
        except Exception as exc:
            job.status = (
                PipelineStatus.FAILED_RETRYABLE.value
                if job.attempts < 3
                else PipelineStatus.FAILED_FINAL.value
            )
            job.last_error = f"{type(exc).__name__}: {exc}"
            job.locked_at = None
            job.locked_by = None
            run.status = job.status
            run.errors = [job.last_error]
            run.finished_at = datetime.now(UTC)
            self.session.flush()
            raise
