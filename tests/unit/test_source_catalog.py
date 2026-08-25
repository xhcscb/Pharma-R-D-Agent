import json
from pathlib import Path


def test_authoritative_source_catalog_covers_required_categories() -> None:
    payload = json.loads(Path("config/authoritative_sources.json").read_text(encoding="utf-8"))
    categories = {source["category"] for source in payload["sources"]}
    assert {
        "券商研报",
        "临床",
        "财务报表与公告",
        "新闻",
        "电话会议",
        "证券行情",
    } <= categories
    assert all(source["authority_tier"] in {"A1", "A2"} for source in payload["sources"])
    assert all(source["enabled"] is True for source in payload["sources"])
    assert len(payload["sources"]) >= 25
    sample_categories = {
        source["category"] for source in payload["sources"] if source.get("sample_records")
    }
    assert {"财务报表与公告", "电话会议"} <= sample_categories
    assert any(
        source.get("document_type") == "news" and source.get("sample_records")
        for source in payload["sources"]
    )
    broker_source = next(
        source
        for source in payload["sources"]
        if source["source_id"] == "authorized_mainland_broker_research"
    )
    assert broker_source["access_mode"] == "authorized_manifest"
    clinical_source = next(
        source for source in payload["sources"] if source["source_id"] == "china_drug_trials"
    )
    assert clinical_source["automation_level"] == "manual"
    assert clinical_source.get("sample_records") is None
    market_sources = [
        source for source in payload["sources"] if source["category"] == "证券行情"
    ]
    assert len(market_sources) == 3
    assert all(source["access_mode"] == "authorized_manifest" for source in market_sources)
    assert all(source.get("sample_records") is None for source in market_sources)


def test_authoritative_source_catalog_is_mainland_only() -> None:
    text = Path("config/authoritative_sources.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["scope"]["jurisdiction"] == "CN-MAINLAND"
    assert all(source["jurisdiction"] == "CN-MAINLAND" for source in payload["sources"])
    assert "clinicaltrials.gov" not in text.lower()
    assert "fda.gov" not in text.lower()
    assert "sec.gov" not in text.lower()
    assert "hkex" not in text.lower()
