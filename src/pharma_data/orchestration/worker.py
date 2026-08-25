import logging
import socket
import time

from pharma_data.config import get_settings
from pharma_data.inbox import build_inbox_coordinator
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical import create_schema, session_scope
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("pharma_data.worker")
    create_schema()
    worker_id = f"{socket.gethostname()}:{id(settings)}"
    inbox = build_inbox_coordinator(settings)
    object_store = LocalObjectStore(settings.object_store_root)
    next_inbox_scan = 0.0
    logger.info("worker_started worker_id=%s", worker_id)
    while True:
        if settings.inbox_enabled and time.monotonic() >= next_inbox_scan:
            try:
                with session_scope() as session:
                    inbox_report = inbox.run_once(session, object_store)
                if inbox_report["files_seen"]:
                    logger.info(
                        "inbox_batch_complete batch_id=%s counts=%s",
                        inbox_report["batch_id"],
                        inbox_report["counts"],
                    )
            except Exception:  # noqa: BLE001 - worker must keep polling after an inbox failure
                logger.exception("inbox_batch_failed")
            next_inbox_scan = time.monotonic() + settings.inbox_poll_seconds
        with session_scope() as session:
            repository = CanonicalRepository(session)
            job = repository.claim_job(worker_id, settings.worker_lock_seconds)
            if job:
                job_id = job.id
            else:
                job_id = None
        if job_id:
            with session_scope() as session:
                try:
                    result = PipelineRunner(session).run(job_id)
                    inbox.refresh_job_receipt(session, job_id, result)
                    logger.info("pipeline_complete result=%s", result)
                except Exception:  # noqa: BLE001 - PipelineRunner has persisted failure state
                    inbox.refresh_job_receipt(session, job_id)
                    logger.exception("pipeline_failed job_id=%s", job_id)
        else:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
