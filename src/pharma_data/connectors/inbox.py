from pathlib import Path

from pharma_data.connectors.base import FetchResult, SourceAdapter
from pharma_data.contracts import SourceRecordEnvelope, SourceRecordPage


class InboxAdapter(SourceAdapter):
    """把一个已经完成治理标注的本地投递文件接入标准入库契约。"""

    adapter_name = "InboxAdapter"

    def __init__(
        self,
        *,
        path: Path,
        envelope: SourceRecordEnvelope,
        source_name: str,
        authority_tier: str,
        base_url: str | None = None,
        terms_url: str | None = None,
    ) -> None:
        self.path = path
        self.envelope = envelope
        self.source_name = source_name
        self.authority_tier = authority_tier
        self.base_url = base_url
        self.terms_url = terms_url
        self.default_license_status = envelope.license_status

    def discover(
        self, query: dict[str, object], cursor: str | None = None
    ) -> SourceRecordPage:
        if cursor:
            return SourceRecordPage(records=[], next_cursor=None)
        return SourceRecordPage(records=[self.envelope], next_cursor=None)

    def fetch(self, record: SourceRecordEnvelope) -> list[FetchResult]:
        if record.source_record_id != self.envelope.source_record_id:
            raise ValueError("Inbox adapter received an unexpected source record")
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        media_type = str(record.raw_metadata["media_type"])
        return [
            FetchResult(
                content=self.path.read_bytes(),
                media_type=media_type,
                original_url=str(record.canonical_url) if record.canonical_url else None,
                metadata={
                    "filename": self.path.name,
                    "ingestion_channel": "filesystem_inbox",
                    "content_hash": record.raw_metadata["content_hash"],
                },
            )
        ]


__all__ = ["InboxAdapter"]
