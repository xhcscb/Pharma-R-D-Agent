import json
from pathlib import Path

from sqlalchemy import select

from pharma_data.contracts import AccessClass, LicenseStatus
from pharma_data.inbox.coordinator import InboxCoordinator
from pharma_data.inbox.metadata import build_candidate
from pharma_data.inbox.service import InboxService
from pharma_data.storage.canonical.models import (
    Document,
    DocumentAccessGrantRecord,
    DocumentVersion,
    ProcessingJob,
    SourceRegistry,
)
from pharma_data.storage.object_store import LocalObjectStore


def test_inbox_metadata_requires_provenance_until_catalog_url_is_verified(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "sources.json"
    catalog.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "cninfo_disclosures",
                        "authority_tier": "A1",
                        "allowed_domains": ["cninfo.com.cn"],
                        "base_url": "https://www.cninfo.com.cn",
                        "terms_url": None,
                        "access_mode": "official_manifest",
                        "redistribution_policy": "metadata_and_derived_only",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "恒瑞医药2026Q1报告.pdf"
    report.write_bytes(b"not-a-real-pdf-but-the-envelope-can-still-be-built")

    unverified = build_candidate(report, source_catalog_path=catalog)
    assert unverified.metadata["document_type"] == "financial_report"
    assert unverified.metadata["report_period"] == "2026-Q1"
    assert unverified.metadata["provenance_status"] == "user_supplied_unverified"
    assert unverified.metadata["metadata_review_required"] is True
    assert unverified.source_profile["authority_tier"] == "B2"

    report.with_name(f"{report.name}.metadata.json").write_text(
        json.dumps(
            {
                "title": "江苏恒瑞医药股份有限公司2026年第一季度报告",
                "source_id": "cninfo_disclosures",
                "canonical_url": "https://static.cninfo.com.cn/finalpage/report.pdf",
                "published_at": "2026-04-22T00:00:00+08:00",
                "stock_code": "600276",
                "license_status": "public_access",
                "access_class": "restricted",
            }
        ),
        encoding="utf-8",
    )
    verified = build_candidate(report, source_catalog_path=catalog)
    assert verified.metadata["provenance_status"] == "catalog_verified"
    assert verified.metadata["metadata_review_required"] is False
    assert verified.source_profile["authority_tier"] == "A1"


def test_inbox_runs_pipeline_archives_and_deduplicates(db_session, tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    metadata = tmp_path / "metadata"
    quarantine = tmp_path / "quarantine"
    inbox.mkdir()
    report = inbox / "恒瑞医药研究报告.txt"
    content = "恒瑞医药开发创新药，相关信息需要人工复核。"
    report.write_text(content, encoding="utf-8")
    catalog = tmp_path / "sources.json"
    service = InboxService(
        inbox_root=inbox,
        archive_root=archive,
        metadata_root=metadata,
        quarantine_root=quarantine,
        source_catalog_path=catalog,
        archive_mode="move",
        settle_seconds=0,
    )

    first = service.run_once(
        db_session,
        LocalObjectStore(tmp_path / "objects"),
        run_pipeline=True,
    )
    assert first["files_seen"] == 1
    assert first["items"][0]["state"] in {"needs_review", "completed"}
    assert first["items"][0]["pipeline_results"][0]["elements"] > 0
    assert not report.exists()
    assert Path(first["items"][0]["archive_path"]).is_file()
    assert Path(first["items"][0]["receipt_path"]).is_file()
    assert Path(first["manifest_path"]).is_file()
    source = db_session.scalar(select(SourceRegistry))
    job = db_session.scalar(select(ProcessingJob))
    assert source is not None and source.authority_tier == "B2"
    assert job is not None and job.status in {"NEEDS_REVIEW", "CLEANED"}

    duplicate = inbox / "同内容研究报告.txt"
    duplicate.write_text(content, encoding="utf-8")
    second = service.run_once(db_session, LocalObjectStore(tmp_path / "objects"))
    assert second["items"][0]["state"] == "duplicate_skipped"
    assert not duplicate.exists()
    assert len(list(archive.rglob("*.txt"))) == 1

    catalog.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "cninfo_disclosures",
                        "authority_tier": "A1",
                        "allowed_domains": ["cninfo.com.cn"],
                        "base_url": "https://www.cninfo.com.cn",
                        "terms_url": None,
                        "access_mode": "official_manifest",
                        "redistribution_policy": "metadata_and_derived_only",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    enriched = inbox / "恒瑞医药研究报告.txt"
    enriched.write_text(content, encoding="utf-8")
    enriched.with_name(f"{enriched.name}.metadata.json").write_text(
        json.dumps(
            {
                "title": "恒瑞医药研究资料",
                "source_id": "cninfo_disclosures",
                "canonical_url": "https://static.cninfo.com.cn/finalpage/report.txt",
                "published_at": "2026-08-23T00:00:00+08:00",
                "license_status": "public_access",
                "access_class": "restricted",
            }
        ),
        encoding="utf-8",
    )
    third = service.run_once(db_session, LocalObjectStore(tmp_path / "objects"))
    assert third["items"][0]["operation"] == "access_grant_added"
    verified_source = db_session.scalar(
        select(SourceRegistry).where(SourceRegistry.name == "cninfo_disclosures")
    )
    version = db_session.scalar(select(DocumentVersion))
    assert verified_source is not None and verified_source.authority_tier == "A1"
    assert version is not None
    assert version.metadata_json["provenance_status"] == "catalog_verified"
    assert version.metadata_json["metadata_review_required"] is False


def test_public_copy_upgrades_one_canonical_document_and_keeps_both_archives(
    db_session,
    tmp_path: Path,
) -> None:
    content = "恒瑞医药2026年报告，数据需要人工复核。"
    catalog = tmp_path / "sources.json"
    object_store = LocalObjectStore(tmp_path / "objects")
    restricted_root = tmp_path / "restricted"
    public_root = tmp_path / "public"
    restricted_root.mkdir()
    public_root.mkdir()
    restricted_report = restricted_root / "恒瑞医药2026年报告.txt"
    restricted_report.write_text(content, encoding="utf-8")

    restricted = InboxService(
        inbox_root=restricted_root,
        archive_root=restricted_root / "_archive",
        metadata_root=restricted_root / "_metadata",
        quarantine_root=restricted_root / "_quarantine",
        source_catalog_path=catalog,
        access_class=AccessClass.RESTRICTED,
        default_license_status=LicenseStatus.AUTHORIZED_RESTRICTED,
        settle_seconds=0,
    )
    restricted_result = restricted.run_once(db_session, object_store)
    restricted_archive = Path(restricted_result["items"][0]["archive_path"])

    public_report = public_root / restricted_report.name
    public_report.write_bytes(restricted_archive.read_bytes())
    public = InboxService(
        inbox_root=public_root,
        archive_root=public_root / "_archive",
        metadata_root=public_root / "_metadata",
        quarantine_root=public_root / "_quarantine",
        source_catalog_path=catalog,
        access_class=AccessClass.PUBLIC,
        default_license_status=LicenseStatus.PUBLIC_ACCESS,
        settle_seconds=0,
    )
    public_result = public.run_once(db_session, object_store)

    version = db_session.scalar(select(DocumentVersion))
    assert version is not None
    assert version.access_class == "public"
    assert version.license_status == "public_access"
    assert version.metadata_json["access_class"] == "public"
    assert db_session.query(Document).count() == 1
    assert restricted_archive.is_file()
    assert Path(public_result["items"][0]["archive_path"]).is_file()
    assert public_result["items"][0]["operation"] == "access_grant_added"
    assert set(db_session.scalars(select(DocumentAccessGrantRecord.access_class))) == {
        "public",
        "restricted",
    }

    status = InboxCoordinator({"public": public, "restricted": restricted}).status()
    assert status["access_classes"] == ["public", "restricted"]
    assert status["receipt_count"] == 2
