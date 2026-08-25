import re
from pathlib import Path
from statistics import median
from typing import Any

from pharma_data.contracts import (
    BoundingBox,
    CharacterSpan,
    DocumentType,
    ElementType,
    ParsedDocument,
)
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element


class PdfParser(Parser):
    name = "pymupdf-layout"
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
            raise RuntimeError("PDF parsing requires the pymupdf package") from exc

        elements = []
        warnings: list[str] = []
        total_chars = 0
        reading_order = 0
        with fitz.open(path) as pdf:
            for page_number, page in enumerate(pdf, start=1):
                page_height = max(float(page.rect.height), 1.0)
                try:
                    detected_tables = page.find_tables()
                except Exception as exc:
                    warnings.append(f"page {page_number}: table detection failed: {exc}")
                    detected_tables = None
                tables = list(detected_tables.tables) if detected_tables else []
                table_boxes = [
                    (
                        float(table.bbox[0]),
                        float(table.bbox[1]),
                        float(table.bbox[2]),
                        float(table.bbox[3]),
                    )
                    for table in tables
                ]
                heading_boxes = _heading_boxes(page)
                blocks = sorted(
                    page.get_text("blocks"),
                    key=lambda item: (round(float(item[1]) / 5), float(item[0])),
                )
                for x0, y0, x1, y1, text, *_ in blocks:
                    cleaned = str(text).strip()
                    if not cleaned:
                        continue
                    block_box = (float(x0), float(y0), float(x1), float(y1))
                    if any(_overlap_over_smaller(block_box, box) > 0.65 for box in table_boxes):
                        continue
                    total_chars += len(cleaned)
                    if y1 > page_height * 0.90:
                        element_type = ElementType.FOOTNOTE
                    elif any(
                        _overlap_over_smaller(block_box, box) > 0.7 for box in heading_boxes
                    ) or _looks_like_heading(cleaned):
                        element_type = ElementType.TITLE
                    else:
                        element_type = ElementType.PARAGRAPH
                    element = make_element(
                            document_version_id=document_version_id,
                            element_type=element_type,
                            reading_order=reading_order,
                            text=cleaned,
                            parser_name=self.name,
                            parser_version=self.version,
                            page_number=page_number,
                            bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                        )
                    elements.append(
                        element.model_copy(
                            update={
                                "character_spans": [
                                    CharacterSpan(
                                        char_start=0,
                                        char_end=len(cleaned),
                                        text=cleaned,
                                        bbox=element.bbox,
                                        confidence=1.0,
                                    )
                                ]
                            }
                        )
                    )
                    reading_order += 1

                if tables:
                    for table_index, table in enumerate(tables):
                        rows = table.extract()
                        table_text = "\n".join(
                            "\t".join("" if cell is None else str(cell) for cell in row)
                            for row in rows
                        )
                        bbox = table.bbox
                        elements.append(
                            make_element(
                                document_version_id=document_version_id,
                                element_type=ElementType.TABLE,
                                reading_order=reading_order,
                                text=table_text,
                                parser_name=self.name,
                                parser_version=self.version,
                                page_number=page_number,
                                bbox=BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
                                structured_payload={
                                    "table_index": table_index,
                                    "rows": rows,
                                    "row_count": len(rows),
                                    "column_count": max((len(row) for row in rows), default=0),
                                    "merged_cells": [],
                                    "header_levels": None,
                                    "unit": None,
                                    "footnotes": [],
                                },
                                confidence=0.85,
                            )
                        )
                        reading_order += 1

                for image_index, image_info in enumerate(page.get_images(full=True)):
                    xref = image_info[0]
                    rects = page.get_image_rects(xref)
                    for rect in rects:
                        elements.append(
                            make_element(
                                document_version_id=document_version_id,
                                element_type=ElementType.FIGURE,
                                reading_order=reading_order,
                                text="",
                                parser_name=self.name,
                                parser_version=self.version,
                                page_number=page_number,
                                bbox=BoundingBox(x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1),
                                structured_payload={
                                    "image_index": image_index,
                                    "xref": xref,
                                    "chart_type": None,
                                    "title": None,
                                    "x_axis": None,
                                    "y_axis": None,
                                    "legend": None,
                                    "series": [],
                                    "values": None,
                                    "units": None,
                                    "footnotes": [],
                                    "needs_chart_analysis": True,
                                },
                                confidence=0.5,
                            )
                        )
                        reading_order += 1

            page_count = len(pdf)

        elements.sort(
            key=lambda item: (
                item.page_number or 0,
                round(item.bbox.y0 / 5) if item.bbox else 10**9,
                item.bbox.x0 if item.bbox else 10**9,
                item.reading_order,
            )
        )
        elements = [
            element.model_copy(update={"reading_order": order})
            for order, element in enumerate(elements)
        ]

        chars_per_page = total_chars / max(page_count, 1)
        if chars_per_page < 50:
            warnings.append("Low native-text coverage; OCR is required for reliable extraction")
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={"artifact_id": artifact_id, "page_count": page_count},
            elements=elements,
            parse_quality={
                "native_characters": float(total_chars),
                "characters_per_page": chars_per_page,
                "requires_ocr": float(chars_per_page < 50),
            },
            warnings=warnings,
        )


def _heading_boxes(page: Any) -> list[tuple[float, float, float, float]]:
    try:
        payload = page.get_text("dict")
    except Exception:
        return []
    spans = [
        span
        for block in payload.get("blocks", [])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if str(span.get("text") or "").strip() and float(span.get("size") or 0) > 0
    ]
    if not spans:
        return []
    baseline = median(float(span["size"]) for span in spans)
    return [
        (
            float(span["bbox"][0]),
            float(span["bbox"][1]),
            float(span["bbox"][2]),
            float(span["bbox"][3]),
        )
        for span in spans
        if float(span["size"]) >= baseline * 1.18
        or int(span.get("flags") or 0) & 16
    ]


def _looks_like_heading(text: str) -> bool:
    cleaned = " ".join(text.split())
    if len(cleaned) > 80 or "\t" in text:
        return False
    return bool(
        re.match(
            r"^(?:第[一二三四五六七八九十百\d]+[章节]|[一二三四五六七八九十]+、|\d+(?:\.\d+){0,3}\s+\S+)",
            cleaned,
        )
    )


def _overlap_over_smaller(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> float:
    intersection = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 0.0)
    area_b = max((b[2] - b[0]) * (b[3] - b[1]), 0.0)
    return intersection / max(min(area_a, area_b), 1.0)
