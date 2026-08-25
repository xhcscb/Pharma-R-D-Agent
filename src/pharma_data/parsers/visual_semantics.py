from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from pharma_data.config import Settings
from pharma_data.contracts import DocumentElement, ElementType, ParsedDocument, TableCell
from pharma_data.parsers.common import make_element
from pharma_data.utils.hashing import sha256_file

PIPELINE_STAGE_LABELS = (
    ("PHASE_I", "I期"),
    ("PHASE_II", "II期"),
    ("PHASE_III", "III期"),
    ("NDA", "NDA"),
)
STAGE_HEADER_RE = re.compile(
    r"(?:临床前|preclinical|phase|[ⅠⅡⅢIVivx1-4]+\s*期|NDA|BLA|上市)", re.I
)


def enrich_visual_semantics(
    document: ParsedDocument,
    pdf_path: Path,
    settings: Settings,
) -> ParsedDocument:
    """Preserve and verify meaning encoded by graphics instead of only OCR text.

    The first deterministic analyzer targets clinical-pipeline matrices. Other
    material charts/figures are explicitly routed to review; they are never
    treated as understood merely because OCR or a table detector found them.
    """
    if not settings.visual_semantics_enabled:
        return _mark_visual_disabled(document, settings)

    page_dimensions = _page_dimensions(pdf_path)
    required: list[DocumentElement] = []
    covered_ids: set[str] = set()
    failures_by_page: dict[int, list[str]] = {}
    enriched: list[DocumentElement] = []
    semantic_elements: list[DocumentElement] = []
    next_order = max((item.reading_order for item in document.elements), default=-1) + 1

    for element in document.elements:
        stage_layout = _pipeline_stage_layout(element.table_cells)
        requires_semantics = bool(stage_layout) or _material_visual(element, page_dimensions)
        if requires_semantics:
            required.append(element)

        if stage_layout:
            asset = _visual_asset(element)
            if not asset or not Path(str(asset.get("path") or "")).is_file():
                failures_by_page.setdefault(element.page_number or 1, []).append(
                    "visual_asset_missing"
                )
                enriched.append(element)
                continue
            result = analyze_pipeline_stage_chart(
                Path(str(asset["path"])),
                element.table_cells,
                stage_layout,
            )
            result["asset"] = asset
            payload = {
                **element.structured_payload,
                "visual_semantics": result,
            }
            element = element.model_copy(update={"structured_payload": payload})
            if (
                result["status"] == "verified"
                and float(result["confidence"]) >= settings.visual_semantics_min_confidence
            ):
                covered_ids.add(element.element_id)
                for observation in result["observations"]:
                    text = _observation_text(observation)
                    semantic_elements.append(
                        make_element(
                            document_version_id=document.document_version_id,
                            element_type=ElementType.STRUCTURED_RECORD,
                            reading_order=next_order,
                            text=text,
                            parser_name="visual-geometry",
                            parser_version="1.0.0",
                            page_number=element.page_number,
                            bbox=element.bbox,
                            structured_payload={
                                "visual_semantics": {
                                    "schema_version": "1.0",
                                    "status": "verified",
                                    "chart_type": "clinical_pipeline_stage_matrix",
                                    "source_element_id": element.element_id,
                                    "asset": asset,
                                    "observation": observation,
                                }
                            },
                            confidence=float(observation["confidence"]),
                        )
                    )
                    next_order += 1
            else:
                failures_by_page.setdefault(element.page_number or 1, []).append(
                    "visual_semantics_low_confidence"
                )
        elif requires_semantics:
            existing = element.structured_payload.get("visual_semantics", {})
            if isinstance(existing, dict) and existing.get("status") == "verified":
                covered_ids.add(element.element_id)
            else:
                failures_by_page.setdefault(element.page_number or 1, []).append(
                    "visual_semantics_missing"
                )
        enriched.append(element)

    required_count = len(required)
    covered_count = len(covered_ids)
    coverage = covered_count / max(required_count, 1) if required_count else 1.0
    page_quality = _merge_page_failures(document, failures_by_page)
    failed_pages = sorted(
        {
            *[int(value) for value in document.metadata.get("failed_pages", [])],
            *failures_by_page,
        }
    )
    visual_blocked = bool(failures_by_page) and settings.visual_semantics_required
    warnings = list(document.warnings)
    if visual_blocked:
        warnings.append(
            f"Visual semantics unresolved for {required_count - covered_count}/"
            f"{required_count} material visual elements; review required"
        )
    return document.model_copy(
        update={
            "elements": [*enriched, *semantic_elements],
            "metadata": {
                **document.metadata,
                "page_quality": page_quality,
                "failed_pages": failed_pages,
                "formal_reasoning_eligible": bool(
                    document.metadata.get("formal_reasoning_eligible", True)
                )
                and not visual_blocked,
                "visual_semantics": {
                    "schema_version": "1.0",
                    "required_count": required_count,
                    "verified_count": covered_count,
                    "observation_count": len(semantic_elements),
                    "coverage": round(coverage, 6),
                    "formal_gate_required": settings.visual_semantics_required,
                },
            },
            "parse_quality": {
                **document.parse_quality,
                "visual_semantic_coverage": coverage,
                "visual_semantic_required_count": float(required_count),
                "visual_semantic_verified_count": float(covered_count),
            },
            "warnings": sorted(set(warnings)),
        }
    )


