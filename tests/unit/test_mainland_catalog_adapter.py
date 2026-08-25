import pytest
import respx
from httpx import Response

from pharma_data.connectors.mainland import MainlandCatalogAdapter
from pharma_data.contracts import AccessClass, LicenseStatus


def source_config() -> dict[str, object]:
    return {
        "source_id": "nhsa_test",
        "authority": "国家医疗保障局",
        "authority_tier": "A1",
        "jurisdiction": "CN-MAINLAND",
        "base_url": "https://www.nhsa.gov.cn",
        "terms_url": None,
        "allowed_domains": ["nhsa.gov.cn"],
        "document_type": "regulatory",
        "sample_records": [
            {
                "source_record_id": "NHSA-1",
                "title": "官方目录",
                "published_at": "2025-12-07",
                "content_url": "https://www.nhsa.gov.cn/example.html",
            }
        ],
    }


@respx.mock
def test_mainland_catalog_adapter_fetches_allowlisted_official_record() -> None:
    respx.get("https://www.nhsa.gov.cn/example.html").mock(
        return_value=Response(
            200,
            text="<html><body>医保目录</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    adapter = MainlandCatalogAdapter(source_config())
    page = adapter.discover({"max_records": 1})
    fetched = adapter.fetch(page.records[0])[0]

    assert page.records[0].license_status == LicenseStatus.PUBLIC_ACCESS
    assert page.records[0].access_class == AccessClass.RESTRICTED
    assert fetched.media_type == "text/html"
    assert "医保目录".encode() in fetched.content


def test_mainland_catalog_adapter_rejects_non_allowlisted_domain() -> None:
    source = source_config()
    source["sample_records"] = [
        {
            "source_record_id": "BAD-1",
            "title": "错误来源",
            "content_url": "https://example.com/not-official",
        }
    ]
    adapter = MainlandCatalogAdapter(source)
    try:
        adapter.discover({})
    except ValueError as exc:
        assert "白名单" in str(exc)
    else:
        raise AssertionError("非白名单域名不应进入数据层")


@respx.mock
def test_mainland_catalog_adapter_rejects_redirect_before_foreign_fetch() -> None:
    official_url = "https://www.nhsa.gov.cn/example.html"
    foreign_url = "https://example.com/redirected"
    respx.get(official_url).mock(return_value=Response(302, headers={"location": foreign_url}))
    foreign_route = respx.get(foreign_url).mock(return_value=Response(200, text="not official"))
    adapter = MainlandCatalogAdapter(source_config())
    record = adapter.discover({}).records[0]

    with pytest.raises(ValueError, match="白名单"):
        adapter.fetch(record)

    assert foreign_route.called is False


@respx.mock
def test_mainland_catalog_adapter_rejects_script_challenge_page() -> None:
    respx.get("https://www.nhsa.gov.cn/example.html").mock(
        return_value=Response(
            200,
            text="<html><head><script>challenge()</script></head><body><script>go()</script></body></html>",
            headers={"content-type": "text/html"},
        )
    )
    adapter = MainlandCatalogAdapter(source_config())
    record = adapter.discover({}).records[0]

    with pytest.raises(ValueError, match="脚本校验或访问限制"):
        adapter.fetch(record)
