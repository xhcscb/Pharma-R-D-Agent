import shutil
import subprocess
import tempfile
from pathlib import Path

from pharma_data.contracts import (
    AudioUtterance,
    DocumentType,
    ParsedDocument,
    ReviewStatus,
)
from pharma_data.parsers.audio_diarization import assign_speakers
from pharma_data.parsers.base import Parser
from pharma_data.utils.hashing import stable_uuid
from pharma_data.utils.text import normalize_text


class AudioParser(Parser):
    name = "faster-whisper"
    version = "0.1.0"
    media_types = {
        "audio/mpeg",
        "audio/wav",
        "audio/x-wav",
        "audio/mp4",
        "video/mp4",
    }

    def __init__(self, model_name: str = "large-v3-turbo", device: str = "auto"):
        self.model_name = model_name
        self.device = device

    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Audio parsing requires the optional 'audio' dependency group"
            ) from exc

        compute_type = "int8" if self.device in {"auto", "cpu"} else "int8_float16"
        model = WhisperModel(self.model_name, device=self.device, compute_type=compute_type)
        with tempfile.TemporaryDirectory(prefix="pharma-audio-") as temp:
            normalized_path = Path(temp) / "normalized.wav"
            self._normalize_audio(path, normalized_path)
            segments, info = model.transcribe(
                str(normalized_path),
                vad_filter=True,
                word_timestamps=True,
                beam_size=5,
            )
            utterances = []
            for segment in segments:
                text = segment.text.strip()
                start_ms = round(segment.start * 1000)
                end_ms = round(segment.end * 1000)
                utterances.append(
                    AudioUtterance(
                        utterance_id=stable_uuid(
                            {
                                "document_version_id": document_version_id,
                                "start_ms": start_ms,
                                "end_ms": end_ms,
                                "text": text,
                            }
                        ),
                        document_version_id=document_version_id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        raw_transcript=text,
                        normalized_transcript=normalize_text(text),
                        asr_confidence=max(
                            0.0,
                            min(1.0, 1.0 - float(segment.no_speech_prob)),
                        ),
                        audio_artifact_id=artifact_id,
                        review_status=ReviewStatus.CANDIDATE,
                    )
                )
            utterances, diarized, diarization_warning = assign_speakers(normalized_path, utterances)

        warnings = []
        if diarization_warning:
            warnings.append(diarization_warning)
        warnings.append("Speaker names and roles require official participant-list review")
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            language=info.language or "und",
            metadata={
                "artifact_id": artifact_id,
                "duration_seconds": info.duration,
                "speaker_diarization": "applied" if diarized else "not_applied",
                "audio_standard": "pcm_s16le/mono/16000Hz",
            },
            utterances=utterances,
            parse_quality={"utterance_count": float(len(utterances))},
            warnings=warnings,
        )

    @staticmethod
    def _normalize_audio(source: Path, destination: Path) -> None:
        executable = shutil.which("ffmpeg")
        if executable is None:
            raise RuntimeError("FFmpeg is required to standardize audio input")
        completed = subprocess.run(
            [
                executable,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            capture_output=True,
            check=False,
            timeout=3600,
        )
        if completed.returncode != 0 or not destination.is_file():
            error = completed.stderr.decode("utf-8", errors="replace")[-1000:]
            raise RuntimeError(f"FFmpeg audio normalization failed: {error}")
