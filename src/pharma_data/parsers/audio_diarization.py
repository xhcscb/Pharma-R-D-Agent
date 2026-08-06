from pathlib import Path

from pharma_data.config import get_settings
from pharma_data.contracts import AudioUtterance


def assign_speakers(
    path: Path, utterances: list[AudioUtterance]
) -> tuple[list[AudioUtterance], bool, str | None]:
    settings = get_settings()
    if not settings.hf_token:
        return utterances, False, "HF_TOKEN is not configured; speaker diarization was skipped"
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        return utterances, False, "pyannote.audio is not installed; diarization was skipped"

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=settings.hf_token,
    )
    diarization = pipeline(str(path))
    turns = [
        (round(turn.start * 1000), round(turn.end * 1000), speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]
    assigned = []
    for utterance in utterances:
        best_speaker = None
        best_overlap = 0
        for start_ms, end_ms, speaker in turns:
            overlap = max(0, min(utterance.end_ms, end_ms) - max(utterance.start_ms, start_ms))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        assigned.append(
            utterance.model_copy(update={"speaker_id": best_speaker or "speaker_unknown"})
        )
    return assigned, True, None
