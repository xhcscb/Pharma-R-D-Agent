import logging
import socket
import time

from pharma_data.config import get_settings
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical import create_schema, session_scope
from pharma_data.storage.canonical.repository import CanonicalRepository


def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("pharma_data.worker")
    create_schema()
    worker_id = f"{socket.gethostname()}:{id(settings)}"
    logger.info("worker_started worker_id=%s", worker_id)
    while True:
        with session_scope() as session:
            repository = CanonicalRepository(session)
            job = repository.claim_job(worker_id, settings.worker_lock_seconds)
            if job:
                job_id = job.id
            else:
                job_id = None
        if job_id:
            try:
                with session_scope() as session:
                    result = PipelineRunner(session).run(job_id)
                    logger.info("pipeline_complete result=%s", result)
            except Exception:
                logger.exception("pipeline_failed job_id=%s", job_id)
        else:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
