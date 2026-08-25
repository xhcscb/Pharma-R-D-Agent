import base64
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from pharma_data.config import Settings
from pharma_data.contracts import (
    DocumentType,
    ElementType,
    ParsedDocument,
    RelationType,
    TableCell,
)
from pharma_data.entity_extraction import (
    EntityExtractAgent,
    PatternExtractor,
    VisualSemanticExtractor,
)
from pharma_data.parsers.common import make_element
from pharma_data.parsers.mineru import _persist_response_images
from pharma_data.parsers.visual_semantics import (
    _pipeline_stage_layout,
    analyze_pipeline_stage_chart,
    enrich_visual_semantics,
)
from pharma_data.relation_extraction import RelationExtractAgent


def _pipeline_cells() -> list[TableCell]:
    values = [
        (0, 0, "治疗领域"),
        (0, 1, "系统"),
        (0, 2, "药品名称/代号"),
        (0, 3, "靶点"),
        (0, 4, "单药/联合"),
        (0, 5, "适应症"),
        (0, 6, "I期"),
        (0, 7, "II期"),
        (0, 8, "III期"),
        (0, 9, "NDA"),
        (1, 2, "DRUG-A"),
        (1, 3, "TARGET-A"),
        (1, 4, "单药"),
        (1, 5, "适应症甲"),
        (1, 6, "中国"),
        (1, 7, ""),
        (1, 8, ""),
        (1, 9, ""),
        (2, 2, "DRUG-B"),
        (2, 3, "TARGET-B"),
        (2, 4, "单药"),
        (2, 5, "适应症乙"),
        (2, 6, "澳洲"),
        (2, 7, ""),
        (2, 8, ""),
        (2, 9, ""),
    ]
    return [
        TableCell(row_index=row, column_index=column, text=text)
        for row, column, text in values
    ]


def _pipeline_image(path: Path) -> None:
    image = Image.new("RGB", (400, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((200, 25, 348, 45), fill="#3b6798")
    draw.polygon(((348, 25), (350, 35), (348, 45)), fill="#3b6798")
    draw.rectangle((200, 70, 248, 90), fill="#c65350")
    draw.polygon(((248, 70), (250, 80), (248, 90)), fill="#c65350")
    image.save(path)


def _one_page_pdf(path: Path) -> None:
    pdf = fitz.open()
    pdf.new_page(width=400, height=120)
    pdf.save(path)
    pdf.close()


def test_pipeline_chart_maps_bar_endpoints_and_keeps_color_and_region(tmp_path: Path) -> None:
    image_path = tmp_path / "pipeline.png"
    _pipeline_image(image_path)
    cells = _pipeline_cells()
    layout = _pipeline_stage_layout(cells)

    result = analyze_pipeline_stage_chart(image_path, cells, layout)

    assert result["status"] == "verified"
    assert [item["stage"] for item in result["observations"]] == [
        "PHASE_III",
        "PHASE_I",
    ]
    assert [item["region"] for item in result["observations"]] == ["中国", "澳洲"]
    assert result["observations"][0]["bar_color"] != result["observations"][1][
        "bar_color"
    ]


def test_visual_enrichment_reaches_stage_assertion_and_reasoning_evidence(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "pipeline.png"
    pdf_path = tmp_path / "pipeline.pdf"
    _pipeline_image(image_path)
    _one_page_pdf(pdf_path)
    element = make_element(
        document_version_id="version",
        element_type=ElementType.TABLE,
        reading_order=0,
        text="pipeline table",
        parser_name="mineru",
        parser_version="3.4.0",
        page_number=1,
        structured_payload={
            "mineru_content": {
                "img_path": "images/pipeline.png",
                "visual_asset": {"path": str(image_path.resolve()), "sha256": "fixture"},
            }
        },
    ).model_copy(update={"table_cells": _pipeline_cells()})
    document = ParsedDocument(
        document_id="document",
        document_version_id="version",
        document_type=DocumentType.RESEARCH_REPORT,
        metadata={
            "formal_reasoning_eligible": True,
            "page_quality": [{"page_number": 1, "passed": True, "failures": []}],
            "failed_pages": [],
        },
        elements=[element],
    )

    enriched = enrich_visual_semantics(
        document,
        pdf_path,
        Settings(_env_file=None, visual_semantics_required=True),
    )
    semantic_elements = [
        item for item in enriched.elements if item.element_type == ElementType.STRUCTURED_RECORD
    ]
    mentions = EntityExtractAgent(
        [PatternExtractor(), VisualSemanticExtractor()]
    ).extract(enriched)
    assertions = RelationExtractAgent().extract(enriched, mentions)
    visual_assertions = [
        item
        for item in assertions
        if item.predicate == RelationType.HAS_STAGE
        and item.extraction_method == "visual_geometry:PIPELINE_HAS_STAGE"
    ]

    assert enriched.metadata["formal_reasoning_eligible"] is True
    assert enriched.parse_quality["visual_semantic_coverage"] == 1.0
    assert len(semantic_elements) == 2
    assert len(visual_assertions) == 2
    assert visual_assertions[0].qualifiers["source_structure"] == "visual_chart_geometry"
    assert visual_assertions[0].qualifiers["visual_asset"]["sha256"] == "fixture"


def test_mineru_response_images_are_archived_as_hashed_visual_evidence(
    tmp_path: Path,
) -> None:
    image = Image.new("RGB", (16, 8), "navy")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    payload = {
        "results": {
            "report": {
                "images": {"visual.png": f"data:image/png;base64,{encoded}"}
            }
        }
    }

    assets = _persist_response_images(
        payload,
        tmp_path / "images",
        max_image_bytes=1024 * 1024,
    )

    assert assets["visual.png"]["mime_type"] == "image/png"
    assert assets["visual.png"]["pixel_width"] == 16
    assert Path(assets["visual.png"]["path"]).is_file()
    assert len(assets["visual.png"]["sha256"]) == 64
