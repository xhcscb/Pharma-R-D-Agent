import json

from openpyxl import Workbook

from pharma_data.contracts import DocumentType, ElementType
from pharma_data.parsers.html import HtmlParser
from pharma_data.parsers.structured import JsonParser, SpreadsheetParser


def test_html_parser_preserves_headings_tables_and_body(tmp_path) -> None:
    path = tmp_path / "article.html"
    path.write_text(
        "<html><head><title>IR</title></head><body>"
        "<nav>menu</nav><h1>Update</h1><p>Clinical result</p>"
        "<table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>ORR</td><td>50%</td></tr></table></body></html>",
        encoding="utf-8",
    )
    parsed = HtmlParser().parse(
        path,
        document_id="doc",
        document_version_id="version",
        document_type=DocumentType.NEWS,
        artifact_id="artifact",
    )

    assert [element.element_type for element in parsed.elements] == [
        ElementType.TITLE,
        ElementType.PARAGRAPH,
        ElementType.TABLE,
    ]
    assert parsed.elements[-1].structured_payload["rows"][1] == ["ORR", "50%"]


def test_json_parser_keeps_full_source_record(tmp_path) -> None:
    path = tmp_path / "study.json"
    payload = {"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    parsed = JsonParser().parse(
        path,
        document_id="doc",
        document_version_id="version",
        document_type=DocumentType.CLINICAL_RECORD,
        artifact_id="artifact",
    )

    assert parsed.elements[0].structured_payload["record"] == payload
    assert parsed.elements[0].text == ""
    assert parsed.elements[1].structured_payload["json_path"].endswith(".nctId")
    assert "NCT00000001" in parsed.elements[1].text


def test_spreadsheet_parser_preserves_sheet_rows(tmp_path) -> None:
    path = tmp_path / "finance.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Income"
    sheet.append(["Metric", "2025"])
    sheet.append(["Revenue", 100])
    workbook.save(path)

    parsed = SpreadsheetParser().parse(
        path,
        document_id="doc",
        document_version_id="version",
        document_type=DocumentType.FINANCIAL_REPORT,
        artifact_id="artifact",
    )

    assert parsed.elements[0].structured_payload["sheet"] == "Income"
    assert parsed.elements[0].structured_payload["rows"][1] == ["Revenue", 100]
