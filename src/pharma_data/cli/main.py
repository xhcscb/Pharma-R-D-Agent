import json
from pathlib import Path
from typing import Any

import typer

from pharma_data.config import get_settings
from pharma_data.connectors import (
    CdeManifestAdapter,
    ChinaDrugTrialsManifestAdapter,
    ClinicalDocumentAdapter,
    ClinicalTrialsGovAdapter,
    EarningsCallAdapter,
    FinancialReportAdapter,
    NewsAdapter,
    ResearchReportManifestAdapter,
)
from pharma_data.contracts import AccessClass, ReviewStatus
from pharma_data.datasets import DataQualityValidator, DatasetBenchmarkEvaluator
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical import create_schema, session_scope
from pharma_data.storage.canonical.models import Document, DocumentVersion, ProcessingJob
from pharma_data.storage.canonical.repository import CanonicalRepository
from pharma_data.storage.object_store import LocalObjectStore
from pharma_data.storage.projectors import ProjectionDispatcher

app = typer.Typer(help="Pharma analyst data-layer control plane")
db_app = typer.Typer(help="Database operations")
source_app = typer.Typer(help="Authoritative source synchronization")
ingest_app = typer.Typer(help="Manifest ingestion")
pipeline_app = typer.Typer(help="Controlled pipeline operations")
review_app = typer.Typer(help="Human review operations")
projection_app = typer.Typer(help="Knowledge-store projections")
dataset_app = typer.Typer(help="Dataset snapshot operations")
eval_app = typer.Typer(help="Quality validation")

app.add_typer(db_app, name="db")
app.add_typer(source_app, name="source")
app.add_typer(ingest_app, name="ingest")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(review_app, name="review")
app.add_typer(projection_app, name="projection")
app.add_typer(dataset_app, name="dataset")
app.add_typer(eval_app, name="eval")


MANIFEST_ADAPTERS = {
    "research_reports": ResearchReportManifestAdapter,
    "china_drug_trials": ChinaDrugTrialsManifestAdapter,
    "cde": CdeManifestAdapter,
    "clinical_documents": ClinicalDocumentAdapter,
    "financial_reports": FinancialReportAdapter,
    "news": NewsAdapter,
    "earnings_calls": EarningsCallAdapter,
}


def print_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


@db_app.command("migrate")
def db_migrate() -> None:
    create_schema()
    typer.echo("Database schema is ready.")


@source_app.command("sync")
def source_sync(
    source: str,
    condition: str | None = typer.Option(None),
    intervention: str | None = typer.Option(None),
    page_size: int = typer.Option(100, min=1, max=1000),
    max_pages: int | None = typer.Option(None, min=1),
) -> None:
    if source != "clinicaltrials":
        raise typer.BadParameter("Automated sync currently supports clinicaltrials")
    create_schema()
    query = {
        key: value
        for key, value in {
            "condition": condition,
            "intervention": intervention,
            "page_size": page_size,
        }.items()
        if value is not None
    }
    with session_scope() as session:
        report = IngestionService(
            session,
            LocalObjectStore(get_settings().object_store_root),
        ).ingest(ClinicalTrialsGovAdapter(), query, max_pages=max_pages)
        print_json(report.__dict__)


@ingest_app.command("manifest")
def ingest_manifest(
    path: Path,
    source_type: str = typer.Option(..., "--source-type"),
) -> None:
    adapter_class = MANIFEST_ADAPTERS.get(source_type)
    if adapter_class is None:
        raise typer.BadParameter(
            f"source_type must be one of: {', '.join(sorted(MANIFEST_ADAPTERS))}"
        )
    create_schema()
    with session_scope() as session:
        report = IngestionService(
            session,
            LocalObjectStore(get_settings().object_store_root),
        ).ingest(adapter_class(path), {"manifest_path": str(path)})
        print_json(report.__dict__)


@pipeline_app.command("run")
def pipeline_run(document_id: str) -> None:
    create_schema()
    with session_scope() as session:
        document = session.get(Document, document_id)
        if document is None or not document.current_version_id:
            raise typer.BadParameter("Document does not exist or has no version")
        version = session.get(DocumentVersion, document.current_version_id)
        if version is None:
            raise typer.BadParameter("Current document version is missing")
        repository = CanonicalRepository(session)
        job = repository.enqueue_job(
            document_version_id=version.id,
            pipeline_step="full_pipeline",
            input_hash=version.content_hash,
            component_version="0.1.0-cli",
        )
        result = PipelineRunner(session).run(job.id)
        print_json(result)


@pipeline_app.command("retry")
def pipeline_retry(job_id: str) -> None:
    with session_scope() as session:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            raise typer.BadParameter("Job does not exist")
        job.status = "FAILED_RETRYABLE"
        job.locked_at = None
        job.locked_by = None
        result = PipelineRunner(session).run(job.id)
        print_json(result)


@review_app.command("list")
def review_list(limit: int = typer.Option(100, min=1, max=500)) -> None:
    with session_scope() as session:
        print_json(CanonicalRepository(session).review_queue(limit))


@review_app.command("approve")
def review_approve(
    target_type: str,
    target_id: str,
    reviewer: str = typer.Option(...),
    rationale: str = typer.Option(...),
) -> None:
    with session_scope() as session:
        decision = CanonicalRepository(session).record_review(
            target_type=target_type,
            target_id=target_id,
            decision=ReviewStatus.APPROVED,
            reviewer=reviewer,
            rationale=rationale,
        )
        print_json({"review_id": decision.id, "decision": decision.decision})


@projection_app.command("dispatch")
def projection_dispatch(
    name: str | None = typer.Option(None),
    limit: int = typer.Option(100, min=1, max=1000),
) -> None:
    with session_scope() as session:
        print_json(ProjectionDispatcher().dispatch_pending(session, name, limit))


@projection_app.command("rebuild")
def projection_rebuild(name: str) -> None:
    dispatcher = ProjectionDispatcher()
    projector = dispatcher.projectors.get(name)
    if projector is None:
        raise typer.BadParameter(f"name must be one of: {', '.join(sorted(dispatcher.projectors))}")
    with session_scope() as session:
        print_json(projector.rebuild(session))


@dataset_app.command("build")
def dataset_build(spec: Path) -> None:
    payload = json.loads(spec.read_text(encoding="utf-8"))
    with session_scope() as session:
        snapshot = CanonicalRepository(session).create_snapshot(
            name=payload["name"],
            specification=payload.get("specification", {}),
            manifest={"document_version_ids": payload["document_version_ids"]},
            access_class=AccessClass(payload.get("access_class", "team_internal")),
            created_by=payload["created_by"],
        )
        print_json(
            {
                "id": snapshot.id,
                "snapshot_hash": snapshot.snapshot_hash,
                "access_class": snapshot.access_class,
            }
        )


@eval_app.command("all")
def eval_all() -> None:
    with session_scope() as session:
        report = DataQualityValidator(session).run()
        print_json(report)
        if not report["passed"]:
            raise typer.Exit(1)


@eval_app.command("benchmark")
def eval_benchmark(gold: Path) -> None:
    report = DatasetBenchmarkEvaluator().evaluate_file(gold)
    print_json(report)
    if not report["passed"]:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