def analyze_pipeline_stage_chart(
    image_path: Path,
    cells: list[TableCell],
    stage_layout: list[tuple[int, str, str]],
) -> dict[str, Any]:
    rows = _pipeline_rows(cells, stage_layout[0][0])
    bars, image_size = _horizontal_color_bars(image_path)
    review_reasons: list[str] = []
    if not rows:
        review_reasons.append("pipeline_rows_missing")
    if len(rows) != len(bars):
        review_reasons.append(
            f"row_bar_count_mismatch:{len(rows)}_rows:{len(bars)}_bars"
        )
    if not bars:
        review_reasons.append("colored_progress_bars_missing")

    observations: list[dict[str, Any]] = []
    if not review_reasons:
        stage_start = float(np.median([bar["x0"] for bar in bars]))
        stage_width = (image_size[0] - stage_start) / len(stage_layout)
        starts = [abs(float(bar["x0"]) - stage_start) for bar in bars]
        if max(starts, default=0.0) > max(stage_width * 0.08, 8.0):
            review_reasons.append("bar_origins_not_aligned")
        for row, bar in zip(rows, bars, strict=True):
            relative_end = (float(bar["x1"]) + 1.0 - stage_start) / stage_width
            stage_index = min(max(int(round(relative_end)), 1), len(stage_layout))
            residual = abs(relative_end - stage_index)
            if residual > 0.20:
                review_reasons.append(
                    f"bar_endpoint_ambiguous:row_{row['row_index']}:residual_{residual:.3f}"
                )
            _, stage_normalized, stage_label = stage_layout[stage_index - 1]
            confidence = max(0.0, min(0.99, 0.98 - residual * 0.35))
            observations.append(
                {
                    **row,
                    "stage": stage_normalized,
                    "stage_label": stage_label,
                    "bar_color": bar["color"],
                    "bar_bbox_pixels": {
                        key: int(bar[key]) for key in ("x0", "y0", "x1", "y1")
                    },
                    "stage_column_bbox_pixels": {
                        "x0": round(stage_start + (stage_index - 1) * stage_width, 3),
                        "y0": 0.0,
                        "x1": round(stage_start + stage_index * stage_width, 3),
                        "y1": float(image_size[1]),
                    },
                    "derivation": "colored_bar_endpoint_to_stage_column",
                    "confidence": round(confidence, 6),
                }
            )

    status = "verified" if not review_reasons and observations else "needs_review"
    confidence = min(
        (float(item["confidence"]) for item in observations),
        default=0.0,
    )
    return {
        "schema_version": "1.0",
        "status": status,
        "chart_type": "clinical_pipeline_stage_matrix",
        "analyzer": "deterministic_color_geometry",
        "analyzer_version": "1.0.0",
        "image_size_pixels": {"width": image_size[0], "height": image_size[1]},
        "stage_columns": [
            {"column_index": column, "stage": stage, "label": label}
            for column, stage, label in stage_layout
        ],
        "observations": observations,
        "confidence": round(confidence, 6),
        "review_reasons": sorted(set(review_reasons)),
    }


