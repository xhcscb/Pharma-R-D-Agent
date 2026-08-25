"""Produce a reproducible quality audit for current document versions and parse runs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pharma_data.config import get_settings
from pharma_data.parsers.mineru import mineru_status
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import (
    AssertionEvidenceRecord,
    AssertionRecord,
    CharacterSpanRecord,
    DatasetSnapshotRecord,
    Document,
    DocumentAccessGrantRecord,
    DocumentElementRecord,
    DocumentVersion,
    MetricObservationRecord,
    OutboxEventRecord,
    ParseCandidateRecord,
    ParseReviewItemRecord,
    TableCellRecord,
)

BASELINE = {
    "elements": 14187,
    "titles": 9274,
    "assertions": 255,
    "approx_distinct_fact_keys": 83,
    "approved_assertions": 0,
    "metric_observations": 0,
    "projection_events": 0,
    "dataset_snapshots": 0,
    "evidence_with_character_locator": 0,
}
PROJECTIONS = ("neo4j", "milvus", "timescale", "elasticsearch")


def _scalar(session: Session, statement: Any) -> int:
    return int(session.scalar(statement) or 0)


def _current_versions(session: Session) -> list[DocumentVersion]:
    return list(
        session.scalars(
            select(DocumentVersion)
            .join(Document, Document.current_version_id == DocumentVersion.id)
            .order_by(DocumentVersion.id)
        )
    )


def build_report(session: Session, physical_integrity: str) -> dict[str, Any]:
    versions = _current_versions(session)
    version_ids = [row.id for row in versions]
    active_runs = {row.id: row.active_parse_run_id for row in versions}
    run_ids = [item for item in active_runs.values() if item]

    element_rows = list(
        session.scalars(
            select(DocumentElementRecord).where(
                DocumentElementRecord.document_version_id.in_(version_ids),
                DocumentElementRecord.parse_run_id.in_(run_ids),
            )
        )
    )
    # A run ID belongs to one version; compare explicitly to guard broken references.
    element_rows = [
        row for row in element_rows if active_runs.get(row.document_version_id) == row.parse_run_id
    ]
    element_ids = [row.id for row in element_rows]
    element_types = Counter(row.element_type for row in element_rows)
    parser_names = Counter(row.parser_name for row in element_rows)
    pages_by_version: dict[str, set[int]] = defaultdict(set)
    for row in element_rows:
        if row.page_number is not None:
            pages_by_version[row.document_version_id].add(row.page_number)

    page_details = []
    expected_pages_total = 0
    covered_pages_total = 0
    for version in versions:
        expected = int((version.metadata_json or {}).get("page_count") or 0)
        covered = len(pages_by_version[version.id])
        expected_pages_total += expected
        covered_pages_total += covered
        page_details.append(
            {
                "document_version_id": version.id,
                "expected_pages": expected,
                "covered_pages": covered,
                "coverage": round(covered / expected, 6) if expected else 0.0,
                "active_parse_run_id": version.active_parse_run_id,
                "authoritative_hash_verified": bool(
                    (version.metadata_json or {}).get("authoritative_hash_verified")
                ),
                "metadata_review_required": bool(
                    (version.metadata_json or {}).get("metadata_review_required", True)
                ),
            }
        )

    spans = (
        _scalar(
            session,
            select(func.count()).select_from(CharacterSpanRecord).where(
                CharacterSpanRecord.element_id.in_(element_ids)
            ),
        )
        if element_ids
        else 0
    )
    cells = (
        _scalar(
            session,
            select(func.count()).select_from(TableCellRecord).where(
                TableCellRecord.element_id.in_(element_ids)
            ),
        )
        if element_ids
        else 0
    )
    numeric_cells = (
        _scalar(
            session,
            select(func.count()).select_from(TableCellRecord).where(
                TableCellRecord.element_id.in_(element_ids),
                TableCellRecord.numeric_value.is_not(None),
            ),
        )
        if element_ids
        else 0
    )

    active_evidence = list(
        session.scalars(
            select(AssertionEvidenceRecord).where(
                AssertionEvidenceRecord.element_id.in_(element_ids)
            )
        )
    ) if element_ids else []
    active_assertion_ids = {row.assertion_id for row in active_evidence}
    active_assertions = list(
        session.scalars(
            select(AssertionRecord).where(AssertionRecord.id.in_(active_assertion_ids))
        )
    ) if active_assertion_ids else []
    assertion_key_counts = Counter(row.assertion_key for row in active_assertions)
    duplicate_active_keys = {
        key: count for key, count in assertion_key_counts.items() if count > 1
    }
    assertions_by_fact_group: dict[str, list[AssertionRecord]] = defaultdict(list)
    for row in active_assertions:
        if row.predicate == "REPORTS" and row.fact_group_key:
            assertions_by_fact_group[row.fact_group_key].append(row)
    active_fact_conflicts = {
        fact_group_key: [row.id for row in rows]
        for fact_group_key, rows in assertions_by_fact_group.items()
        if len(
            {
                (
                    str(row.qualifiers.get("normalized_numeric_value") or row.object_value),
                    row.object_unit,
                    row.qualifiers.get("currency"),
                )
                for row in rows
            }
        )
        > 1
    }
    located_evidence = 0
    for row in active_evidence:
        bbox = row.bbox or {}
        try:
            bbox_valid = (
                0 <= float(bbox["x0"]) <= float(bbox["x1"])
                and 0 <= float(bbox["y0"]) <= float(bbox["y1"])
            )
        except (KeyError, TypeError, ValueError):
            bbox_valid = False
        if (
            row.page_number is not None
            and bbox_valid
            and (row.char_span is not None or row.table_cell_id is not None)
            and row.evidence_hash
        ):
            located_evidence += 1

    active_observations = 0
    if active_evidence:
        active_observations = _scalar(
            session,
            select(func.count()).select_from(MetricObservationRecord).where(
                MetricObservationRecord.evidence_id.in_([row.id for row in active_evidence])
            ),
        )

    active_reviews = list(
        session.scalars(
            select(ParseReviewItemRecord).where(
                ParseReviewItemRecord.document_version_id.in_(version_ids),
                ParseReviewItemRecord.parse_run_id.in_(run_ids),
                ParseReviewItemRecord.status == "open",
            )
        )
    )
    active_reviews = [
        row
        for row in active_reviews
        if active_runs.get(row.document_version_id) == row.parse_run_id
    ]
    active_candidates = list(
        session.scalars(
            select(ParseCandidateRecord).where(
                ParseCandidateRecord.document_version_id.in_(version_ids),
                ParseCandidateRecord.parse_run_id.in_(run_ids),
            )
        )
    )
    active_candidates = [
        row
        for row in active_candidates
        if active_runs.get(row.document_version_id) == row.parse_run_id
    ]

    grant_rows = list(
        session.scalars(
            select(DocumentAccessGrantRecord).where(
                DocumentAccessGrantRecord.document_version_id.in_(version_ids),
                DocumentAccessGrantRecord.active.is_(True),
            )
        )
    )
    grants_by_version: dict[str, set[str]] = defaultdict(set)
    for row in grant_rows:
        grants_by_version[row.document_version_id].add(row.access_class)
    dual_authorized = sum(
        {"public", "restricted"}.issubset(grants_by_version[version.id])
        for version in versions
    )

    approved = sum(row.review_status == "approved" for row in active_assertions)
    snapshots = _scalar(session, select(func.count()).select_from(DatasetSnapshotRecord))
    projection_status: dict[str, dict[str, int]] = {}
    for projection in PROJECTIONS:
        projection_status[projection] = {
            "pending": _scalar(
                session,
                select(func.count()).select_from(OutboxEventRecord).where(
                    OutboxEventRecord.projection == projection,
                    OutboxEventRecord.published_at.is_(None),
                ),
            ),
            "published": _scalar(
                session,
                select(func.count()).select_from(OutboxEventRecord).where(
                    OutboxEventRecord.projection == projection,
                    OutboxEventRecord.published_at.is_not(None),
                ),
            ),
        }

    migration_revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    metadata_review_open = sum(item["metadata_review_required"] for item in page_details)
    page_coverage = (
        covered_pages_total / expected_pages_total if expected_pages_total else 0.0
    )
    evidence_locator_completeness = (
        located_evidence / len(active_evidence) if active_evidence else 0.0
    )
    blockers = []
    if physical_integrity.lower() not in {"ok", "not_applicable"}:
        blockers.append("database_physical_integrity_failed")
    if page_coverage != 1.0:
        blockers.append("page_coverage_incomplete")
    if active_reviews:
        blockers.append("parse_hard_gate_review_open")
    if duplicate_active_keys:
        blockers.append("duplicate_active_assertion_keys")
    if active_observations == 0:
        blockers.append("metric_observations_missing")
    if evidence_locator_completeness != 1.0:
        blockers.append("evidence_locator_incomplete")
    if metadata_review_open:
        blockers.append("metadata_review_open")
    if approved == 0:
        blockers.append("approved_claims_missing")
    if active_fact_conflicts:
        blockers.append("active_fact_conflicts_open")
    blockers.extend(("human_gold_missing", "g3_gold_gate_not_evaluated"))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "quality_first_engineering_baseline_internal_trial",
        "formal_research_goal_passed": False,
        "baseline": BASELINE,
        "database": {
            "physical_integrity": physical_integrity,
            "migration_revision": migration_revision,
            "current_document_versions": len(versions),
            "expected_pages": expected_pages_total,
            "covered_pages": covered_pages_total,
            "page_coverage": round(page_coverage, 6),
        },
        "parsing": {
            "active_elements": len(element_rows),
            "element_types": dict(sorted(element_types.items())),
            "parser_names": dict(sorted(parser_names.items())),
            "character_spans": spans,
            "table_cells": cells,
            "numeric_table_cells": numeric_cells,
            "parse_candidates": len(active_candidates),
            "open_hard_gate_reviews": len(active_reviews),
            "documents": page_details,
        },
        "authorization": {
            "active_grants": len(grant_rows),
            "dual_public_restricted_versions": dual_authorized,
            "required_dual_versions": len(versions),
        },
        "facts": {
            "active_assertions": len(active_assertions),
            "active_assertion_keys": len(assertion_key_counts),
            "duplicate_active_assertion_keys": duplicate_active_keys,
            "active_fact_conflict_groups": len(active_fact_conflicts),
            "active_fact_conflicts": active_fact_conflicts,
            "approved_active_assertions": approved,
            "active_evidence": len(active_evidence),
            "evidence_locator_complete": located_evidence,
            "evidence_locator_completeness": round(
                evidence_locator_completeness, 6
            ),
            "metric_observations": active_observations,
        },
        "snapshots": snapshots,
        "projections": projection_status,
        "readiness": {
            "blockers": blockers,
            "engineering_baseline_ready": all(
                blocker
                not in {
                    "database_physical_integrity_failed",
                    "page_coverage_incomplete",
                    "duplicate_active_assertion_keys",
                    "metric_observations_missing",
                    "evidence_locator_incomplete",
                    "metadata_review_open",
                }
                for blocker in blockers
            ),
            "formal_reasoning_ready": not blockers,
            "gold_character_error_rate": None,
            "gold_teds": None,
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    database = report["database"]
    parsing = report["parsing"]
    facts = report["facts"]
    readiness = report["readiness"]
    duplicate_keys = len(facts["duplicate_active_assertion_keys"])
    lines = [
        "# 数据层质量改造报告",
        "",
        f"生成时间：`{report['generated_at']}`",
        "",
        "## 结论",
        "",
        "当前结论为 **质量优先工程基线 / 内部试运行**。正式研究目标仍未通过；"
        "人工 Gold、G3 指标和主张审批不得由自动检查替代。",
        "",
        "## 当前活动数据",
        "",
        "- 数据库完整性："
        f"`{database['physical_integrity']}`；迁移：`{database['migration_revision']}`",
        f"- 文档：{database['current_document_versions']}；页面："
        f"{database['covered_pages']}/{database['expected_pages']} "
        f"({database['page_coverage']:.2%})",
        f"- 元素：{parsing['active_elements']}；字符 span："
        f"{parsing['character_spans']}；表格单元格：{parsing['table_cells']}"
        f"（数字 {parsing['numeric_table_cells']}）",
        f"- 活动主张：{facts['active_assertions']}；活动事实键："
        f"{facts['active_assertion_keys']}；重复键：{duplicate_keys}",
        f"- 活动事实冲突组：{facts['active_fact_conflict_groups']}",
        f"- 指标观测：{facts['metric_observations']}；活动证据："
        f"{facts['active_evidence']}；定位完整率："
        f"{facts['evidence_locator_completeness']:.2%}",
        f"- 已批准主张：{facts['approved_active_assertions']}；开放解析硬门："
        f"{parsing['open_hard_gate_reviews']}；快照：{report['snapshots']}",
        f"- MinerU GPU：{report['mineru_gpu'].get('status')}；设备："
        f"{report['mineru_gpu'].get('device_name')}；累计服务失败："
        f"{report['mineru_gpu'].get('failed_tasks')}",
        f"- 投影 ID 验收：{report.get('projection_id_audit', {}).get('status', 'not_run')}",
        "",
        "## 正式目标阻断项",
        "",
    ]
    lines.extend(f"- `{item}`" for item in readiness["blockers"])
    lines.extend(
        [
            "",
            "## 改造前基线",
            "",
            "```json",
            json.dumps(report["baseline"], ensure_ascii=False, indent=2),
            "```",
            "",
            "完整机器可读结果见同名 JSON。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("output/data_layer_quality_20260824.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("docs/data_layer/quality_report_20260824.md"),
    )
    args = parser.parse_args()
    engine = get_engine()
    physical_integrity = "not_applicable"
    if engine.url.get_backend_name() == "sqlite":
        with engine.connect() as connection:
            physical_integrity = str(connection.execute(text("PRAGMA integrity_check")).scalar())
    with Session(engine) as session:
        report = build_report(session, physical_integrity)
    report["mineru_gpu"] = mineru_status(get_settings())
    projection_audit_path = Path("output/projection_id_audit_20260824.json")
    if projection_audit_path.is_file():
        report["projection_id_audit"] = json.loads(
            projection_audit_path.read_text(encoding="utf-8")
        )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
