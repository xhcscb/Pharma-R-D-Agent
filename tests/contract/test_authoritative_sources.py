import json

import respx
from httpx import Response

from pharma_data.connectors.clinical import OpenFdaDrugAdapter
from pharma_data.connectors.financial_reports import (
    SecCompanyFactsAdapter,
    SecEdgarFilingsAdapter,
)
from pharma_data.connectors.news import FdaNewsAdapter

SEC_USER_AGENT = "pharma-analyst-data-test test@example.org"


@respx.mock
def test_openfda_adapter_preserves_record_and_paginates() -> None:
    record = {
        "id": "label-1",
        "effective_time": "20250131",
        "openfda": {"generic_name": ["PEMBROLIZUMAB"]},
        "indications_and_usage": ["For treatment of an indicated condition."],
    }
    respx.get(
        "https://api.fda.gov/drug/label.json",
        params={"limit": 1, "skip": 0, "search": "openfda.generic_name:pembrolizumab"},
    ).mock(
        return_value=Response(
            200,
            json={"meta": {"results": {"total": 2}}, "results": [record]},
        )
    )

    page = OpenFdaDrugAdapter().discover(
        {
            "dataset": "label",
            "search": "openfda.generic_name:pembrolizumab",
            "page_size": 1,
        }
    )
    fetched = OpenFdaDrugAdapter().fetch(page.records[0])[0]

    assert page.next_cursor == "1"
    assert page.records[0].source_record_id == "label:label-1"
    assert json.loads(fetched.content)["indications_and_usage"]


@respx.mock
def test_sec_companyfacts_keeps_complete_official_json() -> None:
    payload = {
        "cik": 310158,
        "entityName": "Merck & Co., Inc.",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"val": 1, "filed": "2025-02-01"}]}}}},
    }
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000310158.json").mock(
        return_value=Response(200, json=payload)
    )
    adapter = SecCompanyFactsAdapter(user_agent=SEC_USER_AGENT)
    page = adapter.discover({"cik": "310158"})
    fetched = adapter.fetch(page.records[0])[0]

    assert page.records[0].source_record_id == "CIK0000310158:companyfacts"
    assert page.records[0].published_at.isoformat().startswith("2025-02-01")
    assert json.loads(fetched.content)["facts"]["us-gaap"]["Revenues"]


@respx.mock
def test_sec_filings_builds_official_archive_evidence_url() -> None:
    submissions = {
        "name": "Merck & Co., Inc.",
        "tickers": ["MRK"],
        "exchanges": ["NYSE"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000310158-25-000001", "0000310158-25-000002"],
                "filingDate": ["2025-02-01", "2025-02-02"],
                "reportDate": ["2024-12-31", "2025-01-31"],
                "form": ["10-K", "4"],
                "primaryDocument": ["mrk-20241231.htm", "ownership.xml"],
            }
        },
    }
    respx.get("https://data.sec.gov/submissions/CIK0000310158.json").mock(
        return_value=Response(200, json=submissions)
    )
    filing_url = (
        "https://www.sec.gov/Archives/edgar/data/310158/000031015825000001/mrk-20241231.htm"
    )
    respx.get(filing_url).mock(
        return_value=Response(200, text="<html><body><p>Official filing</p></body></html>")
    )
    adapter = SecEdgarFilingsAdapter(user_agent=SEC_USER_AGENT)
    page = adapter.discover({"cik": "310158", "forms": "10-K", "page_size": 10})
    fetched = adapter.fetch(page.records[0])[0]

    assert len(page.records) == 1
    assert str(page.records[0].canonical_url) == filing_url
    assert fetched.media_type == "text/html"
    assert b"Official filing" in fetched.content


@respx.mock
def test_fda_news_reads_official_rss_and_applies_limit() -> None:
    feed_url = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/drugs/rss.xml"
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item><title>First</title><link>https://www.fda.gov/drugs/first</link>
      <guid>fda-first</guid><pubDate>Thu, 01 Aug 2025 12:00:00 GMT</pubDate></item>
      <item><title>Second</title><link>https://www.fda.gov/drugs/second</link>
      <guid>fda-second</guid><pubDate>Fri, 02 Aug 2025 12:00:00 GMT</pubDate></item>
    </channel></rss>"""
    respx.get(feed_url).mock(return_value=Response(200, content=rss))

    page = FdaNewsAdapter(feed_url).discover({"max_records": 1})

    assert len(page.records) == 1
    assert page.records[0].source_name == "fda_news"
    assert page.records[0].source_record_id == "fda-first"
