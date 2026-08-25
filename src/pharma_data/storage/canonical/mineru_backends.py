from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from pharma_data.config import Settings, get_settings
from pharma_data.parsers.mineru import mineru_status
from pharma_data.storage.canonical.models import MineruBackendRecord


def sync_configured_mineru_backend(
    session: Session, settings: Settings | None = None
) -> MineruBackendRecord:
    """Persist non-secret backend capabilities and the latest verified health."""
    resolved = settings or get_settings()
    health = mineru_status(resolved)
    row = session.get(MineruBackendRecord, resolved.mineru_node_id)
    checked_at = datetime.now(UTC)
    previous_metadata = dict(row.metadata_json or {}) if row is not None else {}
    live_ready = health.get("status") == "ready"
    if live_ready:
        verification_metadata = {
            "last_verified_at": checked_at.isoformat(),
            "last_verified_health": {
                "device_name": health.get("device_name"),
                "cuda_available": health.get("cuda_available"),
                "gpu_verified": health.get("gpu_verified"),
                "mineru_version": health.get("mineru_version"),
            },
        }
    else:
        verification_metadata = {
            key: previous_metadata[key]
            for key in ("last_verified_at", "last_verified_health")
            if key in previous_metadata
        }
    values = {
        "endpoint": resolved.mineru_api_url,
        "backend": resolved.mineru_backend,
        "capabilities": ["layout", "ocr", "table", "formula", "content-list"],
        "model_name": "MinerU",
        "model_version": health.get("mineru_version"),
        "priority": 100,
        "max_concurrency": resolved.mineru_max_concurrency,
        "health_status": (
            "ready_stale"
            if not live_ready and previous_metadata.get("last_verified_at")
            else str(health.get("status") or "unknown")
        ),
        "allowed_access_classes": sorted(resolved.mineru_allowed_access_class_set()),
        "tls_required": resolved.mineru_execution_mode == "remote",
        "last_health_check_at": checked_at,
        "metadata_json": {
            **previous_metadata,
            **verification_metadata,
            "execution_mode": resolved.mineru_execution_mode,
            "device": resolved.mineru_device,
            "device_name": health.get("device_name"),
            "cuda_available": health.get("cuda_available"),
            "gpu_verified": health.get("gpu_verified"),
            "virtual_vram_gb": health.get("virtual_vram_gb"),
            "torch_version": health.get("torch_version"),
            "torch_cuda_version": health.get("torch_cuda_version"),
            "checked_status": health.get("status"),
            "error": health.get("error"),
            "last_probe_at": checked_at.isoformat(),
            "last_probe_status": health.get("status"),
        },
    }
    if row is None:
        row = MineruBackendRecord(id=resolved.mineru_node_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return row
