from pathlib import Path

from pharma_data.contracts import DocumentType, ParsedDocument
from pharma_data.parsers.audio import AudioParser
from pharma_data.parsers.base import Parser
from pharma_data.parsers.html import HtmlParser
from pharma_data.parsers.image import ImageParser
from pharma_data.parsers.pdf_hybrid import HybridPdfParser
from pharma_data.parsers.structured import JsonParser, SpreadsheetParser, XbrlParser
from pharma_data.parsers.text import PlainTextParser


class ParserRouter:
    def __init__(self, parsers: list[Parser] | None = None):
        self.parsers = parsers or [
            HybridPdfParser(),
            HtmlParser(),
            ImageParser(),
            JsonParser(),
            SpreadsheetParser(),
            XbrlParser(),
            PlainTextParser(),
            AudioParser(),
        ]

    def resolve(self, media_type: str, path: Path) -> Parser:
        for parser in self.parsers:
            if parser.supports(media_type, path):
                return parser
        raise ValueError(f"No parser registered for media type: {media_type}")


class DocumentParser:
    name = "DocParser"
    version = "0.2.0"

    def __init__(self, router: ParserRouter | None = None):
        self.router = router or ParserRouter()

    def parse(
        self,
        path: str | Path,
        *,
        media_type: str,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        resolved = Path(path)
        parser = self.router.resolve(media_type, resolved)
        return parser.parse(
            resolved,
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            artifact_id=artifact_id,
        )
