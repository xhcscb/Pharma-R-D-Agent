"""Compare eligible canonical IDs with Neo4j, Milvus, TimescaleDB and Elasticsearch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan
from neo4j import GraphDatabase
from pymilvus import MilvusClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from pharma_data.config import get_settings
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
)


def _comparison(expected: set[str], actual: set[str]) -> dict[str, Any]:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    return {
        "expected": len(expected),
        "actual": len(actual),
        "missing": len(missing),
        "extra": len(extra),
        "missing_sample": missing[:10],
        "extra_sample": extra[:10],
        "id_consistency": 1.0 if not missing and not extra else 0.0,
    }


def _canonical_ids(session: Session) -> tuple[set[str], set[str], set[str]]:
    element_rows = list(
        session.execute(
            select(DocumentElementRecord.id, DocumentElementRecord.text)
            .join(
                DocumentVersion,
                DocumentVersion.id == DocumentElementRecord.document_version_id,
            )
            .join(Document, Document.current_version_id == DocumentVersion.id)
            .where(DocumentElementRecord.parse_run_id == DocumentVersion.active_parse_run_id)
        )
    )
    element_ids = {str(row.id) for row in element_rows}
    vector_element_ids = {str(row.id) for row in element_rows if row.text.strip()}
    approved_assertion_ids = set(
        session.scalars(
            select(AssertionRecord.id)
            .join(
                AssertionEvidenceRecord,
                AssertionEvidenceRecord.assertion_id == AssertionRecord.id,
            )
            .join(
                DocumentVersion,
                DocumentVersion.id == AssertionEvidenceRecord.document_version_id,
            )
            .join(
                DocumentElementRecord,
                DocumentElementRecord.id == AssertionEvidenceRecord.element_id,
            )
            .where(
                AssertionRecord.review_status == "approved",
                DocumentElementRecord.parse_run_id == DocumentVersion.active_parse_run_id,
            )
            .distinct()
        )
    )
    return element_ids, vector_element_ids, approved_assertion_ids


def build_report() -> dict[str, Any]:
    settings = get_settings()
    with Session(get_engine()) as session:
        element_ids, vector_element_ids, approved_assertion_ids = _canonical_ids(session)

    elasticsearch = Elasticsearch(settings.elasticsearch_url)
    es_elements = {
        str(item["_id"])
        for item in scan(
            elasticsearch,
            index="document_elements",
            query={"query": {"match_all": {}}},
            _source=False,
        )
        if not str(item["_id"]).startswith("assertion:")
    }

    milvus = MilvusClient(uri=settings.milvus_uri)
    milvus_elements = {
        str(item["id"])
        for item in milvus.query(
            collection_name="document_chunks",
            filter='id != ""',
            output_fields=["id"],
            limit=max(len(vector_element_ids) + 100, 1000),
        )
    }

    with GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    ) as driver:
        records, _, _ = driver.execute_query(
            "MATCH (a:Assertion) RETURN a.id AS id",
            database_="neo4j",
        )
        neo4j_assertions = {str(record["id"]) for record in records}

    timescale = create_engine(settings.timescale_url, pool_pre_ping=True)
    timescale_assertions: set[str] = set()
    tables = (
        "market_price",
        "financial_metric_series",
        "clinical_event",
        "regulatory_event",
        "news_event",
        "assertion_version_event",
    )
    with timescale.connect() as connection:
        for table in tables:
            timescale_assertions.update(
                str(value)
                for value in connection.execute(
                    text(f"SELECT DISTINCT assertion_id FROM {table}")
                ).scalars()
            )

    comparisons = {
        "elasticsearch_active_elements": _comparison(element_ids, es_elements),
        "milvus_nonempty_active_elements": _comparison(
            vector_element_ids, milvus_elements
        ),
        "neo4j_approved_assertions": _comparison(
            approved_assertion_ids, neo4j_assertions
        ),
        "timescale_approved_assertions": _comparison(
            approved_assertion_ids, timescale_assertions
        ),
    }
    return {
        "status": "passed"
        if all(item["id_consistency"] == 1.0 for item in comparisons.values())
        else "failed",
        "approval_boundary": (
            "Neo4j and TimescaleDB are empty by design until assertions are approved"
        ),
        "comparisons": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/projection_id_audit_20260824.json"),
    )
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "passed" else 2)


if __name__ == "__main__":
    main()
