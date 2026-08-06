from pathlib import Path

from pharma_data.contracts import DocumentType, ElementType, ParsedDocument
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element


class PlainTextParser(Parser):
    name = "plain-text"
    version = "0.1.0"
    media_types = {"text/plain", "text/markdown"}

    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        paragraphs = [
            value.strip()
            for value in path.read_text(encoding="utf-8", errors="replace").split("\n\n")
            if value.strip()
        ]
        elements = [
            make_element(
                document_version_id=document_version_id,
                element_type=ElementType.PARAGRAPH,
                reading_order=index,
                text=text,
                parser_name=self.name,
                parser_version=self.version,
            )
            for index, text in enumerate(paragraphs)
        ]
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={"artifact_id": artifact_id},
            elements=elements,
            parse_quality={"paragraph_count": float(len(elements))},
        )
