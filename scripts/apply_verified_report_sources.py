"""Apply SHA-256 verified exchange metadata to canonical report versions."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.contracts import (
    AccessClass,
    DocumentType,
    LicenseStatus,
    SourceRecordEnvelope,
)
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import Document, DocumentVersion, RawArtifactRecord
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.utils.hashing import sha256_file

SOURCE_DEFAULTS = {
    "cninfo": {
        "adapter_name": "cninfo_verified_filing",
        "base_url": "https://www.cninfo.com.cn/",
        "terms_url": "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
    },
    "sse": {
        "adapter_name": "sse_verified_filing",
        "base_url": "https://www.sse.com.cn/",
        "terms_url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
    },
}


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Verified source manifest must be a list")
    return [item for item in payload if isinstance(item, dict)]


def apply_entry(
    session: Session,
    repository: CanonicalRepository,
    entry: dict[str, Any],
    *,
    verified_at: datetime,
) -> dict[str, Any]:
    expected_hash = str(entry["content_hash"]).casefold()
    version = session.scalar(
        select(DocumentVersion).where(DocumentVersion.content_hash == expected_hash)
    )
    if version is None:
        raise RuntimeError(f"No document version has content hash {expected_hash}")
    artifact = session.get(RawArtifactRecord, version.artifact_id)
    document = session.get(Document, version.document_id)
    if artifact is None or document is None:
        raise RuntimeError(f"Version {version.id} has broken artifact/document references")
    local_hash = sha256_file(Path(artifact.object_path)).casefold()
    if local_hash != expected_hash:
        raise RuntimeError(f"Canonical artifact hash mismatch for version {version.id}")
    verification_copy = Path(str(entry["verification_copy"]))
    if not verification_copy.is_file():
        raise RuntimeError(f"Verification copy is missing: {verification_copy}")
    official_hash = sha256_file(verification_copy).casefold()
    if official_hash != expected_hash:
        raise RuntimeError(f"Official source hash mismatch for {entry['canonical_url']}")

    source_name = str(entry["source_name"])
    defaults = SOURCE_DEFAULTS[source_name]
    source = repository.ensure_source(
        name=source_name,
        adapter_name=str(defaults["adapter_name"]),
        authority_tier=str(entry["authority_tier"]),
        default_license_status=LicenseStatus.PUBLIC_ACCESS,
        base_url=str(defaults["base_url"]),
        terms_url=str(defaults["terms_url"]),
        metadata={"source_kind": "official_exchange_disclosure"},
    )
    published_at = datetime.fromisoformat(str(entry["published_at"]))
    envelope = SourceRecordEnvelope(
        source_name=source_name,
        source_record_id=str(entry["source_record_id"]),
        canonical_url=str(entry["canonical_url"]),
        title=document.title,
        published_at=published_at,
        license_status=LicenseStatus.PUBLIC_ACCESS,
        access_class=AccessClass.PUBLIC,
        document_type=DocumentType(document.document_type),
        raw_metadata={
            "authority_tier": entry["authority_tier"],
            "provenance_status": "verified_sha256",
            "content_hash": expected_hash,
            "verification_method": "downloaded_official_pdf_sha256",
            "verified_at": verified_at.isoformat(),
        },
    )
    source_record = repository.upsert_source_record(source, envelope)
    version.source_record_id = source_record.id
    version.canonical_url = str(entry["canonical_url"])
    version.published_at = published_at
    metadata = dict(version.metadata_json or {})
    metadata.update(
        {
            "canonical_url": str(entry["canonical_url"]),
            "published_at": published_at.isoformat(),
            "source_id": source_name,
            "source_name": source_name,
            "source_record_id": str(entry["source_record_id"]),
            "authority_tier": str(entry["authority_tier"]),
            "provenance_status": "verified_sha256",
            "authoritative_hash_verified": True,
            "authoritative_verified_at": verified_at.isoformat(),
            "metadata_review_required": False,
            "missing_formal_fields": [],
        }
    )
    version.metadata_json = metadata
    repository.ensure_access_grant(
        version=version,
        source_record=source_record,
        access_class=AccessClass.PUBLIC,
        license_status=LicenseStatus.PUBLIC_ACCESS,
        metadata=envelope.raw_metadata,
    )
    return {
        "document_id": document.id,
        "document_version_id": version.id,
        "content_hash": expected_hash,
        "source_name": source_name,
        "source_record_id": entry["source_record_id"],
        "canonical_url": entry["canonical_url"],
        "published_at": published_at.isoformat(),
        "sha256_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/verified_report_sources.json"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    verified_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    with Session(get_engine()) as session:
        repository = CanonicalRepository(session)
        for entry in _load_manifest(args.manifest):
            results.append(
                apply_entry(session, repository, entry, verified_at=verified_at)
            )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(
        json.dumps(
            {"status": "verified", "dry_run": args.dry_run, "documents": results},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
