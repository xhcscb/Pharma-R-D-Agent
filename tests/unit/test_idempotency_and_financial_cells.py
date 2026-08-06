from openpyxl import Workbook

from pharma_data.cleaning import DataCleanAgent
from pharma_data.contracts import DocumentType, ElementType, ParsedDocument
from pharma_data.entity_extraction import EntityExtractAgent, PatternExtractor
from pharma_data.parsers.common import make_element
from pharma_data.parsers.structured import SpreadsheetParser
from pharma_data.relation_extraction import RelationExtractAgent


def test_pipeline_artifact_ids_are_stable_for_same_version_and_content() -> None:
    first = make_element(
        document_version_id="version",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text="Hengrui Pharma EPS 1.20",
        parser_name="test",
        parser_version="1",
    )
    second = make_element(
        document_version_id="version",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text="Hengrui Pharma EPS 1.20",
        parser_name="test",
        parser_version="1",
    )
    assert first.element_id == second.element_id

    document = ParsedDocument(
        document_id="document",
        document_version_id="version",
        document_type=DocumentType.FINANCIAL_REPORT,
        elements=[first],
    )
    agent = EntityExtractAgent([PatternExtractor()])
    first_mentions = agent.extract(document)
    second_mentions = agent.extract(document)
    assert [item.mention_id for item in first_mentions] == [
        item.mention_id for item in second_mentions
    ]

    first_assertions = DataCleanAgent().clean(
        document_version_id="version",
        mentions=first_mentions,
        assertions=RelationExtractAgent().extract(document, first_mentions),
    )
    second_assertions = DataCleanAgent().clean(
        document_version_id="version",
        mentions=second_mentions,
        assertions=RelationExtractAgent().extract(document, second_mentions),
    )
    assert [item.assertion_id for item in first_assertions.assertions] == [
        item.assertion_id for item in second_assertions.assertions
    ]


def test_financial_spreadsheet_emits_cell_level_evidence(tmp_path) -> None:
    path = tmp_path / "finance.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Income Statement"
    sheet.append(["Metric", "2025"])
    sheet.append(["Revenue", 100])
    workbook.save(path)

    parsed = SpreadsheetParser().parse(
        path,
        document_id="document",
        document_version_id="version",
        document_type=DocumentType.FINANCIAL_REPORT,
        artifact_id="artifact",
    )
    cell = parsed.elements[0].structured_payload["financial_cells"][0]

    assert cell["statement_type"] == "income_statement"
    assert cell["row_label"] == "Revenue"
    assert cell["column_label"] == "2025"
    assert cell["numeric_value"] == "100"
    assert cell["period_end"] == "2025-12-31"
    assert cell["cell_reference"] == "B2"
    assert cell["evidence_id"]
