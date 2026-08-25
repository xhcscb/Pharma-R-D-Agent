import json
import re
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.connectors.inbox import InboxAdapter
from pharma_data.contracts import AccessClass, DocumentType, LicenseStatus, SourceRecordEnvelope
from pharma_data.inbox.metadata import InboxCandidate, build_candidate
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical.models import (
    Document,
    DocumentAccessGrantRecord,
    DocumentVersion,
    ProcessingJob,
    RawArtifactRecord,
)
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore
from pharma_data.utils.hashing import sha256_file, stable_hash

ArchiveMode = Literal["move", "copy", "none"]
PROCESSED_RECEIPT_STATES = {
    "queued",
    "metadata_only",
    "needs_review",
    "completed",
    "failed_final",
    "quarantined",
}


class InboxService:
    """扫描本地投递箱，自动建档、入库并按内容哈希归档。"""

    def __init__(
        self,
        *,
        inbox_root: Path,
        archive_root: Path,
        metadata_root: Path,
        quarantine_root: Path,
        source_catalog_path: Path = Path("config/authoritative_sources.json"),
        access_class: AccessClass = AccessClass.RESTRICTED,
        default_license_status: LicenseStatus = LicenseStatus.AUTHORIZED_RESTRICTED,
        archive_mode: ArchiveMode = "move",
        settle_seconds: float = 5.0,
    ) -> None:
        if archive_mode not in {"move", "copy", "none"}:
            raise ValueError("archive_mode must be move, copy, or none")
        self.inbox_root = inbox_root
        self.archive_root = archive_root
        self.metadata_root = metadata_root
        self.quarantine_root = quarantine_root
        self.source_catalog_path = source_catalog_path
        self.access_class = access_class
        self.default_license_status = default_license_status
        self.archive_mode = archive_mode
        self.settle_seconds = settle_seconds
        self.ensure_directories()

    def ensure_directories(self) -> None:
        for path in (
            self.inbox_root,
            self.archive_root,
            self.metadata_root,
            self.quarantine_root,
            self.metadata_root / "manifests",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def scan(self, *, max_files: int | None = None) -> list[Path]:
        now = datetime.now(UTC).timestamp()
        paths = [
            path
            for path in self.inbox_root.iterdir()
            if path.is_file()
            and not path.name.startswith(".")
            and not path.name.lower().endswith(".metadata.json")
            and (
                self.settle_seconds == 0
                or now - path.stat().st_mtime >= self.settle_seconds
            )
        ]
        paths.sort(key=lambda item: (item.stat().st_mtime, item.name.casefold()))
        return paths[:max_files] if max_files is not None else paths

    def run_once(
        self,
        session: Session,
        object_store: LocalObjectStore,
        *,
        run_pipeline: bool = False,
        max_files: int | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now(UTC)
        batch_id = f"inbox-{started_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        results: list[dict[str, Any]] = []
        for path in self.scan(max_files=max_files):
            try:
                results.append(
                    self._process_file(
                        session,
                        object_store,
                        path,
                        batch_id=batch_id,
                        run_pipeline=run_pipeline,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad drop must not stop the batch
                results.append(self._record_failure(path, batch_id, exc))
        finished_at = datetime.now(UTC)
        counts = Counter(str(item["state"]) for item in results)
        report: dict[str, Any] = {
            "schema_version": "1.0",
            "batch_id": batch_id,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "inbox_root": str(self.inbox_root.resolve()),
            "archive_root": str(self.archive_root.resolve()),
            "metadata_root": str(self.metadata_root.resolve()),
            "archive_mode": self.archive_mode,
            "files_seen": len(results),
            "counts": dict(sorted(counts.items())),
            "items": results,
        }
        if results:
            manifest_path = self.metadata_root / "manifests" / f"{batch_id}.json"
            report["manifest_path"] = str(manifest_path.resolve())
            self._write_json(manifest_path, report)
        else:
            report["manifest_path"] = None
        return report

    def status(self, *, include_files: bool = True) -> dict[str, Any]:
        pending = self.scan()
        receipts = []
        for path in sorted(
            self.metadata_root.glob("*.metadata.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                receipts.append(payload)
        states = Counter(
            str(item.get("lifecycle", {}).get("state") or "unknown") for item in receipts
        )
        result: dict[str, Any] = {
            "enabled": True,
            "access_class": self.access_class.value,
            "inbox_root": str(self.inbox_root.resolve()),
            "archive_root": str(self.archive_root.resolve()),
            "metadata_root": str(self.metadata_root.resolve()),
            "archive_mode": self.archive_mode,
            "pending_files": len(pending),
            "receipt_count": len(receipts),
            "states": dict(sorted(states.items())),
            "metadata_review_required": sum(
                bool(item.get("metadata", {}).get("metadata_review_required"))
                for item in receipts
            ),
            "failed": sum(
                count for state, count in states.items() if state.startswith("failed")
            ),
            "last_updated_at": max(
                (
                    value
                    for item in receipts
                    if (value := item.get("lifecycle", {}).get("updated_at"))
                ),
                default=None,
            ),
        }
        if include_files:
            result["pending"] = [path.name for path in pending]
            result["recent"] = [
                {
                    "original_filename": item.get("metadata", {}).get("original_filename"),
                    "title": item.get("metadata", {}).get("title"),
                    "document_type": item.get("metadata", {}).get("document_type"),
                    "provenance_status": item.get("metadata", {}).get("provenance_status"),
                    "state": item.get("lifecycle", {}).get("state"),
                    "archive_path": item.get("archive", {}).get("path"),
                    "job_ids": item.get("ingestion", {}).get("job_ids", []),
                    "updated_at": item.get("lifecycle", {}).get("updated_at"),
                }
                for item in receipts[:20]
            ]
        return result

    def refresh_job_receipt(
        self,
        session: Session,
        job_id: str,
        pipeline_result: dict[str, object] | None = None,
    ) -> None:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            return
        receipt_value = job.payload.get("inbox_receipt_path")
        if not receipt_value:
            return
        receipt_path = Path(str(receipt_value)).resolve()
        if (
            not receipt_path.is_relative_to(self.metadata_root.resolve())
            or not receipt_path.is_file()
        ):
            return
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        ingestion = payload.setdefault("ingestion", {})
        results = ingestion.setdefault("pipeline_results", [])
        if pipeline_result and not any(item.get("job_id") == job_id for item in results):
            results.append(pipeline_result)
        ingestion["job_statuses"] = self._job_statuses(session, ingestion.get("job_ids", []))
        lifecycle = payload.setdefault("lifecycle", {})
        lifecycle["state"] = self._receipt_state(ingestion["job_statuses"])
        lifecycle["updated_at"] = datetime.now(UTC).isoformat()
        self._write_json(receipt_path, payload)

    def _process_file(
        self,
        session: Session,
        object_store: LocalObjectStore,
        path: Path,
        *,
        batch_id: str,
        run_pipeline: bool,
    ) -> dict[str, Any]:
        candidate = build_candidate(
            path,
            source_catalog_path=self.source_catalog_path,
            folder_access_class=self.access_class,
            default_license_status=self.default_license_status,
        )
        receipt_path = self.metadata_root / f"{candidate.content_hash}.metadata.json"
        existing = self._read_receipt(receipt_path)
        existing_versions = list(
            session.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.content_hash == candidate.content_hash
                )
            )
        )
        granted_version_ids = set(
            session.scalars(
                select(DocumentAccessGrantRecord.document_version_id).where(
                    DocumentAccessGrantRecord.document_version_id.in_(
                        [version.id for version in existing_versions]
                    ),
                    DocumentAccessGrantRecord.access_class
                    == str(candidate.metadata["access_class"]),
                    DocumentAccessGrantRecord.active.is_(True),
                )
            )
        )
        metadata_changed = bool(existing_versions) and (
            existing is None
            or existing.get("metadata", {}).get("user_metadata")
            != candidate.metadata.get("user_metadata")
            or any(version.id not in granted_version_ids for version in existing_versions)
        )
        if existing_versions and metadata_changed:
            return self._enrich_existing(
                session,
                candidate,
                existing_versions,
                receipt_path,
                existing or {},
                batch_id,
            )
        if (
            existing
            and existing_versions
            and existing.get("lifecycle", {}).get("state") in PROCESSED_RECEIPT_STATES
        ):
            archive_path = self._archive_candidate(candidate)
            return {
                "filename": path.name,
                "content_hash": candidate.content_hash,
                "state": "duplicate_skipped",
                "receipt_path": str(receipt_path.resolve()),
                "archive_path": str(archive_path.resolve()),
            }

        planned_archive = self._archive_target(candidate)
        metadata = {
            **candidate.metadata,
            "inbox_batch_id": batch_id,
            "planned_archive_path": str(planned_archive.resolve()),
        }
        envelope = SourceRecordEnvelope(
            source_name=str(candidate.source_profile["source_name"]),
            source_record_id=f"sha256:{candidate.content_hash}",
            canonical_url=metadata.get("canonical_url"),
            title=str(metadata["title"]),
            published_at=metadata.get("published_at"),
            license_status=LicenseStatus(str(metadata["license_status"])),
            access_class=AccessClass(str(metadata["access_class"])),
            document_type=DocumentType(str(metadata["document_type"])),
            raw_metadata=metadata,
        )
        adapter = InboxAdapter(
            path=path,
            envelope=envelope,
            source_name=str(candidate.source_profile["source_name"]),
            authority_tier=str(candidate.source_profile["authority_tier"]),
            base_url=candidate.source_profile.get("base_url"),
            terms_url=candidate.source_profile.get("terms_url"),
        )
        report = IngestionService(session, object_store).ingest(adapter, {})
        pipeline_results: list[dict[str, object]] = []
        runnable_job_ids = [
            job_id
            for job_id in report.job_ids
            if (job := session.get(ProcessingJob, job_id)) is not None
            and job.status in {"FETCHED", "FAILED_RETRYABLE"}
        ]
        if run_pipeline:
            for job_id in runnable_job_ids:
                pipeline_results.append(PipelineRunner(session).run(job_id))
        archive_path = self._archive_candidate(candidate)
        job_statuses = self._job_statuses(session, report.job_ids)
        state = self._receipt_state(job_statuses)
        now = datetime.now(UTC).isoformat()
        receipt: dict[str, Any] = {
            "schema_version": "1.0",
            "metadata": metadata,
            "archive": {
                "mode": self.archive_mode,
                "path": str(archive_path.resolve()),
                "content_hash_verified": sha256_file(archive_path) == candidate.content_hash
                if archive_path.is_file()
                else self.archive_mode == "none",
            },
            "ingestion": {
                **asdict(report),
                "job_statuses": job_statuses,
                "pipeline_results": pipeline_results,
            },
            "lifecycle": {
                "state": state,
                "batch_id": batch_id,
                "created_at": now,
                "updated_at": now,
            },
        }
        for job_id in report.job_ids:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                job.payload = {
                    **job.payload,
                    "inbox_content_hash": candidate.content_hash,
                    "inbox_receipt_path": str(receipt_path.resolve()),
                }
        self._write_json(receipt_path, receipt)
        return {
            "filename": path.name,
            "title": metadata["title"],
            "content_hash": candidate.content_hash,
            "document_type": metadata["document_type"],
            "provenance_status": metadata["provenance_status"],
            "metadata_review_required": metadata["metadata_review_required"],
            "state": state,
            "receipt_path": str(receipt_path.resolve()),
            "archive_path": str(archive_path.resolve()),
            "document_ids": report.document_ids,
            "document_version_ids": report.document_version_ids,
            "job_ids": report.job_ids,
            "pipeline_results": pipeline_results,
        }

    def _enrich_existing(
        self,
        session: Session,
        candidate: InboxCandidate,
        versions: list[DocumentVersion],
        receipt_path: Path,
        existing_receipt: dict[str, Any],
        batch_id: str,
    ) -> dict[str, Any]:
        planned_archive = self._archive_target(candidate)
        metadata = {
            **candidate.metadata,
            "inbox_batch_id": batch_id,
            "planned_archive_path": str(planned_archive.resolve()),
        }
        envelope = SourceRecordEnvelope(
            source_name=str(candidate.source_profile["source_name"]),
            source_record_id=f"sha256:{candidate.content_hash}",
            canonical_url=metadata.get("canonical_url"),
            title=str(metadata["title"]),
            published_at=metadata.get("published_at"),
            license_status=LicenseStatus(str(metadata["license_status"])),
            access_class=AccessClass(str(metadata["access_class"])),
            document_type=DocumentType(str(metadata["document_type"])),
            raw_metadata=metadata,
        )
        repository = CanonicalRepository(session)
        source = repository.ensure_source(
            name=str(candidate.source_profile["source_name"]),
            adapter_name="InboxAdapter",
            authority_tier=str(candidate.source_profile["authority_tier"]),
            default_license_status=envelope.license_status,
            base_url=candidate.source_profile.get("base_url"),
            terms_url=candidate.source_profile.get("terms_url"),
        )
        target_record = repository.upsert_source_record(source, envelope)

        document_ids: list[str] = []
        artifact_ids: list[str] = []
        version_ids: list[str] = []
        for version in versions:
            repository.ensure_access_grant(
                version=version,
                source_record=target_record,
                access_class=envelope.access_class,
                license_status=envelope.license_status,
                metadata=metadata,
            )
            version.published_at = version.published_at or envelope.published_at
            version.metadata_json = {**version.metadata_json, **metadata}
            version_ids.append(version.id)
            artifact = session.get(RawArtifactRecord, version.artifact_id)
            if artifact is not None:
                artifact_ids.append(artifact.id)
            document = session.get(Document, version.document_id)
            if document is not None:
                document.title = envelope.title
                document.document_type = envelope.document_type.value
                document_ids.append(document.id)
        jobs = list(
            session.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.document_version_id.in_(version_ids)
                )
            )
        )
        job_ids = [job.id for job in jobs]
        job_statuses = {job.id: job.status for job in jobs}
        archive_path = self._archive_candidate(candidate)
        now = datetime.now(UTC).isoformat()
        pipeline_results = [
            item
            for item in existing_receipt.get("ingestion", {}).get("pipeline_results", [])
            if item.get("job_id") in job_ids
        ]
        state = self._receipt_state(job_statuses)
        receipt = {
            "schema_version": "1.0",
            "metadata": metadata,
            "archive": {
                "mode": self.archive_mode,
                "path": str(archive_path.resolve()),
                "content_hash_verified": sha256_file(archive_path) == candidate.content_hash,
            },
            "ingestion": {
                "records_discovered": 0,
                "artifacts_stored": 0,
                "versions_created": 0,
                "jobs_enqueued": 0,
                "quarantined_records": 0,
                "source_record_ids": [target_record.id],
                "artifact_ids": sorted(set(artifact_ids)),
                "document_ids": sorted(set(document_ids)),
                "document_version_ids": sorted(set(version_ids)),
                "job_ids": job_ids,
                "enqueued_job_ids": [],
                "job_statuses": job_statuses,
                "pipeline_results": pipeline_results,
            },
            "lifecycle": {
                "state": state,
                "batch_id": batch_id,
                "created_at": existing_receipt.get("lifecycle", {}).get("created_at") or now,
                "updated_at": now,
                "last_operation": "access_grant_added",
            },
        }
        for job in jobs:
            job.payload = {
                **job.payload,
                "inbox_content_hash": candidate.content_hash,
                "inbox_receipt_path": str(receipt_path.resolve()),
            }
        self._write_json(receipt_path, receipt)
        return {
            "filename": candidate.path.name,
            "title": metadata["title"],
            "content_hash": candidate.content_hash,
            "document_type": metadata["document_type"],
            "provenance_status": metadata["provenance_status"],
            "metadata_review_required": metadata["metadata_review_required"],
            "state": state,
            "operation": "access_grant_added",
            "receipt_path": str(receipt_path.resolve()),
            "archive_path": str(archive_path.resolve()),
            "document_ids": document_ids,
            "document_version_ids": version_ids,
            "job_ids": job_ids,
            "pipeline_results": pipeline_results,
        }

    def _archive_target(self, candidate: InboxCandidate) -> Path:
        period = str(candidate.metadata.get("report_period") or "")
        year = period[:4] if re.fullmatch(r"20\d{2}-.+", period) else f"{datetime.now(UTC):%Y}"
        return (
            self.archive_root
            / str(candidate.metadata["document_type"])
            / year
            / candidate.content_hash[:2]
            / f"{candidate.content_hash}{candidate.path.suffix.lower()}"
        )

    def _archive_candidate(self, candidate: InboxCandidate) -> Path:
        if self.archive_mode == "none":
            return candidate.path
        target = self._archive_target(candidate)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            if sha256_file(target) != candidate.content_hash:
                raise RuntimeError(f"Archive hash collision at {target}")
            if self.archive_mode == "move" and candidate.path.exists():
                candidate.path.unlink()
        elif self.archive_mode == "move":
            candidate.path.replace(target)
        else:
            shutil.copy2(candidate.path, target)
        if candidate.sidecar_path and candidate.sidecar_path.is_file():
            sidecar_target = target.with_name(f"{target.name}.user-metadata.json")
            if self.archive_mode == "move":
                candidate.sidecar_path.replace(sidecar_target)
            elif not sidecar_target.exists():
                shutil.copy2(candidate.sidecar_path, sidecar_target)
        return target

    def _record_failure(self, path: Path, batch_id: str, exc: Exception) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        error = f"{type(exc).__name__}: {exc}"
        try:
            content_hash = sha256_file(path)
        except OSError:
            content_hash = stable_hash({"path": str(path.resolve()), "batch_id": batch_id})
        receipt_path = self.metadata_root / f"{content_hash}.metadata.json"
        quarantine_path = self._quarantine(path, content_hash)
        payload = {
            "schema_version": "1.0",
            "metadata": {
                "original_filename": path.name,
                "content_hash": content_hash,
                "metadata_review_required": True,
            },
            "archive": {"mode": "quarantine", "path": str(quarantine_path.resolve())},
            "ingestion": {"errors": [error], "job_ids": []},
            "lifecycle": {
                "state": "quarantined",
                "batch_id": batch_id,
                "created_at": now,
                "updated_at": now,
            },
        }
        self._write_json(receipt_path, payload)
        return {
            "filename": path.name,
            "content_hash": content_hash,
            "state": "quarantined",
            "error": error,
            "receipt_path": str(receipt_path.resolve()),
            "archive_path": str(quarantine_path.resolve()),
        }

    def _quarantine(self, path: Path, content_hash: str) -> Path:
        target = self.quarantine_root / f"{content_hash[:12]}__{path.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not target.exists():
            path.replace(target)
        return target

    @staticmethod
    def _job_statuses(session: Session, job_ids: list[str]) -> dict[str, str]:
        statuses = {}
        for job_id in job_ids:
            job = session.get(ProcessingJob, job_id)
            if job is not None:
                statuses[job_id] = job.status
        return statuses

    @staticmethod
    def _receipt_state(job_statuses: dict[str, str]) -> str:
        states = set(job_statuses.values())
        if not states:
            return "metadata_only"
        if states & {"FAILED_FINAL"}:
            return "failed_final"
        if states & {"FAILED_RETRYABLE"}:
            return "failed_retryable"
        if states & {"FETCHED", "PARSED", "ENTITY_EXTRACTED", "RELATION_EXTRACTED"}:
            return "queued"
        if states & {"NEEDS_REVIEW"}:
            return "needs_review"
        if states <= {"CLEANED", "APPROVED", "PROJECTED"}:
            return "completed"
        return "queued"

    @staticmethod
    def _read_receipt(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, dict) else None

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.partial")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)
