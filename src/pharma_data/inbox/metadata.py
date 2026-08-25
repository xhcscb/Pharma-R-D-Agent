import json
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pharma_data.contracts import AccessClass, DocumentType, LicenseStatus
from pharma_data.utils.hashing import sha256_file

SUPPORTED_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
    ".xbrl": "application/xbrl+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}

DOCUMENT_PATTERNS: tuple[tuple[DocumentType, str, re.Pattern[str]], ...] = (
    (
        DocumentType.FINANCIAL_REPORT,
        "法定财务报告关键词",
        re.compile(r"年度报告|年报|半年度报告|半年报|季度报告|季报|Q[1-4]报告", re.I),
    ),
    (
        DocumentType.RESEARCH_REPORT,
        "研究报告关键词",
        re.compile(r"券商研报|研究报告|行业报告|深度报告|公司报告|研报"),
    ),
    (
        DocumentType.CLINICAL_DOCUMENT,
        "临床资料关键词",
        re.compile(r"临床试验|临床研究|试验方案|研究方案|CTR\d+", re.I),
    ),
    (
        DocumentType.REGULATORY,
        "监管资料关键词",
        re.compile(r"审评报告|批准证明|注册批件|药监|NMPA|CDE", re.I),
    ),
    (
        DocumentType.EARNINGS_CALL,
        "投资者交流关键词",
        re.compile(r"业绩说明会|投资者关系|调研纪要|路演|电话会议"),
    ),
    (
        DocumentType.MARKET_DATA,
        "行情数据关键词",
        re.compile(r"行情|股价|成交量|market[_ -]?data|price", re.I),
    ),
    (DocumentType.NEWS, "新闻关键词", re.compile(r"新闻|公告|快讯")),
)


@dataclass(frozen=True)
class InboxCandidate:
    path: Path
    sidecar_path: Path | None
    content_hash: str
    media_type: str
    metadata: dict[str, Any]
    source_profile: dict[str, Any]


