"""Create immutable public and restricted internal-trial snapshots for current versions."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.contracts import AccessClass
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import Document, DocumentVersion
from pharma_data.storage.canonical.repository import CanonicalRepository


def main() -> None:
    with Session(get_engine()) as session:
        versions = list(
            session.scalars(
                select(DocumentVersion)
                .join(Document, Document.current_version_id == DocumentVersion.id)
                .order_by(DocumentVersion.id)
            )
        )
        if not versions or any(row.active_parse_run_id is None for row in versions):
            raise RuntimeError("All current versions must have an active parse run")
        manifest = {
            "document_version_ids": [row.id for row in versions],
            "active_parse_run_ids": {
                row.id: row.active_parse_run_id for row in versions
            },
        }
        specification = {
            "schema_version": "2.0",
            "fact_selection": "current_active_parse_runs_only",
            "formal_reasoning_default": "approved_only",
            "candidate_usage": "internal_review_only",
            "gold_gate": "not_evaluated_no_human_gold",
            "status": "quality_first_engineering_baseline_internal_trial",
        }
        created = []
        repository = CanonicalRepository(session)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        for access_class in (AccessClass.PUBLIC, AccessClass.RESTRICTED):
            snapshot = repository.create_snapshot(
                name=f"current-reports-{access_class.value}-{stamp}",
                specification=specification,
                manifest=manifest,
                access_class=access_class,
                created_by="data-layer-activation",
            )
            created.append(
                {
                    "id": snapshot.id,
                    "name": snapshot.name,
                    "access_class": snapshot.access_class,
                    "snapshot_hash": snapshot.snapshot_hash,
                }
            )
        session.commit()
    print(json.dumps({"status": "created", "snapshots": created}, ensure_ascii=False))


if __name__ == "__main__":
    main()
