import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.api.app import app
from pharma_data.config import get_settings
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    EntityMentionRecord,
    EntityRecord,
)


def test_rest_and_graphql_expose_public_document(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "api.db"
    object_root = tmp_path / "objects"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(object_root))
    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-secret")
    monkeypatch.setenv("PUBLIC_INBOX_ROOT", str(tmp_path / "public-inbox"))
    monkeypatch.setenv("PUBLIC_INBOX_ARCHIVE_ROOT", str(tmp_path / "public-archive"))
    monkeypatch.setenv("PUBLIC_INBOX_METADATA_ROOT", str(tmp_path / "public-metadata"))
    monkeypatch.setenv("PUBLIC_INBOX_QUARANTINE_ROOT", str(tmp_path / "public-quarantine"))
    monkeypatch.setenv("RESTRICTED_INBOX_ROOT", str(tmp_path / "restricted-inbox"))
    monkeypatch.setenv(
        "RESTRICTED_INBOX_ARCHIVE_ROOT",
        str(tmp_path / "restricted-archive"),
    )
    monkeypatch.setenv(
        "RESTRICTED_INBOX_METADATA_ROOT",
        str(tmp_path / "restricted-metadata"),
    )
    monkeypatch.setenv(
        "RESTRICTED_INBOX_QUARANTINE_ROOT",
        str(tmp_path / "restricted-quarantine"),
    )
    monkeypatch.setenv("INBOX_SETTLE_SECONDS", "0")
    get_settings.cache_clear()
    get_engine.cache_clear()

    article = tmp_path / "article.html"
    article.write_text("<h1>Official</h1><p>Public evidence</p>", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "NEWS-API-1",
                    "title": "Official API fixture",
                    "local_path": str(article),
                    "license_status": "public",
                    "access_class": "public",
                }
            ]
        ),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        dashboard = client.get("/demo/data-layer")
        assert dashboard.status_code == 200
        assert "医药投研数据处理看板" in dashboard.text
        assert "自动投递与归档" in dashboard.text
        assert "推理层就绪度" in dashboard.text
        denied_ingestion = client.post(
            "/v1/ingestions",
            json={
                "source_type": "news",
                "query": {"manifest_path": str(manifest)},
            },
        )
        assert denied_ingestion.status_code == 403
        response = client.post(
            "/v1/ingestions",
            json={
                "source_type": "news",
                "query": {"manifest_path": str(manifest)},
            },
            headers={"X-Internal-API-Key": "test-internal-secret"},
        )
        assert response.status_code == 200
        assert response.json()["versions_created"] == 1

        with Session(get_engine()) as session:
            document = session.scalar(select(Document))
            document_id = document.id

        document_response = client.get(f"/v1/documents/{document_id}")
        assert document_response.status_code == 200
        assert document_response.json()["title"] == "Official API fixture"

        graphql_response = client.post(
            "/graphql",
            json={"query": f'query {{ document(id: "{document_id}") {{ title }} }}'},
        )
        assert graphql_response.status_code == 200
        assert graphql_response.json()["data"]["document"]["title"] == "Official API fixture"

        overview = client.get("/v1/visualizations/data-layer")
        assert overview.status_code == 200
        assert overview.json()["summary"]["sources"] == 1
        assert overview.json()["summary"]["documents"] == 1
        assert overview.json()["documents"][0]["title"] == "Official API fixture"
        assert overview.json()["relation_graph"]["nodes"] == []
        assert overview.json()["entity_extraction_example"] is None
        summary = client.post(
            "/v1/reasoning/summarize",
            json={"access_class": "public"},
        )
        assert summary.status_code == 200
        assert summary.json()["tldr"] == "当前权限和筛选条件下没有可用主张。"
        context = client.post(
            "/v1/reasoning/context",
            json={"access_class": "public"},
        )
        assert context.status_code == 200
        assert context.json()["schema_version"] == "1.0"
        assert context.json()["readiness"]["claim_count"] == 0
        assert context.json()["claim_graph"]["claims"] == []
        assert client.get("/v1/inbox/status").status_code == 403
        inbox = client.get(
            "/v1/inbox/status",
            headers={"X-Internal-API-Key": "test-internal-secret"},
        )
        assert inbox.status_code == 200
        assert inbox.json()["pending_files"] == 0

    get_engine.cache_clear()
    get_settings.cache_clear()