def build_candidate(
    path: Path,
    *,
    source_catalog_path: Path,
    folder_access_class: AccessClass = AccessClass.RESTRICTED,
    default_license_status: LicenseStatus = LicenseStatus.AUTHORIZED_RESTRICTED,
) -> InboxCandidate:
    suffix = path.suffix.lower()
    media_type = SUPPORTED_MEDIA_TYPES.get(suffix)
    if media_type is None:
        guessed = mimetypes.guess_type(path.name)[0]
        raise ValueError(f"Unsupported inbox file type: {suffix or guessed or 'unknown'}")
    sidecar_path, sidecar = _load_sidecar(path)
    content_hash = sha256_file(path)
    extracted = _extract_file_metadata(path, media_type)
    searchable_text = " ".join(
        [path.stem, str(extracted.get("sample_text") or ""), str(sidecar.get("title") or "")]
    )
    document_type, classification_reason, confidence = _classify(searchable_text, suffix)
    if sidecar.get("document_type"):
        document_type = DocumentType(str(sidecar["document_type"]))
        classification_reason = "用户侧车 metadata 明确指定"
        confidence = 1.0

    source_profile = _resolve_source_profile(sidecar, source_catalog_path)
    identity = _extract_identity(searchable_text, path.stem)
    title = str(sidecar.get("title") or extracted.get("pdf_title") or identity["title"])
    published_at = _iso_datetime(sidecar.get("published_at"))
    license_status = LicenseStatus(
        str(sidecar.get("license_status") or default_license_status.value)
    )
    requested_access = AccessClass(
        str(sidecar.get("access_class") or folder_access_class.value)
    )
    if requested_access != folder_access_class:
        raise ValueError(
            f"Folder enforces access_class={folder_access_class.value}; "
            f"sidecar requested {requested_access.value}"
        )
    access_class = folder_access_class
    if license_status not in {LicenseStatus.PUBLIC, LicenseStatus.PUBLIC_ACCESS}:
        if access_class == AccessClass.PUBLIC:
            raise ValueError("Non-public inbox content cannot use public access_class")

    metadata: dict[str, Any] = {
        "schema_version": "1.0",
        "metadata_origin": "auto_generated_with_optional_sidecar",
        "metadata_generated_at": datetime.now(UTC).isoformat(),
        "original_filename": path.name,
        "media_type": media_type,
        "content_hash": content_hash,
        "size_bytes": path.stat().st_size,
        "title": title,
        "document_type": document_type.value,
        "classification_reason": classification_reason,
        "classification_confidence": confidence,
        "issuer": sidecar.get("issuer") or identity.get("issuer"),
        "stock_code": sidecar.get("stock_code") or identity.get("stock_code"),
        "report_period": sidecar.get("report_period") or identity.get("report_period"),
        "language": sidecar.get("language") or "zh-CN",
        "published_at": published_at.isoformat() if published_at else None,
        "canonical_url": sidecar.get("canonical_url"),
        "source_id": source_profile["source_id"],
        "source_name": source_profile["source_name"],
        "authority_tier": source_profile["authority_tier"],
        "provenance_status": source_profile["provenance_status"],
        "redistribution_policy": source_profile.get("redistribution_policy"),
        "license_status": license_status.value,
        "access_class": access_class.value,
        "metadata_review_required": True,
        "sidecar_path": str(sidecar_path) if sidecar_path else None,
        "user_metadata": sidecar,
        **{key: value for key, value in extracted.items() if key != "sample_text"},
    }
    required_fields = ["published_at"]
    if not metadata.get("canonical_url") and not sidecar.get("authorization_reference"):
        required_fields.append("canonical_url_or_authorization_reference")
    if document_type == DocumentType.FINANCIAL_REPORT:
        required_fields.extend(["issuer", "stock_code", "report_period"])
    metadata["missing_formal_fields"] = [
        field for field in required_fields if not metadata.get(field)
    ]
    metadata["metadata_review_required"] = (
        source_profile["provenance_status"] != "catalog_verified"
        or bool(metadata["missing_formal_fields"])
    )
    return InboxCandidate(
        path=path,
        sidecar_path=sidecar_path,
        content_hash=content_hash,
        media_type=media_type,
        metadata=metadata,
        source_profile=source_profile,
    )


def is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_MEDIA_TYPES


