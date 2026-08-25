from collections.abc import Iterable
from typing import Any

from sqlalchemy import exists, select, union
from sqlalchemy.orm import Session

from pharma_data.storage.canonical.models import (
    DocumentAccessGrantRecord,
    DocumentVersion,
)


def visible_version_ids(allowed_access_classes: Iterable[str]) -> Any:
    """Return version IDs visible through grants, with a legacy-row fallback."""
    access = tuple(allowed_access_classes)
    granted = select(DocumentAccessGrantRecord.document_version_id.label("id")).where(
        DocumentAccessGrantRecord.active.is_(True),
        DocumentAccessGrantRecord.access_class.in_(access),
    )
    any_grant = exists(
        select(DocumentAccessGrantRecord.id).where(
            DocumentAccessGrantRecord.document_version_id == DocumentVersion.id,
            DocumentAccessGrantRecord.active.is_(True),
        )
    )
    legacy = select(DocumentVersion.id.label("id")).where(
        ~any_grant,
        DocumentVersion.access_class.in_(access),
    )
    return union(granted, legacy)


def version_has_access(
    session: Session,
    version: DocumentVersion,
    allowed_access_classes: Iterable[str],
) -> bool:
    access = tuple(allowed_access_classes)
    grants = list(
        session.scalars(
            select(DocumentAccessGrantRecord).where(
                DocumentAccessGrantRecord.document_version_id == version.id,
                DocumentAccessGrantRecord.active.is_(True),
            )
        )
    )
    if grants:
        return any(grant.access_class in access for grant in grants)
    return version.access_class in access


def version_access_classes(session: Session, version: DocumentVersion) -> list[str]:
    grants = list(
        session.scalars(
            select(DocumentAccessGrantRecord.access_class).where(
                DocumentAccessGrantRecord.document_version_id == version.id,
                DocumentAccessGrantRecord.active.is_(True),
            )
        )
    )
    return sorted(set(grants or [version.access_class]))
