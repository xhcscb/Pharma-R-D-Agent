from __future__ import annotations

import base64
import binascii
import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from pharma_data.config import Settings, get_settings
from pharma_data.contracts import (
    BoundingBox,
    CharacterSpan,
    DocumentType,
    ElementType,
    ParsedDocument,
    TableCell,
)
from pharma_data.parsers.base import Parser
from pharma_data.parsers.common import make_element
from pharma_data.parsers.visual_semantics import visual_asset_metadata
from pharma_data.utils.hashing import sha256_file, stable_hash

NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![\w.])")


class MineruServiceError(RuntimeError):
    pass


class MineruClient:
    """Security-constrained client for a self-hosted MinerU `/file_parse` API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.mineru_api_url.rstrip("/")
        self._validate_endpoint()

    def _validate_endpoint(self) -> None:
        parsed = urlparse(self.base_url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or not host:
            raise MineruServiceError("MINERU_API_URL must be an absolute HTTP(S) URL")
        if host not in self.settings.mineru_trusted_host_set():
            raise MineruServiceError(
                f"MinerU host {host!r} is not present in MINERU_TRUSTED_HOSTS"
            )
        if self.settings.mineru_execution_mode == "local":
            if host not in {"127.0.0.1", "localhost", "::1"}:
                raise MineruServiceError("Local MinerU mode may only call a loopback endpoint")
        elif parsed.scheme != "https":
            raise MineruServiceError("Remote MinerU endpoints require TLS (https)")
        elif not self.settings.mineru_api_key:
            raise MineruServiceError("Remote MinerU endpoints require MINERU_API_KEY")

    def _headers(self) -> dict[str, str]:
        return (
            {"Authorization": f"Bearer {self.settings.mineru_api_key}"}
            if self.settings.mineru_api_key
            else {}
        )

    def health(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "endpoint": self.base_url,
            "node_id": self.settings.mineru_node_id,
            "backend": self.settings.mineru_backend,
            "execution_mode": self.settings.mineru_execution_mode,
            "service_reachable": False,
            "gpu_verified": False,
        }
        try:
            with httpx.Client(timeout=5.0, headers=self._headers()) as client:
                gpu_response = client.get(f"{self.base_url}/gpu-health")
                if gpu_response.status_code == 200:
                    payload = gpu_response.json()
                    result.update(payload if isinstance(payload, dict) else {})
                    result["service_reachable"] = True
                    result["gpu_verified"] = bool(
                        result.get("cuda_available") and result.get("device_name")
                    )
                health_response = client.get(f"{self.base_url}/health")
                if health_response.status_code == 200:
                    result["service_reachable"] = True
                    service_health = health_response.json()
                    result["service_health"] = service_health
                    if isinstance(service_health, dict):
                        for key in (
                            "queued_tasks",
                            "processing_tasks",
                            "completed_tasks",
                            "failed_tasks",
                            "max_concurrent_requests",
                        ):
                            if key in service_health:
                                result[key] = service_health[key]
                else:
                    schema = client.get(f"{self.base_url}/openapi.json")
                    result["service_reachable"] = schema.status_code == 200
        except Exception as exc:  # health endpoints must never crash the application
            result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    def parse(
        self,
        path: Path,
        *,
        start_page_id: int = 0,
        end_page_id: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        health = self.health()
        if not health.get("service_reachable"):
            raise MineruServiceError(f"MinerU is unavailable: {health.get('error', health)}")
        if self.settings.mineru_device.casefold().startswith("cuda") and not health.get(
            "gpu_verified"
        ):
            raise MineruServiceError(
                "MinerU service is reachable but CUDA identity was not verified at /gpu-health"
            )
        form: dict[str, str] = {
            "lang_list": "ch",
            "backend": self.settings.mineru_backend,
            "parse_method": "auto",
            "formula_enable": "true",
            "table_enable": "true",
            "image_analysis": "true",
            "return_md": "true",
            "return_middle_json": "true",
            "return_model_output": "true",
            "return_content_list": "true",
            "return_images": str(self.settings.mineru_return_images).lower(),
            "response_format_zip": "false",
            "return_original_file": "false",
            "start_page_id": str(start_page_id),
            "end_page_id": str(end_page_id if end_page_id is not None else 99999),
        }
        if self.settings.mineru_server_url:
            form["server_url"] = self.settings.mineru_server_url
        with path.open("rb") as stream, httpx.Client(
            timeout=self.settings.mineru_timeout_seconds,
            headers=self._headers(),
        ) as client:
            response = client.post(
                f"{self.base_url}/file_parse",
                data=form,
                files={"files": (path.name, stream, "application/pdf")},
            )
        if response.status_code >= 400:
            detail = response.text[:2000]
            raise MineruServiceError(
                f"MinerU returned HTTP {response.status_code}: {detail}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MineruServiceError("MinerU returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise MineruServiceError("MinerU response root must be an object")
        output_hash = stable_hash(payload)
        output_dir = (
            self.settings.mineru_raw_output_root
            / sha256_file(path)
            / output_hash
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        visual_assets = _persist_response_images(
            payload,
            output_dir / "images",
            max_image_bytes=self.settings.mineru_max_image_bytes,
        )
        output_path = output_dir / "response.json"
        if not output_path.exists():
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        audit = {
            "backend_name": "mineru",
            "backend_version": payload.get("version") or health.get("mineru_version"),
            "node_id": self.settings.mineru_node_id,
            "endpoint": self.base_url,
            "selected": True,
            "status": "selected",
            "parameters": {key: value for key, value in form.items() if "key" not in key},
            "raw_output_path": str(output_path.resolve()),
            "raw_output_hash": output_hash,
            "visual_assets": visual_assets,
            "health": health,
        }
        return payload, audit


class MineruPdfParser(Parser):
    name = "mineru"
    version = "3.x-content-list"
    media_types = {"application/pdf"}

    def __init__(self, client: MineruClient | None = None) -> None:
        self.client = client or MineruClient()

    def parse(
        self,
        path: Path,
        *,
        document_id: str,
        document_version_id: str,
        document_type: DocumentType,
        artifact_id: str,
    ) -> ParsedDocument:
        page_count = _pdf_page_count(path)
        batch_size = self.client.settings.mineru_page_batch_size
        elements: list[Any] = []
        audits: list[dict[str, Any]] = []
        for start_page_id in range(0, page_count, batch_size):
            end_page_id = min(start_page_id + batch_size - 1, page_count - 1)
            payload, audit = self.client.parse(
                path,
                start_page_id=start_page_id,
                end_page_id=end_page_id,
            )
            audit["pages"] = list(range(start_page_id + 1, end_page_id + 2))
            audit["region_key"] = f"pages:{start_page_id + 1}-{end_page_id + 1}"
            audits.append(audit)
            content_list, middle = _response_outputs(payload, path.stem)
            elements.extend(
                _decode_content_list(
                    content_list,
                    middle,
                    path,
                    document_version_id=document_version_id,
                    parser_version=str(audit.get("backend_version") or self.version),
                    page_offset=start_page_id,
                    reading_order_offset=len(elements),
                    visual_assets=audit.get("visual_assets") or {},
                )
            )
        return ParsedDocument(
            document_id=document_id,
            document_version_id=document_version_id,
            document_type=document_type,
            metadata={
                "artifact_id": artifact_id,
                "page_count": page_count,
                "parser_candidate": self.name,
                "parse_candidates": audits,
                "mineru": {
                    "backend_name": "mineru",
                    "node_id": self.client.settings.mineru_node_id,
                    "backend": self.client.settings.mineru_backend,
                    "page_batch_size": batch_size,
                    "batch_count": len(audits),
                    "raw_output_hashes": [item["raw_output_hash"] for item in audits],
                },
            },
            elements=elements,
            parse_quality={
                "page_count": float(page_count),
                "element_count": float(len(elements)),
            },
        )


def apply_pdf_quality_gates(
    parsed: ParsedDocument,
    native: ParsedDocument,
    path: Path,
) -> ParsedDocument:
    """Apply hard page/region checks and expose every failure for review."""
    page_count = int(native.metadata.get("page_count") or _pdf_page_count(path))
    by_page: dict[int, list[Any]] = {page: [] for page in range(1, page_count + 1)}
    for element in parsed.elements:
        if element.page_number in by_page:
            by_page[element.page_number].append(element)
    native_by_page: dict[int, list[Any]] = {page: [] for page in range(1, page_count + 1)}
    for element in native.elements:
        if element.page_number in native_by_page:
            native_by_page[element.page_number].append(element)

    dimensions = _pdf_page_dimensions(path)
    diagnostics: list[dict[str, Any]] = []
    failed_pages: list[int] = []
    total_native_numbers = 0
    matched_native_numbers = 0
    globally_ordered = sorted(parsed.elements, key=lambda item: item.reading_order)
    invalid_sequence_pages: set[int] = set()
    for previous, current in zip(globally_ordered, globally_ordered[1:], strict=False):
        if (
            previous.page_number is not None
            and current.page_number is not None
            and current.page_number < previous.page_number
        ):
            invalid_sequence_pages.update((previous.page_number, current.page_number))
    for page_number in range(1, page_count + 1):
        failures: list[str] = []
        page_elements = by_page[page_number]
        if not page_elements:
            failures.append("page_coverage")
        width, height = dimensions[page_number]
        if any(item.bbox is None for item in page_elements):
            failures.append("bbox_missing")
        if any(not _bbox_in_bounds(item.bbox, width, height) for item in page_elements):
            failures.append("bbox_out_of_bounds")
        page_orders = [item.reading_order for item in page_elements]
        if (
            len(page_orders) != len(set(page_orders))
            or page_orders != sorted(page_orders)
            or page_number in invalid_sequence_pages
        ):
            failures.append("reading_order_invalid")
        if _has_duplicate_table_region(page_elements):
            failures.append("duplicate_region")

        native_numbers = Counter(
            _number_tokens(
                "\n".join(
                    item.text
                    for item in native_by_page[page_number]
                    if item.element_type not in {ElementType.HEADER, ElementType.FOOTER}
                )
            )
        )
        parsed_numbers = Counter(
            _number_tokens(
                "\n".join(
                    item.text
                    for item in page_elements
                    if item.element_type not in {ElementType.HEADER, ElementType.FOOTER}
                )
            )
        )
        total_native_numbers += sum(native_numbers.values())
        matched_native_numbers += sum((native_numbers & parsed_numbers).values())
        missing = native_numbers - parsed_numbers
        added = parsed_numbers - native_numbers
        if missing:
            failures.append("numeric_tokens_missing")
        if added:
            failures.append("numeric_tokens_added")
        if any(
            item.element_type == ElementType.TABLE and not _valid_table_cells(item.table_cells)
            for item in page_elements
        ):
            failures.append("table_grid_invalid")
        if failures:
            failed_pages.append(page_number)
        diagnostics.append(
            {
                "page_number": page_number,
                "passed": not failures,
                "failures": failures,
                "native_number_count": sum(native_numbers.values()),
                "parsed_number_count": sum(parsed_numbers.values()),
                "missing_number_count": sum(missing.values()),
                "added_number_count": sum(added.values()),
                "missing_number_sample": list(missing.elements())[:20],
                "added_number_sample": list(added.elements())[:20],
                "element_count": len(page_elements),
            }
        )
    warnings = [
        warning
        for warning in parsed.warnings
        if not warning.startswith("Hard quality gates failed on ")
    ]
    if failed_pages:
        warnings.append(
            f"Hard quality gates failed on {len(failed_pages)}/{page_count} pages; review required"
        )
    return parsed.model_copy(
        update={
            "metadata": {
                **parsed.metadata,
                "page_quality": diagnostics,
                "failed_pages": failed_pages,
                "formal_reasoning_eligible": not failed_pages,
            },
            "parse_quality": {
                **parsed.parse_quality,
                "page_coverage": (page_count - len([p for p in failed_pages if not by_page[p]]))
                / max(page_count, 1),
                "hard_gate_pass_rate": (page_count - len(failed_pages)) / max(page_count, 1),
                "numeric_token_recall": matched_native_numbers
                / max(total_native_numbers, 1),
                "failed_page_count": float(len(failed_pages)),
            },
            "warnings": warnings,
        }
    )


def _response_outputs(
    payload: dict[str, Any], stem: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, dict) or not results:
        raise MineruServiceError("MinerU response has no results")
    item = results.get(stem) or next(iter(results.values()))
    if not isinstance(item, dict):
        raise MineruServiceError("MinerU result entry must be an object")
    content = _decode_json_field(item.get("content_list"))
    middle = _decode_json_field(item.get("middle_json"))
    if not isinstance(content, list):
        raise MineruServiceError("MinerU content_list output is missing or malformed")
    return [row for row in content if isinstance(row, dict)], (
        middle if isinstance(middle, dict) else {}
    )


def _decode_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _decode_content_list(
    content: list[dict[str, Any]],
    middle: dict[str, Any],
    path: Path,
    *,
    document_version_id: str,
    parser_version: str,
    page_offset: int = 0,
    reading_order_offset: int = 0,
    visual_assets: dict[str, dict[str, Any]] | None = None,
) -> list[Any]:
    dimensions = _pdf_page_dimensions(path)
    local_dimensions = {
        local_page: dimensions[local_page + page_offset]
        for local_page in range(1, len(dimensions) - page_offset + 1)
        if local_page + page_offset in dimensions
    }
    span_index = _middle_span_index(middle, local_dimensions)
    elements = []
    for order, item in enumerate(content):
        local_page_number = int(item.get("page_idx", 0)) + 1
        page_number = local_page_number + page_offset
        if page_number not in dimensions:
            continue
        kind = str(item.get("type") or "text").casefold()
        element_type = {
            "table": ElementType.TABLE,
            "chart": ElementType.CHART,
            "image": ElementType.FIGURE,
            "equation": ElementType.FORMULA,
            "code": ElementType.PARAGRAPH,
            "page_footnote": ElementType.FOOTNOTE,
            "footer": ElementType.FOOTER,
            "header": ElementType.HEADER,
        }.get(kind, ElementType.TITLE if item.get("text_level") else ElementType.PARAGRAPH)
        text = _content_text(item)
        bbox = _normalized_bbox(item.get("bbox"), dimensions[page_number])
        cells = _html_table_cells(str(item.get("table_body") or ""), bbox)
        image_ref = str(item.get("img_path") or item.get("image_path") or "").strip()
        visual_asset = (visual_assets or {}).get(Path(image_ref).name) if image_ref else None
        character_spans = span_index.get((local_page_number, text), [])
        if not character_spans and text:
            character_spans = [
                CharacterSpan(
                    char_start=0,
                    char_end=len(text),
                    text=text,
                    bbox=bbox,
                    confidence=0.9,
                )
            ]
        elements.append(
            make_element(
                document_version_id=document_version_id,
                element_type=element_type,
                reading_order=reading_order_offset + order,
                text=text,
                parser_name="mineru",
                parser_version=parser_version,
                page_number=page_number,
                bbox=bbox,
                structured_payload={
                    "mineru_content": {
                        **item,
                        "source_page_number": page_number,
                        "visual_asset": visual_asset,
                    }
                },
                confidence=float(item.get("score") or 0.9),
            ).model_copy(
                update={"character_spans": character_spans, "table_cells": cells}
            )
        )
    return elements


def _persist_response_images(
    payload: dict[str, Any],
    output_dir: Path,
    *,
    max_image_bytes: int,
) -> dict[str, dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, dict):
        return {}
    assets: dict[str, dict[str, Any]] = {}
    for result in results.values():
        if not isinstance(result, dict) or not isinstance(result.get("images"), dict):
            continue
        for raw_name, data_url in result["images"].items():
            name = Path(str(raw_name)).name
            if not name or name in {".", ".."} or not isinstance(data_url, str):
                continue
            match = re.fullmatch(r"data:(image/[-+.\w]+);base64,(.+)", data_url, re.S)
            if not match:
                continue
            encoded = match.group(2)
            if len(encoded) > (max_image_bytes * 4 // 3) + 16:
                raise MineruServiceError(f"MinerU image {name!r} exceeds configured size limit")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise MineruServiceError(f"MinerU image {name!r} has invalid base64") from exc
            if len(content) > max_image_bytes:
                raise MineruServiceError(f"MinerU image {name!r} exceeds configured size limit")
            suffix = Path(name).suffix.casefold()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
                continue
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / name
            if path.exists() and path.read_bytes() != content:
                raise MineruServiceError(f"MinerU returned conflicting image payloads for {name!r}")
            if not path.exists():
                path.write_bytes(content)
            try:
                asset = visual_asset_metadata(path, source_ref=f"images/{name}")
            except Exception as exc:
                raise MineruServiceError(
                    f"MinerU image {name!r} is not a valid raster image"
                ) from exc
            asset["response_mime_type"] = match.group(1)
            assets[name] = asset
    return assets


def _content_text(item: dict[str, Any]) -> str:
    kind = str(item.get("type") or "")
    if kind == "table":
        return _strip_html(str(item.get("table_body") or ""))
    if kind in {"image", "chart"}:
        values = [
            *(item.get("image_caption") or item.get("chart_caption") or []),
            *(item.get("image_footnote") or item.get("chart_footnote") or []),
        ]
        return "\n".join(str(value) for value in values if value)
    if kind == "list":
        return "\n".join(str(value) for value in item.get("list_items", []) if value)
    return str(item.get("text") or item.get("code_body") or item.get("content") or "").strip()


class _TableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            values = dict(attrs)
            self._cell = {
                "text": "",
                "row_span": max(int(values.get("rowspan") or 1), 1),
                "column_span": max(int(values.get("colspan") or 1), 1),
                "header": tag == "th",
            }

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._cell["text"] = " ".join(self._cell["text"].split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _html_table_cells(html: str, table_bbox: BoundingBox | None) -> list[TableCell]:
    if not html:
        return []
    parser = _TableHtmlParser()
    try:
        parser.feed(html)
    except (ValueError, TypeError):
        return []
    occupied: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    headers: dict[int, str] = {}
    for row_index, row in enumerate(parser.rows):
        column_index = 0
        for raw in row:
            while (row_index, column_index) in occupied:
                column_index += 1
            row_span = int(raw["row_span"])
            column_span = int(raw["column_span"])
            for rr in range(row_index, row_index + row_span):
                for cc in range(column_index, column_index + column_span):
                    occupied.add((rr, cc))
            value = str(raw["text"])
            if raw["header"] or row_index == 0:
                for cc in range(column_index, column_index + column_span):
                    headers[cc] = value
            numeric, unit = _numeric_value(value)
            cells.append(
                TableCell(
                    row_index=row_index,
                    column_index=column_index,
                    row_span=row_span,
                    column_span=column_span,
                    text=value,
                    bbox=table_bbox,
                    header_path=[headers[column_index]]
                    if column_index in headers and row_index > 0
                    else [],
                    normalized_value=value.strip() or None,
                    numeric_value=numeric,
                    unit=unit,
                    confidence=0.9,
                )
            )
            column_index += column_span
    return cells


def _numeric_value(value: str) -> tuple[str | None, str | None]:
    match = NUMBER_RE.fullmatch(value.strip())
    if not match:
        return None, None
    raw = match.group(0)
    unit = "%" if raw.endswith("%") else None
    try:
        normalized = str(Decimal(raw.rstrip("%").replace(",", "")))
    except InvalidOperation:
        return None, unit
    return normalized, unit


def _middle_span_index(
    middle: dict[str, Any], dimensions: dict[int, tuple[float, float]]
) -> dict[tuple[int, str], list[CharacterSpan]]:
    result: dict[tuple[int, str], list[CharacterSpan]] = {}
    pages = middle.get("pdf_info") if isinstance(middle, dict) else None
    if not isinstance(pages, list):
        return result
    for page_pos, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page_pos not in dimensions:
            continue
        for block in page.get("para_blocks", []):
            if not isinstance(block, dict):
                continue
            values: list[tuple[str, Any, float]] = []
            _collect_middle_spans(block, values)
            text = "".join(item[0] for item in values).strip()
            if not text:
                continue
            offset = 0
            spans = []
            for span_text, span_bbox, score in values:
                start = offset
                offset += len(span_text)
                spans.append(
                    CharacterSpan(
                        char_start=start,
                        char_end=offset,
                        text=span_text,
                        bbox=_absolute_bbox(span_bbox),
                        confidence=score,
                    )
                )
            result[(page_pos, text)] = spans
    return result


def _collect_middle_spans(
    value: Any, target: list[tuple[str, Any, float]]
) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("content"), str) and value.get("type") in {
            "text",
            "inline_equation",
            "interline_equation",
        }:
            target.append(
                (
                    value["content"],
                    value.get("bbox"),
                    float(value.get("score") or 0.9),
                )
            )
        for key in ("blocks", "lines", "spans"):
            _collect_middle_spans(value.get(key), target)
    elif isinstance(value, list):
        for item in value:
            _collect_middle_spans(item, target)


def _pdf_page_count(path: Path) -> int:
    return len(_pdf_page_dimensions(path))


def _pdf_page_dimensions(path: Path) -> dict[int, tuple[float, float]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("MinerU verification requires pymupdf") from exc
    with fitz.open(path) as pdf:
        return {
            page_number: (float(page.rect.width), float(page.rect.height))
            for page_number, page in enumerate(pdf, start=1)
        }


def _normalized_bbox(value: Any, dimensions: tuple[float, float]) -> BoundingBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    width, height = dimensions
    return BoundingBox(
        x0=float(value[0]) * width / 1000.0,
        y0=float(value[1]) * height / 1000.0,
        x1=float(value[2]) * width / 1000.0,
        y1=float(value[3]) * height / 1000.0,
    )


def _absolute_bbox(value: Any) -> BoundingBox | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return BoundingBox(x0=value[0], y0=value[1], x1=value[2], y1=value[3])
    except (TypeError, ValueError):
        return None


def _bbox_in_bounds(bbox: BoundingBox | None, width: float, height: float) -> bool:
    return bbox is None or (
        0 <= bbox.x0 <= bbox.x1 <= width + 1
        and 0 <= bbox.y0 <= bbox.y1 <= height + 1
    )


def _has_duplicate_table_region(elements: list[Any]) -> bool:
    tables = [item for item in elements if item.element_type == ElementType.TABLE and item.bbox]
    text = [
        item
        for item in elements
        if item.element_type in {ElementType.PARAGRAPH, ElementType.TITLE} and item.bbox
    ]
    return any(
        _intersection_over_smaller(table.bbox, block.bbox) > 0.8
        for table in tables
        for block in text
    )


def _intersection_over_smaller(a: BoundingBox, b: BoundingBox) -> float:
    intersection = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0)) * max(
        0.0, min(a.y1, b.y1) - max(a.y0, b.y0)
    )
    area_a = max((a.x1 - a.x0) * (a.y1 - a.y0), 0.0)
    area_b = max((b.x1 - b.x0) * (b.y1 - b.y0), 0.0)
    return intersection / max(min(area_a, area_b), 1.0)


def _valid_table_cells(cells: list[TableCell]) -> bool:
    if not cells:
        return False
    occupied: set[tuple[int, int]] = set()
    for cell in cells:
        slots = {
            (row, column)
            for row in range(cell.row_index, cell.row_index + cell.row_span)
            for column in range(cell.column_index, cell.column_index + cell.column_span)
        }
        if slots & occupied:
            return False
        occupied |= slots
    return True


def _number_tokens(text: str) -> list[str]:
    return [match.group(0).replace(",", "") for match in NUMBER_RE.finditer(text)]


def _strip_html(value: str) -> str:
    parser = _TableHtmlParser()
    try:
        parser.feed(value)
    except (TypeError, ValueError):
        return re.sub(r"<[^>]+>", " ", value)
    return "\n".join("\t".join(str(cell["text"]) for cell in row) for row in parser.rows)


def mineru_status(settings: Settings | None = None) -> dict[str, Any]:
    resolved = settings or get_settings()
    if not resolved.mineru_enabled:
        return {"enabled": False, "status": "disabled"}
    try:
        health = MineruClient(resolved).health()
    except Exception as exc:
        return {
            "enabled": True,
            "status": "misconfigured",
            "error": f"{type(exc).__name__}: {exc}",
        }
    health["enabled"] = True
    health["status"] = (
        "ready"
        if health.get("service_reachable")
        and (
            not resolved.mineru_device.casefold().startswith("cuda")
            or health.get("gpu_verified")
        )
        else "unavailable"
    )
    health["checked_at"] = datetime.now(UTC).isoformat()
    return health
