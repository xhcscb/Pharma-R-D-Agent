from pathlib import Path

from bs4 import BeautifulSoup

from pharma_data.contracts import DocumentType, ElementType, ParsedDocument
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element
from pharma_data.utils.text import normalize_text


class HtmlParser(Parser):
    name = "beautifulsoup-readable"
    version = "0.1.0"
    media_types = {"text/html", "application/xhtml+xml"}

    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside", "form", "noscript"]):
            tag.decompose()
        elements = []
        seen: set[str] = set()
        order = 0
        for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            text = normalize_text(node.get_text(" ", strip=True))
            if not text or text in seen:
                continue
            seen.add(text)
            if node.name.startswith("h"):
                kind = ElementType.TITLE
            elif node.name == "li":
                kind = ElementType.LIST
            elif node.name == "table":
                kind = ElementType.TABLE
            else:
                kind = ElementType.PARAGRAPH
            payload = {}
            if node.name == "table":
                payload["rows"] = [
                    [
                        normalize_text(cell.get_text(" ", strip=True))
                        for cell in row.find_all(["th", "td"])
                    ]
                    for row in node.find_all("tr")
                ]
            elements.append(
                make_element(
                    document_version_id=document_version_id,
                    element_type=kind,
                    reading_order=order,
                    text=text,
                    parser_name=self.name,
                    parser_version=self.version,
                    structured_payload=payload,
                )
            )
            order += 1
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={
                "artifact_id": artifact_id,
                "title": soup.title.string if soup.title else None,
            },
            elements=elements,
            parse_quality={"element_count": float(len(elements))},
        )
