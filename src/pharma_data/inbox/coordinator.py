from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from pharma_data.config import Settings
from pharma_data.contracts import AccessClass, LicenseStatus
from pharma_data.inbox.service import InboxService
from pharma_data.storage.object_store import LocalObjectStore


class InboxCoordinator:
    """Coordinate the public and restricted filesystem inboxes."""

    def __init__(self, services: dict[str, InboxService]) -> None:
        self.services = services

    def status(self, *, include_files: bool = True) -> dict[str, Any]:
        inboxes = {
            name: service.status(include_files=include_files)
            for name, service in self.services.items()
        }
        states: Counter[str] = Counter()
        recent: list[dict[str, Any]] = []
        pending: list[dict[str, str]] = []
        for name, payload in inboxes.items():
            states.update(payload["states"])
            if include_files:
                pending.extend(
                    {"access_class": name, "filename": filename}
                    for filename in payload.get("pending", [])
                )
                recent.extend(
                    {**item, "access_class": name}
                    for item in payload.get("recent", [])
                )
        recent.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        result: dict[str, Any] = {
            "schema_version": "2.0",
            "enabled": True,
            "access_classes": list(self.services),
            "inbox_roots": {
                name: payload["inbox_root"] for name, payload in inboxes.items()
            },
            "inbox_root": " | ".join(
                f"{name}: {payload['inbox_root']}" for name, payload in inboxes.items()
            ),
            "pending_files": sum(int(item["pending_files"]) for item in inboxes.values()),
            "receipt_count": sum(int(item["receipt_count"]) for item in inboxes.values()),
            "states": dict(sorted(states.items())),
            "metadata_review_required": sum(
                int(item["metadata_review_required"]) for item in inboxes.values()
            ),
            "failed": sum(int(item["failed"]) for item in inboxes.values()),
            "last_updated_at": max(
                (
                    str(item["last_updated_at"])
                    for item in inboxes.values()
                    if item["last_updated_at"]
                ),
                default=None,
            ),
            "inboxes": inboxes,
        }
        if include_files:
            result["pending"] = pending
            result["recent"] = recent[:20]
        return result

    def run_once(
        self,
        session: Session,
        object_store: LocalObjectStore,
        *,
        run_pipeline: bool = False,
        max_files: int | None = None,
    ) -> dict[str, Any]:
        reports: dict[str, dict[str, Any]] = {}
        remaining = max_files
        for name, service in self.services.items():
            if remaining == 0:
                break
            report = service.run_once(
                session,
                object_store,
                run_pipeline=run_pipeline,
                max_files=remaining,
            )
            reports[name] = report
            if remaining is not None:
                remaining = max(remaining - int(report["files_seen"]), 0)
        counts: Counter[str] = Counter()
        items: list[dict[str, Any]] = []
        for name, report in reports.items():
            counts.update(report["counts"])
            items.extend({**item, "access_class": name} for item in report["items"])
        now = datetime.now(UTC)
        return {
            "schema_version": "2.0",
            "batch_id": f"dual-inbox-{now:%Y%m%dT%H%M%SZ}",
            "finished_at": now.isoformat(),
            "files_seen": len(items),
            "counts": dict(sorted(counts.items())),
            "items": items,
            "inboxes": reports,
        }

    def refresh_job_receipt(
        self,
        session: Session,
        job_id: str,
        pipeline_result: dict[str, object] | None = None,
    ) -> None:
        for service in self.services.values():
            service.refresh_job_receipt(session, job_id, pipeline_result)


def build_inbox_coordinator(settings: Settings) -> InboxCoordinator:
    return InboxCoordinator(
        {
            AccessClass.PUBLIC.value: InboxService(
                inbox_root=settings.public_inbox_root,
                archive_root=settings.public_inbox_archive_root,
                metadata_root=settings.public_inbox_metadata_root,
                quarantine_root=settings.public_inbox_quarantine_root,
                access_class=AccessClass.PUBLIC,
                default_license_status=LicenseStatus.PUBLIC_ACCESS,
                source_catalog_path=settings.authoritative_source_catalog_path,
                archive_mode=settings.inbox_archive_mode,
                settle_seconds=settings.inbox_settle_seconds,
            ),
            AccessClass.RESTRICTED.value: InboxService(
                inbox_root=settings.restricted_inbox_root,
                archive_root=settings.restricted_inbox_archive_root,
                metadata_root=settings.restricted_inbox_metadata_root,
                quarantine_root=settings.restricted_inbox_quarantine_root,
                access_class=AccessClass.RESTRICTED,
                default_license_status=LicenseStatus.AUTHORIZED_RESTRICTED,
                source_catalog_path=settings.authoritative_source_catalog_path,
                archive_mode=settings.inbox_archive_mode,
                settle_seconds=settings.inbox_settle_seconds,
            ),
        }
    )