def test_restricted_document_requires_internal_api_key(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "restricted-api.db"
    object_root = tmp_path / "restricted-objects"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(object_root))
    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-secret")
    get_settings.cache_clear()
    get_engine.cache_clear()

    report_pdf = tmp_path / "authorized.pdf"
    report_pdf.write_bytes(b"%PDF-1.4\n% authorized fixture")
    manifest = tmp_path / "research.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_record_id": "RR-API-1",
                    "title": "Restricted research fixture",
                    "local_path": str(report_pdf),
                    "license_status": "authorized_restricted",
                    "access_class": "restricted",
                }
            ]
        ),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/ingestions",
            json={
                "source_type": "research_reports",
                "query": {"manifest_path": str(manifest)},
            },
            headers={"X-Internal-API-Key": "test-internal-secret"},
        )
        assert response.status_code == 200

        with Session(get_engine()) as session:
            document = session.scalar(select(Document))
            document_id = document.id
            company = EntityRecord(
                entity_type="Company",
                canonical_name="受限样例公司",
                normalized_name="受限样例公司",
                review_status="approved",
            )
            session.add(company)
            session.flush()
            mention = EntityMentionRecord(
                document_version_id=document.current_version_id,
                entity_id=company.id,
                entity_type="Company",
                original_text="受限样例公司",
                normalized_name="受限样例公司",
                extraction_method="fixture",
                confidence=1,
                link_status="approved",
            )
            session.add(mention)
            session.flush()
            assertion = AssertionRecord(
                subject_entity_id=company.id,
                subject_mention_id=mention.id,
                predicate="REPORTS",
                object_value="10",
                object_unit="亿元",
                qualifiers={"metric_name": "营业收入"},
                assertion_mode="stated",
                extraction_method="fixture",
                confidence=1,
                review_status="approved",
                assertion_key="a" * 64,
            )
            session.add(assertion)
            session.flush()
            session.add(
                AssertionEvidenceRecord(
                    assertion_id=assertion.id,
                    document_version_id=document.current_version_id,
                    evidence_role="support",
                    evidence_text="受限样例公司营业收入10亿元",
                    page_number=1,
                )
            )
            session.commit()

        assert client.get(f"/v1/documents/{document_id}").status_code == 404
        hidden = client.post(
            "/graphql",
            json={"query": f'query {{ document(id: "{document_id}") {{ title }} }}'},
        )
        assert hidden.json()["data"]["document"] is None
        denied = client.get(
            f"/v1/documents/{document_id}",
            params={"caller_access": "restricted"},
        )
        assert denied.status_code == 403
        allowed = client.get(
            f"/v1/documents/{document_id}",
            params={"caller_access": "restricted"},
            headers={"X-Internal-API-Key": "test-internal-secret"},
        )
        assert allowed.status_code == 200

        public_overview = client.get("/v1/visualizations/data-layer")
        assert public_overview.status_code == 200
        assert public_overview.json()["summary"]["documents"] == 0
        denied_overview = client.get(
            "/v1/visualizations/data-layer",
            params={"caller_access": "restricted"},
        )
        assert denied_overview.status_code == 403
        internal_overview = client.get(
            "/v1/visualizations/data-layer",
            params={"caller_access": "restricted"},
            headers={"X-Internal-API-Key": "test-internal-secret"},
        )
        assert internal_overview.status_code == 200
        assert internal_overview.json()["summary"]["documents"] == 1
        denied_summary = client.post(
            "/v1/reasoning/summarize",
            json={"entity": "受限样例公司", "access_class": "restricted"},
        )
        assert denied_summary.status_code == 403
        allowed_summary = client.post(
            "/v1/reasoning/summarize",
            json={"entity": "受限样例公司", "access_class": "restricted"},
            headers={"X-Internal-API-Key": "test-internal-secret"},
        )
        assert allowed_summary.status_code == 200
        assert "claim:" in allowed_summary.json()["tldr"]

    get_engine.cache_clear()
    get_settings.cache_clear()
