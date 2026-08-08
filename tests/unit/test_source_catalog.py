import json
from pathlib import Path

from pharma_data.config import Settings


def test_authoritative_source_catalog_covers_required_categories() -> None:
    payload = json.loads(Path("config/authoritative_sources.json").read_text(encoding="utf-8"))
    categories = {source["category"] for source in payload["sources"]}
    assert {"券商研报", "临床", "财务报表与公告", "新闻", "电话会议"} <= categories
    assert all(source["authority_tier"] in {"A1", "A2"} for source in payload["sources"])
    assert all(source["enabled"] is True for source in payload["sources"])


def test_sec_user_agent_requires_real_contact_configuration() -> None:
    settings = Settings(project_contact_email="team@example.org")
    assert "team@example.org" in settings.identified_sec_user_agent()

    unconfigured = Settings(project_contact_email=None, sec_user_agent=None)
    try:
        unconfigured.identified_sec_user_agent()
    except ValueError as exc:
        assert "PROJECT_CONTACT_EMAIL" in str(exc)
    else:
        raise AssertionError("未配置联系信息时不应允许 SEC 自动访问")
