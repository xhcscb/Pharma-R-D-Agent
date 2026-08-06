import importlib.util
import tempfile
from pathlib import Path
from typing import Any

from pharma_data.contracts import (
    BoundingBox,
    DocumentType,
    ElementType,
    ParsedDocument,
)
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element
from pharma_data.parsers.image import ImageParser
from pharma_data.parsers.pdf import PdfParser


class PdfQualitySelector:
    """Select the strongest parse while preserving candidate scores."""

    @staticmethod
    def score(document: ParsedDocument) -> float:
        text_chars = sum(len(item.text) for item in document.elements)
        tables = sum(item.element_type == ElementType.TABLE for item in document.elements)
        located = sum(item.bbox is not None for item in document.elements)
        confidence = (
            sum(item.confidence for item in document.elements) / len(document.elements)
            if document.elements
            else 0.0
        )
        location_rate = located / len(document.elements) if document.elements else 0.0
        return round(
            min(text_chars / 5000.0, 0.55)
            + min(tables * 0.05, 0.15)
            + location_rate * 0.15
            + confidence * 0.15,
            6,
        )

    def select(self, candidates: list[ParsedDocument]) -> ParsedDocument:
        if not candidates:
            raise ValueError("At least one PDF parse candidate is required")
        scored = [(self.score(item), item) for item in candidates]
        score, selected = max(scored, key=lambda pair: pair[0])
        candidate_scores = {
            str(item.metadata.get("parser_candidate", index)): item_score
            for index, (item_score, item) in enumerate(scored)
        }
        return selected.model_copy(
            update={
                "metadata": {
                    **selected.metadata,
                    "selected_parser": selected.metadata.get("parser_candidate"),
                    "candidate_scores": candidate_scores,
                },
                "parse_quality": {
                    **selected.parse_quality,
                    "selector_score": score,
                },
            }
        )


class PaddleOcrPdfParser(Parser):
    name = "paddleocr-pdf"
    version = "0.1.0"
    media_types = {"application/pdf"}

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
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF OCR requires pymupdf") from exc
        image_parser = ImageParser()
        elements = []
        order = 0
        with fitz.open(path) as pdf, tempfile.TemporaryDirectory(prefix="pharma-pdf-ocr-") as temp:
            for page_number, page in enumerate(pdf, start=1):
                image_path = Path(temp) / f"page-{page_number}.png"
                page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(image_path)
                parsed = image_parser.parse(
                    image_path,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    document_type=document_type,
                    artifact_id=artifact_id,
                )
                for element in parsed.elements:
                    elements.append(
                        element.model_copy(
                            update={"page_number": page_number, "reading_order": order}
                        )
                    )
                    order += 1
            page_count = len(pdf)
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={
                "artifact_id": artifact_id,
                "page_count": page_count,
                "parser_candidate": self.name,
            },
            elements=elements,
            parse_quality={"ocr_element_count": float(len(elements))},
        )


class DoclingPdfParser(Parser):
    name = "docling-pdf"
    version = "0.1.0"
    media_types = {"application/pdf"}

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
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RuntimeError("Docling requires the optional 'documents' dependency") from exc
        result = DocumentConverter().convert(path)
        markdown = result.document.export_to_markdown()
        elements = []
        order = 0
        for block in (item.strip() for item in markdown.split("\n\n")):
            if not block:
                continue
            element_type = (
                ElementType.TABLE
                if block.startswith("|") and "\n|" in block
                else ElementType.TITLE
                if block.startswith("#")
                else ElementType.PARAGRAPH
            )
            elements.append(
                make_element(
                    document_version_id=document_version_id,
                    element_type=element_type,
                    reading_order=order,
                    text=block.lstrip("# ").strip(),
                    parser_name=self.name,
                    parser_version=self.version,
                    structured_payload={"markdown": block}
                    if element_type == ElementType.TABLE
                    else {},
                    confidence=0.85,
                )
            )
            order += 1
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={"artifact_id": artifact_id, "parser_candidate": self.name},
            elements=elements,
            parse_quality={"docling_element_count": float(len(elements))},
        )


