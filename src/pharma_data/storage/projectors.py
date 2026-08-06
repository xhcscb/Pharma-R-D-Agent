from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.config import Settings, get_settings
from pharma_data.storage.canonical.models import OutboxEventRecord


class Projector(Protocol):
    name: str

    def project(self, session: Session, event: OutboxEventRecord) -> None: ...

    def rebuild(self, session: Session) -> dict[str, int]: ...


class ProjectionDispatcher:
    def __init__(
        self,
        projectors: dict[str, Projector] | None = None,
        settings: Settings | None = None,
    ):
        settings = settings or get_settings()
        if projectors is None:
            from pharma_data.storage.elasticsearch.projector import ElasticsearchProjector
            from pharma_data.storage.milvus.projector import MilvusProjector
            from pharma_data.storage.neo4j.projector import Neo4jProjector
            from pharma_data.storage.timescale.projector import TimescaleProjector

            projectors = {
                "neo4j": Neo4jProjector(settings),
                "milvus": MilvusProjector(settings),
                "timescale": TimescaleProjector(settings),
                "elasticsearch": ElasticsearchProjector(settings),
            }
        self.projectors = projectors

    def dispatch_pending(
        self, session: Session, projection: str | None = None, limit: int = 100
    ) -> dict[str, int]:
        statement = (
            select(OutboxEventRecord)
            .where(OutboxEventRecord.published_at.is_(None))
            .order_by(OutboxEventRecord.created_at)
            .limit(limit)
        )
        if projection:
            statement = statement.where(OutboxEventRecord.projection == projection)
        projected = 0
        failed = 0
        for event in session.scalars(statement):
            projector = self.projectors.get(event.projection)
            if projector is None:
                event.attempts += 1
                event.last_error = f"No projector configured for {event.projection}"
                failed += 1
                continue
            try:
                projector.project(session, event)
                event.published_at = datetime.now(UTC)
                event.last_error = None
                projected += 1
            except Exception as exc:
                event.attempts += 1
                event.last_error = f"{type(exc).__name__}: {exc}"
                failed += 1
        session.flush()
        return {"projected": projected, "failed": failed}
