from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from pharma_data.cleaning import DataCleanAgent
from pharma_data.config import get_settings
from pharma_data.contracts import DocumentType, ParsedDocument, PipelineStatus, QualityLevel
from pharma_data.entity_extraction import (
    DictionaryExtractor,
    EntityExtractAgent,
    PatternExtractor,
    VisualSemanticExtractor,
)
from pharma_data.parsers import DocumentParser
from pharma_data.relation_extraction import RelationExtractAgent
from pharma_data.storage.canonical.access import version_access_classes
from pharma_data.storage.canonical.models import (
    Document,
    DocumentVersion,
    ProcessingJob,
    RawArtifactRecord,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.utils.hashing import stable_hash, stable_uuid


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
        self.entity_agent = EntityExtractAgent(
            [dictionary, PatternExtractor(), VisualSemanticExtractor()]
        )
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
        settings = get_settings()
        document_access = set(version_access_classes(self.session, version))
        unauthorized = document_access - settings.mineru_allowed_access_class_set()
        if settings.mineru_enabled and unauthorized:
            raise RuntimeError(
                "Configured MinerU backend is not authorized for access classes: "
                + ", ".join(sorted(unauthorized))
            )

        trace_id = str(uuid4())
        job.status = PipelineStatus.PROCESSING.value
        job.locked_at = datetime.now(UTC)
        job.locked_by = job.locked_by or "pipeline-runner"
        run = self.repository.start_run(
            job,
            trace_id=trace_id,
            producer="controlled-data-pipeline",
            producer_version="0.3.0",
            schema_version="2.0",
            input_hash=version.content_hash,
        )
        # A GPU/OCR parse can run for hours. Persist the audit envelope before doing
        # that work so SQLite does not retain a writer lock for the whole parse.
        self.session.commit()
        try:
            parsed = self.document_parser.parse(
                _resolve_artifact_path(artifact, settings.object_store_root),
                media_type=artifact.media_type,
                document_id=document.id,
                document_version_id=version.id,
                document_type=DocumentType(document.document_type),
                artifact_id=artifact.id,
            )
            parsed = _bind_artifacts_to_run(parsed, run.id)
            element_count, utterance_count = self.repository.save_parsed_document(parsed, run)
            job.status = PipelineStatus.PARSED.value
            # The parse is independently auditable and remains current even if a
            # later fact-extraction stage needs to be retried.
            self.session.commit()

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


def _bind_artifacts_to_run(parsed: ParsedDocument, run_id: str) -> ParsedDocument:
    """Give every parse run independent locators while retaining source IDs for audit."""
    element_ids = {
        element.element_id: stable_uuid(
            {
                "parse_run_id": run_id,
                "source_element_id": element.element_id,
            }
        )
        for element in parsed.elements
    }
    elements = [
        element.model_copy(
            update={
                "element_id": element_ids[element.element_id],
                "structured_payload": {
                    **element.structured_payload,
                    "source_element_id": element.element_id,
                },
                "footnote_links": [
                    element_ids.get(link, link) for link in element.footnote_links
                ],
            }
        )
        for element in parsed.elements
    ]
    utterances = [
        utterance.model_copy(
            update={
                "utterance_id": stable_uuid(
                    {
                        "parse_run_id": run_id,
                        "source_utterance_id": utterance.utterance_id,
                    }
                )
            }
        )
        for utterance in parsed.utterances
    ]
    return parsed.model_copy(update={"elements": elements, "utterances": utterances})


def _resolve_artifact_path(artifact: RawArtifactRecord, object_store_root: Path) -> Path:
    """Resolve a content-addressed object across Windows-host and Linux-container paths."""
    configured = object_store_root / artifact.content_hash[:2] / artifact.content_hash
    original = Path(artifact.object_path)
    normalized = Path(str(artifact.object_path).replace("\\", "/"))
    for candidate in (original, normalized, configured):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Artifact is missing from both its recorded path and content-addressed store: "
        f"content_hash={artifact.content_hash}, configured_path={configured}"
    )
