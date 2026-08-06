import pytest
from pydantic import ValidationError

from pharma_data.contracts import AudioUtterance, BoundingBox, ReviewStatus


def test_bounding_box_rejects_reversed_coordinates() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x0=10, y0=0, x1=5, y1=20)


def test_audio_utterance_requires_ordered_timestamps() -> None:
    with pytest.raises(ValidationError):
        AudioUtterance(
            document_version_id="version",
            start_ms=1000,
            end_ms=999,
            raw_transcript="text",
            normalized_transcript="text",
            audio_artifact_id="artifact",
            review_status=ReviewStatus.CANDIDATE,
        )
