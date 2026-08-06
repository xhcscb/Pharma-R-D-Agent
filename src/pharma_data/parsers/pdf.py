from pathlib import Path

from pharma_data.contracts import (
    BoundingBox,
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
                blocks = sorted(
                    page.get_text("blocks"),
                    key=lambda item: (round(float(item[1]) / 5), float(item[0])),
                )
                for x0, y0, x1, y1, text, *_ in blocks:
                    cleaned = str(text).strip()
                    if not cleaned:
                        continue
                    total_chars += len(cleaned)
                    if y1 > page_height * 0.90:
                        element_type = ElementType.FOOTNOTE
                    elif len(cleaned) < 100 and cleaned.count("\n") <= 1:
                        element_type = ElementType.TITLE
                    else:
                        element_type = ElementType.PARAGRAPH
                    elements.append(
                        make_element(
                            document_version_id=document_version_id,
                            element_type=element_type,
                            reading_order=reading_order,
                            text=cleaned,
                            parser_name=self.name,
                            parser_version=self.version,
                            page_number=page_number,
                            bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                        )
                    )
                    reading_order += 1

                try:
                    tables = page.find_tables()
                except Exception as exc:
                    warnings.append(f"page {page_number}: table detection failed: {exc}")
                    tables = None
                if tables:
                    for table_index, table in enumerate(tables.tables):
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
