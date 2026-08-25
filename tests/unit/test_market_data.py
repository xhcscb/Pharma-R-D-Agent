import json

from pharma_data.connectors.market_data import MarketDataAdapter
from pharma_data.contracts import DocumentType, LicenseStatus
from pharma_data.entity_extraction.extractors import PatternExtractor
from pharma_data.parsers.router import DocumentParser
from pharma_data.relation_extraction.agent import RelationExtractAgent
from pharma_data.storage.canonical.models import AssertionRecord
from pharma_data.storage.timescale.projector import TimescaleProjector


def test_market_manifest_defaults_to_restricted_authorized_data(tmp_path) -> None:
    data_file = tmp_path / "market.json"
    data_file.write_text(json.dumps({"收盘价": 42.1}), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "SSE-600276-20260821",
                    "title": "600276 2026-08-21 日行情",
                    "local_path": str(data_file),
                }
            ]
        ),
        encoding="utf-8",
    )
    record = MarketDataAdapter(manifest).discover({"manifest_path": str(manifest)}).records[0]
    assert record.document_type == DocumentType.MARKET_DATA
    assert record.license_status == LicenseStatus.AUTHORIZED_RESTRICTED
    assert record.access_class.value == "restricted"


def test_market_metric_routes_to_market_price(db_session) -> None:
    assertion = AssertionRecord(
        subject_mention_id="fixture",
        predicate="REPORTS",
        object_value="42.1",
        qualifiers={"metric_name": "收盘价"},
        assertion_mode="stated",
        extraction_method="fixture",
        confidence=1,
        review_status="approved",
        assertion_key="m" * 64,
    )
    targets = TimescaleProjector.__new__(TimescaleProjector)._target_tables(
        db_session, assertion
    )
    assert "market_price" in targets
    assert "financial_metric_series" not in targets


def test_market_json_produces_company_metric_assertions(tmp_path) -> None:
    path = tmp_path / "market.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "company": "恒瑞医药",
                        "stock_code": "600276.SH",
                        "trade_date": "2026-08-21",
                        "open": 42,
                        "close": 43.1,
                        "volume": 10000,
                        "currency": "CNY",
                        "adjustment": "unadjusted",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    document = DocumentParser().parse(
        path,
        media_type="application/json",
        document_id="d1",
        document_version_id="v1",
        document_type=DocumentType.MARKET_DATA,
        artifact_id="a1",
    )
    mentions = PatternExtractor().extract(document)
    assertions = RelationExtractAgent().extract(document, mentions)
    close = next(item for item in assertions if item.qualifiers.get("metric_name") == "收盘价")
    assert close.object_value == "43.1"
    assert close.object_unit == "元"
    assert document.elements[0].structured_payload["market_record"]["stock_code"] == "600276.SH"
