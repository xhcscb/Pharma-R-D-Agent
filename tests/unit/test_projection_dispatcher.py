from datetime import datetime

from pharma_data.storage.canonical.models import OutboxEventRecord
from pharma_data.storage.projectors import ProjectionDispatcher


class FakeProjector:
    name = "fake"

    def __init__(self):
        self.ids: list[str] = []

    def project(self, session, event) -> None:
        self.ids.append(event.id)

    def rebuild(self, session) -> dict[str, int]:
        return {"rebuilt": len(self.ids)}


def test_projection_dispatch_marks_event_published(db_session) -> None:
    event = OutboxEventRecord(
        aggregate_type="assertion",
        aggregate_id="aggregate",
        event_type="assertion.approved",
        projection="fake",
        payload={},
    )
    db_session.add(event)
    db_session.flush()
    fake = FakeProjector()

    result = ProjectionDispatcher(projectors={"fake": fake}).dispatch_pending(db_session)

    assert result == {"projected": 1, "failed": 0}
    assert event.published_at is not None
    assert isinstance(event.published_at, datetime)