def _pipeline_stage_layout(cells: list[TableCell]) -> list[tuple[int, str, str]]:
    if not cells:
        return []
    total_columns = max(cell.column_index + cell.column_span for cell in cells)
    header = {
        column: cell.text.strip()
        for cell in cells
        if cell.row_index == 0
        for column in range(cell.column_index, cell.column_index + cell.column_span)
    }
    if total_columns < 8:
        return []
    rightmost = [header.get(column, "") for column in range(total_columns - 4, total_columns)]
    if not re.search(r"NDA|BLA|上市", rightmost[-1], re.I):
        return []
    if sum(bool(STAGE_HEADER_RE.search(value)) for value in rightmost) < 3:
        return []
    stage_columns = list(range(total_columns - 4, total_columns))
    if len(_pipeline_rows(cells, stage_columns[0])) < 2:
        return []
    return [
        (column, stage, label)
        for column, (stage, label) in zip(stage_columns, PIPELINE_STAGE_LABELS, strict=True)
    ]


def _pipeline_rows(cells: list[TableCell], stage_start_column: int) -> list[dict[str, Any]]:
    grid: dict[tuple[int, int], TableCell] = {}
    for cell in cells:
        for row in range(cell.row_index, cell.row_index + cell.row_span):
            for column in range(cell.column_index, cell.column_index + cell.column_span):
                grid[(row, column)] = cell
    max_row = max((cell.row_index + cell.row_span for cell in cells), default=1)
    drug_column = stage_start_column - 4
    target_column = stage_start_column - 3
    mode_column = stage_start_column - 2
    indication_column = stage_start_column - 1
    rows: list[dict[str, Any]] = []
    for row in range(1, max_row):
        mode = grid.get((row, mode_column))
        indication = grid.get((row, indication_column))
        region = grid.get((row, stage_start_column))
        if not mode or not indication or not region:
            continue
        if not (
            mode.row_index == row
            and indication.row_index == row
            and region.row_index == row
        ):
            continue
        if not indication.text.strip() or not region.text.strip():
            continue
        drug = grid.get((row, drug_column))
        target = grid.get((row, target_column))
        if not drug or not drug.text.strip():
            continue
        rows.append(
            {
                "row_index": row,
                "drug": drug.text.strip(),
                "target": target.text.strip() if target else "",
                "combination": mode.text.strip(),
                "indication": indication.text.strip(),
                "region": region.text.strip(),
            }
        )
    return rows


