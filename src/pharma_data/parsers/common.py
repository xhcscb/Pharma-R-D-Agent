from typing import Any

from pharma_data.contracts import BoundingBox, DocumentElement, ElementType
from pharma_data.utils.hashing import stable_hash, stable_uuid


def make_element(
    *,
    document_version_id: str,
    element_type: ElementType,
    reading_order: int,
    text: str,
    parser_name: str,
    parser_version: str,
    page_number: int | None = None,
    bbox: BoundingBox | None = None,
    structured_payload: dict[str, Any] | None = None,
    confidence: float = 1.0,
) -> DocumentElement:
    payload = structured_payload or {}
    content_hash = stable_hash(
        {
            "page": page_number,
            "type": element_type.value,
            "bbox": bbox.model_dump() if bbox else None,
            "text": text,
            "payload": payload,
        }
    )
    return DocumentElement(
        element_id=stable_uuid([document_version_id, reading_order, content_hash]),
        document_version_id=document_version_id,
        page_number=page_number,
        element_type=element_type,
        bbox=bbox,
        reading_order=reading_order,
        text=text,
        structured_payload=payload,
        parser_name=parser_name,
        parser_version=parser_version,
        confidence=confidence,
        content_hash=content_hash,
    )
