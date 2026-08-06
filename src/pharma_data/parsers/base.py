from abc import ABC, abstractmethod
from pathlib import Path

from pharma_data.contracts import DocumentType, ParsedDocument


class Parser(ABC):
    name: str
    version: str = "0.1.0"
    media_types: set[str]

    def supports(self, media_type: str, path: Path) -> bool:
        return media_type in self.media_types

    @abstractmethod
    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        raise NotImplementedError