def _horizontal_color_bars(image_path: Path) -> tuple[list[dict[str, Any]], tuple[int, int]]:
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        rgb = np.asarray(image, dtype=np.int16)
    height, width, _ = rgb.shape
    channel_max = rgb.max(axis=2)
    channel_min = rgb.min(axis=2)
    saturated = (channel_max - channel_min >= 35) & (channel_max >= 65)
    saturated[:, : int(width * 0.45)] = False
    row_counts = saturated.sum(axis=1)
    active = row_counts >= max(30, int(width * 0.02))
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for y, is_active in enumerate(active.tolist() + [False]):
        if is_active and start is None:
            start = y
        elif not is_active and start is not None:
            if y - start >= 5:
                groups.append((start, y - 1))
            start = None

    bars: list[dict[str, Any]] = []
    for y0, y1 in groups:
        ys, xs = np.where(saturated[y0 : y1 + 1])
        if not xs.size:
            continue
        x0 = int(xs.min())
        x1 = int(xs.max())
        bar_height = y1 - y0 + 1
        if x0 < int(width * 0.45) or x1 - x0 < 40 or (x1 - x0) / bar_height < 2:
            continue
        pixels = rgb[y0 : y1 + 1][saturated[y0 : y1 + 1]]
        quantized = (np.clip(pixels, 0, 255).astype(np.uint8) // 8) * 8
        color_tuple, _ = Counter(map(tuple, quantized.tolist())).most_common(1)[0]
        bars.append(
            {
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "color": "#{:02x}{:02x}{:02x}".format(*color_tuple),
            }
        )
    return sorted(bars, key=lambda item: item["y0"]), (width, height)


def _visual_asset(element: DocumentElement) -> dict[str, Any] | None:
    mineru = element.structured_payload.get("mineru_content", {})
    if not isinstance(mineru, dict):
        return None
    asset = mineru.get("visual_asset")
    return asset if isinstance(asset, dict) else None


def _material_visual(
    element: DocumentElement,
    page_dimensions: dict[int, tuple[float, float]],
) -> bool:
    if element.element_type == ElementType.CHART:
        return True
    if element.element_type != ElementType.FIGURE or not element.bbox or not element.page_number:
        return False
    page = page_dimensions.get(element.page_number)
    if not page:
        return True
    area = (element.bbox.x1 - element.bbox.x0) * (element.bbox.y1 - element.bbox.y0)
    return area / max(page[0] * page[1], 1.0) >= 0.01


def _page_dimensions(path: Path) -> dict[int, tuple[float, float]]:
    try:
        import fitz
    except ImportError:
        return {}
    with fitz.open(path) as pdf:
        return {
            number: (float(page.rect.width), float(page.rect.height))
            for number, page in enumerate(pdf, start=1)
        }


def _merge_page_failures(
    document: ParsedDocument,
    failures_by_page: dict[int, list[str]],
) -> list[dict[str, Any]]:
    diagnostics = {
        int(item["page_number"]): dict(item)
        for item in document.metadata.get("page_quality", [])
        if isinstance(item, dict) and item.get("page_number") is not None
    }
    for page_number, failures in failures_by_page.items():
        item = diagnostics.setdefault(
            int(page_number),
            {"page_number": int(page_number), "failures": [], "passed": True},
        )
        item["failures"] = sorted(set([*(item.get("failures") or []), *failures]))
        item["passed"] = not item["failures"]
    return [diagnostics[key] for key in sorted(diagnostics)]


def _mark_visual_disabled(document: ParsedDocument, settings: Settings) -> ParsedDocument:
    required = [
        element
        for element in document.elements
        if _pipeline_stage_layout(element.table_cells)
        or element.element_type in {ElementType.CHART, ElementType.FIGURE}
    ]
    if not required:
        return document
    failed_pages = sorted(
        {
            *[int(value) for value in document.metadata.get("failed_pages", [])],
            *[element.page_number or 1 for element in required],
        }
    )
    failures = {
        element.page_number or 1: ["visual_semantics_disabled"] for element in required
    }
    page_quality = _merge_page_failures(document, failures)
    return document.model_copy(
        update={
            "metadata": {
                **document.metadata,
                "page_quality": page_quality,
                "failed_pages": failed_pages,
                "formal_reasoning_eligible": False,
            },
            "parse_quality": {
                **document.parse_quality,
                "visual_semantic_coverage": 0.0,
            },
            "warnings": sorted(
                set(
                    [
                        *document.warnings,
                        "Visual semantics disabled; material visuals require review",
                    ]
                )
            ),
        }
    )


def _observation_text(observation: dict[str, Any]) -> str:
    target = f"，靶点 {observation['target']}" if observation.get("target") else ""
    return (
        f"药品/代号 {observation['drug']}{target}，用于 {observation['indication']}；"
        f"{observation['region']} 管线阶段为 {observation['stage_label']}。"
        f"阶段由图中 {observation['bar_color']} 进度条终点映射到"
        f" {observation['stage_label']} 列。"
    )


def visual_asset_metadata(path: Path, *, source_ref: str) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
        mime_type = Image.MIME.get(image.format or "", "application/octet-stream")
    return {
        "source_ref": source_ref,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "mime_type": mime_type,
        "size_bytes": path.stat().st_size,
        "pixel_width": width,
        "pixel_height": height,
    }
