from pathlib import Path

import fitz
import pytest

from pharma_data.config import Settings
from pharma_data.contracts import DocumentType, ElementType, ParsedDocument
from pharma_data.orchestration.pipeline import _bind_artifacts_to_run, _resolve_artifact_path
from pharma_data.parsers.common import make_element
from pharma_data.parsers.mineru import (
    MineruClient,
    MineruServiceError,
    _decode_content_list,
    apply_pdf_quality_gates,
)
from pharma_data.storage.canonical.models import RawArtifactRecord


def _one_page_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((72, 72), "Revenue 123")
    document.save(path)
    document.close()


def _two_page_pdf(path: Path) -> None:
    document = fitz.open()
    for value in ("Page one 100", "Page two 200"):
        page = document.new_page(width=600, height=800)
        page.insert_text((72, 72), value)
    document.save(path)
    document.close()


def test_content_list_decoder_preserves_page_bbox_spans_and_merged_cells(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.pdf"
    _one_page_pdf(path)
    content = [
        {
            "type": "table",
            "table_body": (
                "<table><tr><th rowspan='2'>项目</th><th colspan='2'>2025</th></tr>"
                "<tr><th>本期</th><th>上期</th></tr>"
                "<tr><td>Revenue</td><td>123</td><td>100</td></tr></table>"
            ),
            "bbox": [100, 100, 900, 500],
            "page_idx": 0,
        }
    ]
    elements = _decode_content_list(
        content,
        {},
        path,
        document_version_id="version-1",
        parser_version="3.4.0",
    )
    assert len(elements) == 1
    table = elements[0]
    assert table.element_type == ElementType.TABLE
    assert table.page_number == 1
    assert table.bbox is not None and table.bbox.x1 == pytest.approx(540)
    assert len(table.character_spans) == 1
    assert len(table.table_cells) == 7
    assert table.table_cells[0].row_span == 2
    assert table.table_cells[1].column_span == 2
    assert table.table_cells[-2].numeric_value == "123"


def test_page_quality_gate_requires_numeric_fidelity(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    _one_page_pdf(path)
    native_element = make_element(
        document_version_id="version-1",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text="Revenue 123",
        parser_name="pymupdf-layout",
        parser_version="0.2.0",
        page_number=1,
    )
    native = ParsedDocument(
        document_id="document-1",
        document_version_id="version-1",
        document_type=DocumentType.FINANCIAL_REPORT,
        metadata={"page_count": 1},
        elements=[native_element],
    )
    mineru_element = native_element.model_copy(
        update={"parser_name": "mineru", "text": "Revenue 124"}
    )
    parsed = native.model_copy(update={"elements": [mineru_element]})
    result = apply_pdf_quality_gates(parsed, native, path)
    assert result.metadata["failed_pages"] == [1]
    failures = result.metadata["page_quality"][0]["failures"]
    assert "numeric_tokens_missing" in failures
    assert "numeric_tokens_added" in failures
    assert result.metadata["formal_reasoning_eligible"] is False


def test_content_list_decoder_offsets_single_page_batch(tmp_path: Path) -> None:
    path = tmp_path / "two-pages.pdf"
    _two_page_pdf(path)
    elements = _decode_content_list(
        [{"type": "text", "text": "Page two 200", "page_idx": 0}],
        {},
        path,
        document_version_id="version-1",
        parser_version="3.4.0",
        page_offset=1,
        reading_order_offset=7,
    )

    assert len(elements) == 1
    assert elements[0].page_number == 2
    assert elements[0].reading_order == 7
    assert elements[0].structured_payload["mineru_content"]["source_page_number"] == 2


def test_remote_mineru_requires_tls_and_allowlist() -> None:
    settings = Settings(
        _env_file=None,
        mineru_execution_mode="remote",
        mineru_api_url="http://untrusted.example",
        mineru_trusted_hosts="untrusted.example",
        mineru_api_key="secret",
    )
    with pytest.raises(MineruServiceError, match="TLS"):
        MineruClient(settings)


def test_parse_locators_are_stable_within_run_and_distinct_across_runs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sample.pdf"
    _one_page_pdf(path)
    source = make_element(
        document_version_id="version-1",
        element_type=ElementType.PARAGRAPH,
        reading_order=0,
        text="Revenue 123",
        parser_name="mineru",
        parser_version="3.4.0",
        page_number=1,
    )
    parsed = ParsedDocument(
        document_id="document-1",
        document_version_id="version-1",
        document_type=DocumentType.FINANCIAL_REPORT,
        elements=[source],
    )

    run_a_first = _bind_artifacts_to_run(parsed, "run-a")
    run_a_second = _bind_artifacts_to_run(parsed, "run-a")
    run_b = _bind_artifacts_to_run(parsed, "run-b")

    assert run_a_first.elements[0].element_id == run_a_second.elements[0].element_id
    assert run_a_first.elements[0].element_id != run_b.elements[0].element_id
    assert run_a_first.elements[0].structured_payload["source_element_id"] == source.element_id


def test_artifact_path_resolves_from_configured_content_store(tmp_path: Path) -> None:
    digest = "ab" + "1" * 62
    expected = tmp_path / "objects" / "ab" / digest
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"pdf")
    artifact = RawArtifactRecord(
        source_record_id="source-record",
        media_type="application/pdf",
        object_path=r"data\objects\ab\missing",
        content_hash=digest,
        size_bytes=3,
        license_status="public_access",
        access_class="public",
    )

    assert _resolve_artifact_path(artifact, tmp_path / "objects") == expected
