# Local operations

## Start the core

1. Copy .env.example to .env and replace placeholder passwords and contact details.
2. Run: docker compose --profile core up -d --build
3. Run: docker compose --profile core exec api alembic upgrade head
4. Open /docs and /graphql on http://127.0.0.1:8000.

## Ingest and process

    datactl ingest manifest manifests/examples/news.csv --source-type news
    datactl source sync clinicaltrials --condition oncology --page-size 100 --max-pages 1
    datactl pipeline run DOCUMENT_ID

## Review and project

    datactl review list
    datactl review approve assertion ASSERTION_ID --reviewer NAME --rationale TEXT
    datactl projection dispatch
    datactl projection rebuild neo4j

## Validate

    datactl eval all
    pytest
    ruff check src tests

The full profile is resource intensive. Test graph, vector, timeseries, and search
profiles separately on a laptop.


## Profiles

- core: API, worker, and canonical PostgreSQL.
- graph: Neo4j.
- vector: Milvus, etcd, and MinIO.
- timeseries: TimescaleDB.
- search: Elasticsearch.
- full: every service.

The Docker image installs the lockfile-pinned documents, audio, and ML extras
required by the full parsing pipeline.

## Access and licensing

Set INTERNAL_API_KEY to a long random value before loading restricted material.
Use X-Internal-API-Key for non-public REST reads. Unknown, prohibited, and
metadata-only records are quarantined before content download.

## Quality benchmark

    datactl eval benchmark path/to/gold-benchmark.json

The command exits non-zero when any declared release threshold fails. See
benchmark.md and acceptance.md before creating a release tag.

## Recovery

Jobs are claimed with FOR UPDATE SKIP LOCKED. A failed job becomes
FAILED_RETRYABLE until the retry ceiling, then FAILED_FINAL. Use
datactl pipeline retry JOB_ID after fixing the source or configuration.
Projection failures remain unpublished in the outbox with attempts and the last
error; rerun datactl projection dispatch after the target store recovers.
