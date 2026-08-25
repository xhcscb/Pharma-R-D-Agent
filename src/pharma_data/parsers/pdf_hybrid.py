import importlib.util
import tempfile
from pathlib import Path
from typing import Any

from pharma_data.config import Settings, get_settings
from pharma_data.contracts import (
    BoundingBox,
    CharacterSpan,
    DocumentType,
    ElementType,
    ParsedDocument,
)
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element
from pharma_data.parsers.image import ImageParser
from pharma_data.parsers.mineru import (
    MineruClient,
    MineruPdfParser,
    _html_table_cells,
    apply_pdf_quality_gates,
)
from pharma_data.parsers.pdf import PdfParser
from pharma_data.parsers.visual_semantics import enrich_visual_semantics


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
        return self.parse_pages(
            path,
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            artifact_id=artifact_id,
            page_numbers=None,
        )

    def parse_pages(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
        page_numbers: set[int] | None,
    ) -> ParsedDocument:
        try:
            import fitz
            from paddleocr import PPStructureV3
        except ImportError as exc:
            raise RuntimeError("PP-StructureV3 requires the documents dependency") from exc
        pipeline = PPStructureV3(
            device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            use_seal_recognition=False,
            use_formula_recognition=False,
            use_chart_recognition=False,
            use_region_detection=False,
            use_table_recognition=True,
            lang="ch",
        )
        elements = []
        order = 0
        with fitz.open(path) as pdf, tempfile.TemporaryDirectory(prefix="pharma-ppstruct-") as temp:
            for page_number, page in enumerate(pdf, start=1):
                if page_numbers is not None and page_number not in page_numbers:
                    continue
                image_path = Path(temp) / f"page-{page_number}.png"
                page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(image_path)
                for result in pipeline.predict(input=str(image_path)):
                    payload = _result_payload(result)
                    for block in _structure_blocks(payload):
                        label = str(
                            block.get("block_label")
                            or block.get("label")
                            or block.get("type")
                            or "text"
                        ).lower()
                        text = _block_text(block)
                        if not text:
                            continue
                        element_type = {
                            "table": ElementType.TABLE,
                            "chart": ElementType.CHART,
                            "figure": ElementType.FIGURE,
                            "formula": ElementType.FORMULA,
                            "title": ElementType.TITLE,
                            "doc_title": ElementType.TITLE,
                            "number": ElementType.FOOTER,
                            "footnote": ElementType.FOOTNOTE,
                            "header": ElementType.HEADER,
                        }.get(label, ElementType.PARAGRAPH)
                        bbox = _block_bbox(block)
                        table_cells = (
                            _html_table_cells(text, bbox)
                            if element_type == ElementType.TABLE and "<table" in text.lower()
                            else []
                        )
                        element = make_element(
                                document_version_id=document_version_id,
                                element_type=element_type,
                                reading_order=order,
                                text=text,
                                parser_name=self.name,
                                parser_version=self.version,
                                page_number=page_number,
                                bbox=bbox,
                                structured_payload={"pp_structure": block},
                                confidence=float(block.get("score", 0.75)),
                            ).model_copy(
                                update={
                                    "character_spans": [
                                        CharacterSpan(
                                            char_start=0,
                                            char_end=len(text),
                                            text=text,
                                            bbox=bbox,
                                            confidence=float(block.get("score", 0.75)),
                                        )
                                    ],
                                    "table_cells": table_cells,
                                }
                            )
                        elements.append(
                            element
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
    version = "0.3.0"
    media_types = {"application/pdf"}

    def __init__(
        self,
        selector: PdfQualitySelector | None = None,
        settings: Settings | None = None,
    ):
        self.selector = selector or PdfQualitySelector()
        self.settings = settings or get_settings()

    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        kwargs: dict[str, Any] = {
            "document_id": document_id,
            "document_version_id": document_version_id,
            "document_type": document_type,
            "artifact_id": artifact_id,
        }
        native = PdfParser().parse(path, **kwargs)
        native = native.model_copy(
            update={"metadata": {**native.metadata, "parser_candidate": PdfParser.name}}
        )
        warnings = list(native.warnings)
        if not self.settings.mineru_enabled:
            warnings.append("MinerU is disabled; PyMuPDF verifier output is review-only")
            return self._degraded_native(native, warnings, "mineru_disabled")

        try:
            selected = MineruPdfParser(MineruClient(self.settings)).parse(path, **kwargs)
        except Exception as exc:
            if (
                self.settings.mineru_cpu_fallback
                and self.settings.mineru_cpu_api_url
                and "out of memory" in str(exc).casefold()
            ):
                cpu_settings = self.settings.model_copy(
                    update={
                        "mineru_api_url": self.settings.mineru_cpu_api_url,
                        "mineru_device": "cpu",
                        "mineru_node_id": f"{self.settings.mineru_node_id}-cpu-fallback",
                    }
                )
                try:
                    selected = MineruPdfParser(MineruClient(cpu_settings)).parse(
                        path, **kwargs
                    )
                    selected = selected.model_copy(
                        update={
                            "metadata": {
                                **selected.metadata,
                                "degraded_from_gpu": True,
                                "degradation_reason": f"{type(exc).__name__}: {exc}",
                            }
                        }
                    )
                except Exception as cpu_exc:
                    if self.settings.mineru_required:
                        raise RuntimeError(
                            f"MinerU GPU and CPU fallback both failed: {cpu_exc}"
                        ) from cpu_exc
                    warnings.extend(
                        [
                            f"MinerU GPU failed: {type(exc).__name__}: {exc}",
                            f"MinerU CPU fallback failed: {type(cpu_exc).__name__}: {cpu_exc}",
                        ]
                    )
                    return self._degraded_native(native, warnings, "mineru_all_backends_failed")
            else:
                if self.settings.mineru_required:
                    raise
                warnings.append(f"MinerU failed: {type(exc).__name__}: {exc}")
                return self._degraded_native(native, warnings, "mineru_unavailable")

        selected = apply_pdf_quality_gates(selected, native, path)
        failed_pages = set(selected.metadata.get("failed_pages", []))
        if (
            failed_pages
            and self.settings.pp_structure_fallback
            and importlib.util.find_spec("paddleocr") is not None
        ):
            try:
                rescue = PaddleStructurePdfParser().parse_pages(
                    path, page_numbers=failed_pages, **kwargs
                )
                keep = [
                    element
                    for element in selected.elements
                    if element.page_number not in failed_pages
                ]
                pp_candidate = {
                    "backend_name": "pp-structure-v3",
                    "selected": False,
                    "status": "page_rescue_candidate",
                    "pages": sorted(failed_pages),
                    "element_count": len(rescue.elements),
                }
                combined = selected.model_copy(
                    update={
                        "elements": [*keep, *rescue.elements],
                        "metadata": {
                            **selected.metadata,
                            "parse_candidates": [
                                *selected.metadata.get("parse_candidates", []),
                                pp_candidate,
                            ],
                        },
                    }
                )
                rescued = apply_pdf_quality_gates(combined, native, path)
                previous_score = _quality_score(selected)
                rescue_score = _quality_score(rescued)
                if rescue.elements and rescue_score > previous_score:
                    pp_candidate.update({"selected": True, "status": "page_rescue_selected"})
                    selected = rescued.model_copy(
                        update={
                            "metadata": {
                                **rescued.metadata,
                                "pp_structure_rescue_pages": sorted(failed_pages),
                            }
                        }
                    )
                else:
                    selected = selected.model_copy(
                        update={
                            "metadata": {
                                **selected.metadata,
                                "parse_candidates": [
                                    *selected.metadata.get("parse_candidates", []),
                                    pp_candidate,
                                ],
                            },
                            "warnings": [
                                *selected.warnings,
                                "PP-StructureV3 candidate did not improve hard quality gates",
                            ],
                        }
                    )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                warnings.append(f"PP-StructureV3 page rescue failed: {error}")
                selected = selected.model_copy(
                    update={
                        "metadata": {
                            **selected.metadata,
                            "parse_candidates": [
                                *selected.metadata.get("parse_candidates", []),
                                {
                                    "backend_name": "pp-structure-v3",
                                    "selected": False,
                                    "status": "page_rescue_failed",
                                    "pages": sorted(failed_pages),
                                    "diagnostics": {"error": error},
                                },
                            ],
                        }
                    }
                )
        elif failed_pages and self.settings.pp_structure_fallback:
            warnings.append(
                "PP-StructureV3 is unavailable; failed pages remain in the review queue"
            )

        selected = enrich_visual_semantics(selected, path, self.settings)
        return selected.model_copy(
            update={
                "metadata": {
                    **selected.metadata,
                    "selected_parser": selected.metadata.get("selected_parser")
                    or selected.metadata.get("parser_candidate")
                    or MineruPdfParser.name,
                    "hybrid_candidate_count": len(
                        selected.metadata.get("parse_candidates", [])
                    ),
                },
                "warnings": sorted(set([*selected.warnings, *warnings])),
            }
        )

    @staticmethod
    def _degraded_native(
        native: ParsedDocument, warnings: list[str], reason: str
    ) -> ParsedDocument:
        page_count = int(native.metadata.get("page_count") or 0)
        return native.model_copy(
            update={
                "metadata": {
                    **native.metadata,
                    "selected_parser": PdfParser.name,
                    "degraded_mode": True,
                    "degradation_reason": reason,
                    "formal_reasoning_eligible": False,
                    "failed_pages": list(range(1, page_count + 1)),
                    "parse_candidates": [
                        {
                            "backend_name": PdfParser.name,
                            "backend_version": PdfParser.version,
                            "selected": True,
                            "status": "review_only_fallback",
                            "diagnostics": {"reason": reason},
                        }
                    ],
                },
                "parse_quality": {
                    **native.parse_quality,
                    "hard_gate_pass_rate": 0.0,
                    "failed_page_count": float(page_count),
                },
                "warnings": sorted(set(warnings)),
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
    if not isinstance(value, dict):
        return {}
    response = value.get("res")
    if isinstance(response, dict):
        return {str(key): item for key, item in response.items()}
    return {str(key): item for key, item in value.items()}


def _structure_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("parsing_res_list", "layout_res", "blocks"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _block_bbox(block: dict[str, Any]) -> BoundingBox | None:
    value = block.get("block_bbox") or block.get("bbox") or block.get("coordinate")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    return BoundingBox(
        x0=float(value[0]), y0=float(value[1]), x1=float(value[2]), y1=float(value[3])
    )


def _block_text(block: dict[str, Any]) -> str:
    value = (
        block.get("block_content")
        or block.get("text")
        or block.get("content")
        or block.get("markdown")
        or ""
    )
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(
            _block_text(item) if isinstance(item, dict) else str(item)
            for item in value
            if item
        ).strip()
    if isinstance(value, dict):
        return _block_text(value)
    return str(value).strip()


def _quality_score(document: ParsedDocument) -> tuple[float, float, float, int]:
    quality = document.parse_quality
    return (
        float(quality.get("hard_gate_pass_rate", 0.0)),
        float(quality.get("numeric_token_recall", 0.0)),
        float(quality.get("page_coverage", 0.0)),
        len(document.elements),
    )
