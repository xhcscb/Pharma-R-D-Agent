import json
from pathlib import Path
from typing import Any

from pharma_data.contracts import BoundingBox, DocumentType, ElementType, ParsedDocument
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element


class ImageParser(Parser):
    name = "paddleocr-image"
    version = "0.1.0"
    media_types = {"image/png", "image/jpeg", "image/tiff", "image/bmp"}

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
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "Image OCR requires the optional 'documents' dependency group"
            ) from exc

        engine = PaddleOCR(
            use_doc_orientation_classify=True,
            use_doc_unwarping=True,
            use_textline_orientation=True,
        )
        results = list(engine.predict(str(path)))
        elements = []
        order = 0
        for result in results:
            payload = self._payload(result)
            texts = payload.get("rec_texts", [])
            scores = payload.get("rec_scores", [])
            polygons = payload.get("rec_polys", payload.get("dt_polys", []))
            for index, text in enumerate(texts):
                polygon = polygons[index] if index < len(polygons) else None
                bbox = self._bbox(polygon)
                score = float(scores[index]) if index < len(scores) else 0.5
                elements.append(
                    make_element(
                        document_version_id=document_version_id,
                        element_type=ElementType.PARAGRAPH,
                        reading_order=order,
                        text=str(text),
                        parser_name=self.name,
                        parser_version=self.version,
                        page_number=1,
                        bbox=bbox,
                        confidence=max(0.0, min(1.0, score)),
                    )
                )
                order += 1
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={"artifact_id": artifact_id, "ocr_engine": self.name},
            elements=elements,
            parse_quality={"ocr_element_count": float(len(elements))},
        )

    @staticmethod
    def _payload(result: Any) -> dict[str, Any]:
        value = getattr(result, "json", result)
        if callable(value):
            value = value()
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, dict) and isinstance(value.get("res"), dict):
            value = value["res"]
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _bbox(polygon: Any) -> BoundingBox | None:
        if polygon is None:
            return None
        points = list(polygon)
        if not points:
            return None
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        return BoundingBox(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))