def _load_sidecar(path: Path) -> tuple[Path | None, dict[str, Any]]:
    candidates = [path.with_name(f"{path.name}.metadata.json"), path.with_suffix(".metadata.json")]
    existing = [item for item in candidates if item.is_file()]
    if len(existing) > 1:
        raise ValueError(f"Multiple metadata sidecars found for {path.name}")
    if not existing:
        return None, {}
    payload = json.loads(existing[0].read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Inbox metadata sidecar must contain a JSON object")
    return existing[0], dict(payload)


def _extract_file_metadata(path: Path, media_type: str) -> dict[str, Any]:
    if media_type != "application/pdf":
        return {}
    try:
        import fitz
    except ImportError:
        return {"metadata_warning": "pymupdf is unavailable; PDF metadata was not inspected"}
    try:
        with fitz.open(path) as pdf:
            sample_text = "\n".join(
                pdf.load_page(index).get_text("text") for index in range(min(len(pdf), 12))
            )[:180_000]
            pdf_metadata = {
                key: value
                for key, value in (pdf.metadata or {}).items()
                if value and key in {"title", "author", "subject", "keywords", "creationDate"}
            }
            return {
                "page_count": len(pdf),
                "pdf_title": pdf_metadata.get("title"),
                "pdf_metadata": pdf_metadata,
                "native_text_sample_characters": len(sample_text),
                "sample_text": sample_text,
                "pdf_encrypted": bool(pdf.needs_pass),
            }
    except Exception as exc:
        return {"metadata_warning": f"PDF metadata inspection failed: {type(exc).__name__}: {exc}"}


def _classify(text: str, suffix: str) -> tuple[DocumentType, str, float]:
    for document_type, reason, pattern in DOCUMENT_PATTERNS:
        if pattern.search(text):
            return document_type, reason, 0.95
    if suffix in {".csv", ".xlsx"}:
        return DocumentType.OTHER, "结构化文件但业务类型不明确", 0.45
    return DocumentType.OTHER, "未命中业务类型规则", 0.35


def _extract_identity(text: str, stem: str) -> dict[str, str | None]:
    compact = re.sub(r"\s+", " ", text)
    issuer_match = re.search(
        r"([\u4e00-\u9fff（）()·]{4,45}?(?:股份有限公司|有限责任公司))\s*20\d{2}",
        compact,
    )
    issuer = issuer_match.group(1).strip("：: ") if issuer_match else None
    stock_match = re.search(
        r"(?:公司代码|证券代码|股票代码)\s*[：:]?\s*(\d{6})|股票简称\s+\S+\s+股票代码\s+(\d{6})",
        compact,
    )
    stock_code = (
        next((item for item in stock_match.groups() if item), None) if stock_match else None
    )
    period_match = re.search(
        r"(20\d{2})\s*年?\s*(第一季度|一季度|Q1|半年度|半年|中期|第三季度|三季度|Q3|年度|年报)",
        compact,
        re.I,
    )
    period = None
    period_label = None
    report_year = None
    if period_match:
        year, raw_period = period_match.groups()
        report_year = year
        normalized = raw_period.upper()
        suffix = (
            "Q1"
            if normalized in {"第一季度", "一季度", "Q1"}
            else "H1"
            if normalized in {"半年度", "半年", "中期"}
            else "Q3"
            if normalized in {"第三季度", "三季度", "Q3"}
            else "FY"
        )
        period = f"{year}-{suffix}"
        period_label = {
            "Q1": "第一季度报告",
            "H1": "半年度报告",
            "Q3": "第三季度报告",
            "FY": "年度报告",
        }[suffix]
    title = (
        f"{issuer} {report_year}年{period_label}"
        if issuer and report_year and period_label
        else stem
    )
    return {
        "title": title,
        "issuer": issuer,
        "stock_code": stock_code,
        "report_period": period,
    }


def _resolve_source_profile(
    sidecar: dict[str, Any], source_catalog_path: Path
) -> dict[str, Any]:
    source_id = str(sidecar.get("source_id") or "local_inbox_unverified")
    fallback = {
        "source_id": source_id,
        "source_name": source_id,
        "authority_tier": "B2",
        "base_url": None,
        "terms_url": None,
        "redistribution_policy": "restricted_internal_only",
        "provenance_status": "user_supplied_unverified",
    }
    if source_id == "local_inbox_unverified" or not source_catalog_path.is_file():
        return fallback
    payload = json.loads(source_catalog_path.read_text(encoding="utf-8"))
    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    catalog = next(
        (item for item in sources if isinstance(item, dict) and item.get("source_id") == source_id),
        None,
    )
    if catalog is None:
        return {**fallback, "provenance_status": "unknown_source_id"}
    canonical_url = str(sidecar.get("canonical_url") or "")
    allowed_domains = [str(item).lower() for item in catalog.get("allowed_domains", [])]
    hostname = (urlparse(canonical_url).hostname or "").lower()
    domain_verified = bool(hostname) and any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains
    )
    authorization_verified = bool(sidecar.get("authorization_reference")) and catalog.get(
        "access_mode"
    ) in {"authorized_manifest", "official_manifest"}
    if not (domain_verified or authorization_verified):
        return {
            **fallback,
            "source_name": source_id,
            "base_url": catalog.get("base_url"),
            "terms_url": catalog.get("terms_url"),
            "redistribution_policy": catalog.get("redistribution_policy"),
            "provenance_status": "catalog_declared_unverified",
        }
    return {
        "source_id": source_id,
        "source_name": source_id,
        "authority_tier": str(catalog.get("authority_tier") or "B2"),
        "base_url": catalog.get("base_url"),
        "terms_url": catalog.get("terms_url"),
        "redistribution_policy": catalog.get("redistribution_policy"),
        "provenance_status": "catalog_verified",
    }


def _iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
