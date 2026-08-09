import json
from pathlib import Path


def test_authoritative_source_catalog_covers_required_categories() -> None:
    payload = json.loads(Path("config/authoritative_sources.json").read_text(encoding="utf-8"))
    categories = {source["category"] for source in payload["sources"]}
    assert {"券商研报", "临床", "财务报表与公告", "新闻", "电话会议"} <= categories
    assert all(source["authority_tier"] in {"A1", "A2"} for source in payload["sources"])
    assert all(source["enabled"] is True for source in payload["sources"])
    assert len(payload["sources"]) >= 25


def test_authoritative_source_catalog_is_mainland_only() -> None:
    text = Path("config/authoritative_sources.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["scope"]["jurisdiction"] == "CN-MAINLAND"
    assert all(source["jurisdiction"] == "CN-MAINLAND" for source in payload["sources"])
    assert "clinicaltrials.gov" not in text.lower()
    assert "fda.gov" not in text.lower()
    assert "sec.gov" not in text.lower()
    assert "hkex" not in text.lower()
