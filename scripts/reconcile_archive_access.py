"""Reconcile public/restricted archive presence into document access grants."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from pharma_data.config import get_settings
from pharma_data.contracts import (
    AccessClass,
    DocumentType,
    LicenseStatus,
    SourceRecordEnvelope,
)
from pharma_data.storage.canonical import session_scope
from pharma_data.storage.canonical.models import Document, DocumentVersion
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.utils.hashing import sha256_file


def _files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.name.lower().endswith(".json")
    )


def reconcile() -> dict[str, int]:
    settings = get_settings()
    scopes = [
        (
            AccessClass.PUBLIC,
            LicenseStatus.PUBLIC_ACCESS,
            settings.public_inbox_archive_root,
        ),
        (
            AccessClass.RESTRICTED,
            LicenseStatus.AUTHORIZED_RESTRICTED,
            settings.restricted_inbox_archive_root,
        ),
    ]
    counts = {"files": 0, "matched_versions": 0, "grants": 0, "unmatched": 0}
    with session_scope() as session:
        repository = CanonicalRepository(session)
        for access_class, license_status, root in scopes:
            source = repository.ensure_source(
                name=f"local-{access_class.value}-archive",
                adapter_name="ArchiveGrantReconciler",
                authority_tier="A3",
                default_license_status=license_status,
                metadata={"archive_root": str(root.resolve())},
            )
            for path in _files(root):
                counts["files"] += 1
                content_hash = sha256_file(path)
                versions = list(
                    session.scalars(
                        select(DocumentVersion).where(
                            DocumentVersion.content_hash == content_hash
                        )
                    )
                )
                if not versions:
                    counts["unmatched"] += 1
                    continue
                counts["matched_versions"] += len(versions)
                for version in versions:
                    document = session.get(Document, version.document_id)
                    if document is None:
                        continue
                    metadata = {
                        "provenance_status": "archive_presence_verified",
                        "archive_path": str(path.resolve()),
                        "content_hash": content_hash,
                        "reconciled_at": datetime.now(UTC).isoformat(),
                    }
                    envelope = SourceRecordEnvelope(
                        source_name=source.name,
                        source_record_id=f"sha256:{content_hash}",
                        title=document.title,
                        published_at=version.published_at,
                        license_status=license_status,
                        access_class=access_class,
                        document_type=DocumentType(document.document_type),
                        raw_metadata=metadata,
                    )
                    source_record = repository.upsert_source_record(source, envelope)
                    repository.ensure_access_grant(
                        version=version,
                        source_record=source_record,
                        access_class=access_class,
                        license_status=license_status,
                        metadata=metadata,
                    )
                    counts["grants"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(reconcile())


if __name__ == "__main__":
    main()
