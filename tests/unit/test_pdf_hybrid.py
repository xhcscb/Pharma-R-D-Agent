import fitz

from pharma_data.config import Settings
from pharma_data.contracts import DocumentType, ElementType, ParsedDocument
from pharma_data.parsers.common import make_element
from pharma_data.parsers.pdf_hybrid import HybridPdfParser, PdfQualitySelector


def test_native_pdf_preserves_page_and_coordinates(tmp_path) -> None:
    path = tmp_path / "native.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Official clinical and financial evidence")
    pdf.save(path)
    pdf.close()

    parsed = HybridPdfParser(settings=Settings(_env_file=None, mineru_enabled=False)).parse(
        path,
        document_id="document",
        document_version_id="version",
        document_type=DocumentType.RESEARCH_REPORT,
        artifact_id="artifact",
    )

    assert parsed.elements
    assert parsed.elements[0].page_number == 1
    assert parsed.elements[0].bbox is not None
    assert parsed.metadata["selected_parser"] == "pymupdf-layout"
    assert parsed.metadata["degraded_mode"] is True
    assert parsed.metadata["formal_reasoning_eligible"] is False


def test_pdf_quality_selector_prefers_located_high_confidence_content() -> None:
    weak = ParsedDocument(
        document_id="document",
        document_version_id="version",
        document_type=DocumentType.RESEARCH_REPORT,
        metadata={"parser_candidate": "weak"},
        elements=[],
    )
    strong_element = make_element(
        document_version_id="version",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text="evidence " * 100,
        parser_name="strong",
        parser_version="1",
    )
    strong = weak.model_copy(
        update={
            "metadata": {"parser_candidate": "strong"},
            "elements": [strong_element],
        }
    )

    selected = PdfQualitySelector().select([weak, strong])

    assert selected.metadata["selected_parser"] == "strong"
    assert selected.parse_quality["selector_score"] > 0