class PaddleStructurePdfParser(Parser):
    name = "pp-structure-v3"
    version = "0.1.0"
    media_types = {"application/pdf"}

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
            import fitz
            from paddleocr import PPStructureV3
        except ImportError as exc:
            raise RuntimeError("PP-StructureV3 requires the documents dependency") from exc
        pipeline = PPStructureV3()
        elements = []
        order = 0
        with fitz.open(path) as pdf, tempfile.TemporaryDirectory(prefix="pharma-ppstruct-") as temp:
            for page_number, page in enumerate(pdf, start=1):
                image_path = Path(temp) / f"page-{page_number}.png"
                page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(image_path)
                for result in pipeline.predict(input=str(image_path)):
                    payload = _result_payload(result)
                    for block in _structure_blocks(payload):
                        label = str(block.get("label") or block.get("type") or "text").lower()
                        text = str(
                            block.get("text") or block.get("content") or block.get("markdown") or ""
                        ).strip()
                        if not text:
                            continue
                        element_type = {
                            "table": ElementType.TABLE,
                            "chart": ElementType.CHART,
                            "figure": ElementType.FIGURE,
                            "formula": ElementType.FORMULA,
                            "title": ElementType.TITLE,
                            "footnote": ElementType.FOOTNOTE,
                        }.get(label, ElementType.PARAGRAPH)
                        elements.append(
                            make_element(
                                document_version_id=document_version_id,
                                element_type=element_type,
                                reading_order=order,
                                text=text,
                                parser_name=self.name,
                                parser_version=self.version,
                                page_number=page_number,
                                bbox=_block_bbox(block),
                                structured_payload={"pp_structure": block},
                                confidence=float(block.get("score", 0.75)),
                            )
                        )
                        order += 1
            page_count = len(pdf)
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={
                "artifact_id": artifact_id,
                "page_count": page_count,
                "parser_candidate": self.name,
            },
            elements=elements,
            parse_quality={"structure_element_count": float(len(elements))},
        )


class HybridPdfParser(Parser):
    name = "hybrid-pdf"
    version = "0.1.0"
    media_types = {"application/pdf"}

    def __init__(self, selector: PdfQualitySelector | None = None):
        self.selector = selector or PdfQualitySelector()

    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        kwargs = {
            "document_id": document_id,
            "document_version_id": document_version_id,
            "document_type": document_type,
            "artifact_id": artifact_id,
        }
        native = PdfParser().parse(path, **kwargs)
        native = native.model_copy(
            update={"metadata": {**native.metadata, "parser_candidate": PdfParser.name}}
        )
        candidates = [native]
        warnings = list(native.warnings)

        if importlib.util.find_spec("docling") is not None:
            self._try_candidate(DoclingPdfParser(), path, kwargs, candidates, warnings)
        requires_ocr = bool(native.parse_quality.get("requires_ocr"))
        if requires_ocr and importlib.util.find_spec("paddleocr") is not None:
            self._try_candidate(PaddleOcrPdfParser(), path, kwargs, candidates, warnings)
            self._try_candidate(PaddleStructurePdfParser(), path, kwargs, candidates, warnings)
        elif requires_ocr:
            warnings.append(
                "OCR candidates unavailable; install the documents dependency and reprocess"
            )

        selected = self.selector.select(candidates)
        return selected.model_copy(
            update={
                "metadata": {
                    **selected.metadata,
                    "hybrid_candidate_count": len(candidates),
                },
                "warnings": sorted(set([*selected.warnings, *warnings])),
            }
        )

    @staticmethod
    def _try_candidate(
        parser: Parser,
        path: Path,
        kwargs: dict[str, Any],
        candidates: list[ParsedDocument],
        warnings: list[str],
    ) -> None:
        try:
            candidates.append(parser.parse(path, **kwargs))
        except Exception as exc:
            warnings.append(f"{parser.name} failed: {type(exc).__name__}: {exc}")


def _result_payload(result: Any) -> dict[str, Any]:
    value = getattr(result, "json", result)
    if callable(value):
        value = value()
    if isinstance(value, dict) and isinstance(value.get("res"), dict):
        return value["res"]
    return value if isinstance(value, dict) else {}


def _structure_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("parsing_res_list", "layout_res", "blocks"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _block_bbox(block: dict[str, Any]) -> BoundingBox | None:
    value = block.get("bbox") or block.get("coordinate")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    return BoundingBox(
        x0=float(value[0]), y0=float(value[1]), x1=float(value[2]), y1=float(value[3])
    )
