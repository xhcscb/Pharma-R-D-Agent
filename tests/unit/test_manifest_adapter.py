import json

from pharma_data.connectors.news import NewsAdapter
from pharma_data.contracts import AccessClass, LicenseStatus


def test_manifest_adapter_reads_jsonl_and_fetches_local_file(tmp_path) -> None:
    article = tmp_path / "article.html"
    article.write_text("<h1>Official update</h1>", encoding="utf-8")
    manifest = tmp_path / "news.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "source_record_id": "NEWS-1",
                "title": "Official update",
                "local_path": str(article),
                "license_status": "public",
                "access_class": "public",
            }
        ),
        encoding="utf-8",
    )

    adapter = NewsAdapter(manifest)
    page = adapter.discover({"manifest_path": str(manifest)})
    record = page.records[0]
    fetched = adapter.fetch(record)[0]

    assert record.license_status == LicenseStatus.PUBLIC
    assert record.access_class == AccessClass.PUBLIC
    assert fetched.media_type == "text/html"
    assert b"Official update" in fetched.content
