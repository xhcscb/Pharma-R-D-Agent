import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import typer
from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from pharma_data.config import get_settings
from pharma_data.connectors import (
    CdeManifestAdapter,
    ChinaDrugTrialsManifestAdapter,
    ClinicalDocumentAdapter,
    EarningsCallAdapter,
    FinancialReportAdapter,
    MainlandCatalogAdapter,
    NewsAdapter,
    ResearchReportManifestAdapter,
    SourceAdapter,
)
from pharma_data.connectors.http_client import authoritative_get
from pharma_data.contracts import AccessClass, ReviewStatus
from pharma_data.datasets import DataQualityValidator, DatasetBenchmarkEvaluator
from pharma_data.orchestration.ingestion import IngestionService
from pharma_data.orchestration.pipeline import PipelineRunner
from pharma_data.storage.canonical import create_schema, session_scope
from pharma_data.storage.canonical.database import get_engine
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

SOURCE_CATALOG_PATH = Path("config/authoritative_sources.json")


def load_source_catalog() -> dict[str, Any]:
    if not SOURCE_CATALOG_PATH.is_file():
        raise FileNotFoundError(f"权威来源目录不存在: {SOURCE_CATALOG_PATH}")
    payload = json.loads(SOURCE_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("权威来源目录根节点必须是 JSON 对象")
    scope = payload.get("scope", {})
    if scope.get("jurisdiction") != "CN-MAINLAND":
        raise ValueError("权威来源目录必须限定为 CN-MAINLAND")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("权威来源目录必须包含非空 sources 数组")
    source_ids: set[str] = set()
    for source in sources:
        if source.get("jurisdiction") != "CN-MAINLAND":
            raise ValueError(f"发现非中国大陆来源: {source.get('source_id')}")
        source_id = str(source.get("source_id") or "")
        if not source_id or source_id in source_ids:
            raise ValueError(f"来源编号为空或重复: {source_id}")
        source_ids.add(source_id)
    return dict(payload)


def catalog_source(source_id: str) -> dict[str, Any]:
    for source in load_source_catalog()["sources"]:
        if source["source_id"] == source_id:
            return dict(source)
    raise KeyError(source_id)


def print_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


@db_app.command("migrate")
def db_migrate() -> None:
    try:
        create_schema()
    except OperationalError as exc:
        settings = get_settings()
        url = make_url(settings.database_url)
        print_json(
            {
                "status": "FAILED",
                "database_driver": url.drivername,
                "database_host": url.host,
                "hint": _database_error_hint(url.host),
                "error": str(exc.orig),
            }
        )
        raise typer.Exit(1) from exc
    typer.echo("数据库结构已就绪。")


@db_app.command("doctor")
def db_doctor() -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    result: dict[str, Any] = {
        "database_driver": url.drivername,
        "database_host": url.host or "local-file",
        "database_port": url.port,
    }
    try:
        with get_engine(settings.database_url).connect() as connection:
            connection.execute(sql_text("SELECT 1"))
        result["status"] = "OK"
    except OperationalError as exc:
        result.update(
            status="FAILED",
            hint=_database_error_hint(url.host),
            error=str(exc.orig),
        )
    print_json(result)
    if result["status"] != "OK":
        raise typer.Exit(1)


def _database_error_hint(host: str | None) -> str:
    if host in {"postgres", "timescaledb", "neo4j", "milvus", "elasticsearch"}:
        return (
            "当前地址是 Docker 内部服务名，不能从 Windows 本机解析。"
            "本机 CLI 请使用 SQLite 或 localhost；容器内请使用 docker compose exec。"
        )
    return "请检查数据库服务是否启动、端口是否正确以及连接配置是否可达。"


@source_app.command("list")
def source_list() -> None:
    catalog = load_source_catalog()
    print_json(
        {
            "schema_version": catalog["schema_version"],
            "sources": [
                {
                    key: source.get(key)
                    for key in (
                        "source_id",
                        "category",
                        "name",
                        "authority",
                        "authority_tier",
                        "jurisdiction",
                        "access_mode",
                        "automation_level",
                        "credential",
                        "redistribution_policy",
                        "enabled",
                        "note",
                    )
                    if source.get(key) is not None
                }
                for source in catalog["sources"]
            ],
        }
    )


@source_app.command("doctor")
def source_doctor(
    live: bool = typer.Option(False, help="执行只读网络探测"),
    strict: bool = typer.Option(False, help="任一联网探测失败时返回非零退出码"),
    source_id: str | None = typer.Option(None, help="只检查指定来源编号"),
) -> None:
    settings = get_settings()
    results = []
    failures = 0
    sources = load_source_catalog()["sources"]
    if source_id:
        sources = [source for source in sources if source["source_id"] == source_id]
        if not sources:
            raise typer.BadParameter(f"未知来源编号: {source_id}")
    for source in sources:
        access_mode = source["access_mode"]
        automation_level = source["automation_level"]
        probe_url = source.get("probe_url")
        result = {
            "source_id": source["source_id"],
            "jurisdiction": source["jurisdiction"],
            "access_mode": access_mode,
            "automation_level": automation_level,
            "status": "READY" if automation_level != "manual" else "MANUAL_REQUIRED",
        }
        if live and probe_url:
            headers = {"User-Agent": settings.http_user_agent}
            started = perf_counter()
            try:
                response = authoritative_get(
                    str(probe_url),
                    headers=headers,
                    timeout=30,
                    attempts=2,
                )
                result.update(
                    status=("OK" if response.status_code == 200 else "REACHABLE_WITH_RESTRICTIONS"),
                    http_status=response.status_code,
                    latency_ms=round((perf_counter() - started) * 1000),
                )
            except Exception as exc:  # noqa: BLE001 - doctor must report every source
                result.update(
                    status="UNAVAILABLE",
                    detail=f"{type(exc).__name__}: {exc}",
                    latency_ms=round((perf_counter() - started) * 1000),
                )
                failures += 1
        elif live and not probe_url:
            result.update(status="MANIFEST_REQUIRED", detail="该来源必须逐项登记官网或授权材料")
        results.append(result)
    print_json(
        {
            "live": live,
            "jurisdiction": "CN-MAINLAND",
            "results": results,
            "live_failures": failures,
        }
    )
    if strict and failures:
        raise typer.Exit(1)


@source_app.command("demo")
def source_demo(
    database: Path = typer.Option(Path("data/demo/china-mainland-demo.db")),
    object_store: Path = typer.Option(Path("data/demo/china-mainland-objects")),
    report_path: Path = typer.Option(Path("data/demo/china-mainland-demo-report.json")),
) -> None:
    """下载中国大陆官方小样本并跑通解析、抽取和清洗。"""
    database.parent.mkdir(parents=True, exist_ok=True)
    object_store.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(f"sqlite:///{database.resolve().as_posix()}")
    create_schema(engine)
    demo_source_ids = [
        "nmpa_government_service",
        "cninfo_disclosures",
        "cninfo_investor_relations",
        "nhsa_drug_catalog",
        "nhsa_statistics",
    ]
    specs: list[tuple[str, SourceAdapter, dict[str, Any]]] = []
    for source_id in demo_source_ids:
        source = catalog_source(source_id)
        specs.append((source_id, MainlandCatalogAdapter(source), {"max_records": 1}))
    demo_report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "jurisdiction": "CN-MAINLAND",
        "mainland_only": True,
        "database": str(database.resolve()),
        "object_store": str(object_store.resolve()),
        "sources": [],
    }
    for source_name, adapter, query in specs:
        source_result: dict[str, Any] = {"source": source_name, "query": query}
        try:
            with session_scope(engine) as session:
                before_jobs = set(session.scalars(select(ProcessingJob.id)).all())
                report = IngestionService(session, LocalObjectStore(object_store)).ingest(
                    adapter,
                    query,
                    max_pages=1,
                )
                session.flush()
                current_jobs = set(session.scalars(select(ProcessingJob.id)).all())
                pipeline_results = [
                    PipelineRunner(session).run(job_id)
                    for job_id in sorted(current_jobs - before_jobs)
                ]
                source_result.update(
                    status="OK",
                    ingestion=report.__dict__,
                    pipeline=pipeline_results,
                )
        except Exception as exc:  # noqa: BLE001 - demo continues to show partial availability
            source_result.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        demo_report["sources"].append(source_result)
    demo_report["finished_at"] = datetime.now(UTC).isoformat()
    demo_report["successful_sources"] = sum(
        item["status"] == "OK" for item in demo_report["sources"]
    )
    report_path.write_text(
        json.dumps(demo_report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print_json(demo_report)


@source_app.command("sync")
def source_sync(
    source: str,
    record_id: str | None = typer.Option(None, help="只同步目录中的指定样本记录"),
    page_size: int = typer.Option(10, min=1, max=100),
    max_pages: int | None = typer.Option(None, min=1),
    run_pipeline: bool = typer.Option(False, help="同步后立即运行本批次处理任务"),
) -> None:
    try:
        source_config = catalog_source(source)
    except KeyError as exc:
        raise typer.BadParameter(f"未知中国大陆来源: {source}") from exc
    records = list(source_config.get("sample_records", []))
    if record_id:
        records = [item for item in records if item["source_record_id"] == record_id]
    if not records:
        raise typer.BadParameter(
            "该来源没有可自动读取的直连样本；请从官网人工导出后使用 ingest manifest。"
        )
    adapter = MainlandCatalogAdapter(source_config)
    query = {"records": records, "max_records": page_size}

    create_schema()
    with session_scope() as session:
        before_jobs = set(session.scalars(select(ProcessingJob.id)).all())
        report = IngestionService(
            session,
            LocalObjectStore(get_settings().object_store_root),
        ).ingest(adapter, query, max_pages=max_pages)
        session.flush()
        pipeline_results = []
        if run_pipeline:
            current_jobs = set(session.scalars(select(ProcessingJob.id)).all())
            for job_id in sorted(current_jobs - before_jobs):
                pipeline_results.append(PipelineRunner(session).run(job_id))
        print_json({"source": source, "ingestion": report.__dict__, "pipeline": pipeline_results})


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
            component_version="0.2.0-cli",
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
