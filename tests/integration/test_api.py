import json

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.api.app import app
from pharma_data.config import get_settings
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import Document


def test_rest_and_graphql_expose_public_document(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "api.db"
    object_root = tmp_path / "objects"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("OBJECT_STORE_ROOT", str(object_root))
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
        response = client.post(
            "/v1/ingestions",
            json={
                "source_type": "news",
                "query": {"manifest_path": str(manifest)},
            },
        )
        assert response.status_code == 200
        assert response.json()["versions_created"] == 1

        with Session(get_engine()) as session:
            document = session.scalar(select(Document))

        document_response = client.get(f"/v1/documents/{document.id}")
        assert document_response.status_code == 200
        assert document_response.json()["title"] == "Official API fixture"

        graphql_response = client.post(
            "/graphql",
            json={"query": f'query {{ document(id: "{document.id}") {{ title }} }}'},
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
        )
        assert response.status_code == 200

        with Session(get_engine()) as session:
            document = session.scalar(select(Document))

        assert client.get(f"/v1/documents/{document.id}").status_code == 404
        hidden = client.post(
            "/graphql",
            json={"query": f'query {{ document(id: "{document.id}") {{ title }} }}'},
        )
        assert hidden.json()["data"]["document"] is None
        denied = client.get(
            f"/v1/documents/{document.id}",
            params={"caller_access": "restricted"},
        )
        assert denied.status_code == 403
        allowed = client.get(
            f"/v1/documents/{document.id}",
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

    get_engine.cache_clear()
    get_settings.cache_clear()
