"""Rebuild facts from the current active parse without parsing source files again."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharma_data.cleaning import DataCleanAgent
from pharma_data.contracts import (
    BoundingBox,
    CharacterSpan,
    DocumentElement,
    DocumentType,
    ElementType,
    ParsedDocument,
    TableCell,
)
from pharma_data.entity_extraction import (
    DictionaryExtractor,
    EntityExtractAgent,
    PatternExtractor,
    VisualSemanticExtractor,
)
from pharma_data.relation_extraction import RelationExtractAgent
from pharma_data.storage.canonical.database import get_engine
from pharma_data.storage.canonical.models import (
    CharacterSpanRecord,
    Document,
    DocumentElementRecord,
    DocumentVersion,
    ProcessingRun,
    TableCellRecord,
)
from pharma_data.storage.canonical.repository import CanonicalRepository


def _bbox(value: dict[str, Any] | None) -> BoundingBox | None:
    return BoundingBox.model_validate(value) if value else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def load_active_document(session: Session, version: DocumentVersion) -> ParsedDocument:
    if not version.active_parse_run_id:
        raise RuntimeError(f"Document version {version.id} has no active parse run")
    document = session.get(Document, version.document_id)
    run = session.get(ProcessingRun, version.active_parse_run_id)
    if document is None or run is None:
        raise RuntimeError(f"Document version {version.id} has broken active parse references")

    element_rows = list(
        session.scalars(
            select(DocumentElementRecord)
            .where(
                DocumentElementRecord.document_version_id == version.id,
                DocumentElementRecord.parse_run_id == version.active_parse_run_id,
            )
            .order_by(
                DocumentElementRecord.page_number,
                DocumentElementRecord.reading_order,
            )
        )
    )
    element_ids = [item.id for item in element_rows]
    spans: dict[str, list[CharacterSpan]] = defaultdict(list)
    cells: dict[str, list[TableCell]] = defaultdict(list)
    if element_ids:
        for span_row in session.scalars(
            select(CharacterSpanRecord)
            .where(CharacterSpanRecord.element_id.in_(element_ids))
            .order_by(
                CharacterSpanRecord.element_id,
                CharacterSpanRecord.char_start,
            )
        ):
            spans[span_row.element_id].append(
                CharacterSpan(
                    char_start=span_row.char_start,
                    char_end=span_row.char_end,
                    text=span_row.text,
                    bbox=_bbox(span_row.bbox),
                    confidence=span_row.confidence,
                )
            )
        for cell_row in session.scalars(
            select(TableCellRecord)
            .where(TableCellRecord.element_id.in_(element_ids))
            .order_by(
                TableCellRecord.element_id,
                TableCellRecord.row_index,
                TableCellRecord.column_index,
            )
        ):
            cells[cell_row.element_id].append(
                TableCell(
                    row_index=cell_row.row_index,
                    column_index=cell_row.column_index,
                    row_span=cell_row.row_span,
                    column_span=cell_row.column_span,
                    text=cell_row.text,
                    bbox=_bbox(cell_row.bbox),
                    header_path=cell_row.header_path or [],
                    normalized_value=cell_row.normalized_value,
                    numeric_value=_decimal_text(cell_row.numeric_value),
                    unit=cell_row.unit,
                    currency=cell_row.currency,
                    scale=cell_row.scale,
                    period_start=cell_row.period_start,
                    period_end=cell_row.period_end,
                    confidence=cell_row.confidence,
                )
            )

    elements = [
        DocumentElement(
            element_id=row.id,
            document_version_id=row.document_version_id,
            page_number=row.page_number,
            element_type=ElementType(row.element_type),
            bbox=_bbox(row.bbox),
            reading_order=row.reading_order,
            text=row.text,
            structured_payload=row.structured_payload or {},
            character_spans=spans[row.id],
            table_cells=cells[row.id],
            footnote_links=row.footnote_links or [],
            parser_name=row.parser_name,
            parser_version=row.parser_version,
            confidence=row.confidence,
            content_hash=row.content_hash,
        )
        for row in element_rows
    ]
    metadata = dict(version.metadata_json or {})
    return ParsedDocument(
        document_id=document.id,
        document_version_id=version.id,
        document_type=DocumentType(document.document_type),
        language=str(metadata.get("language") or "und"),
        metadata=metadata,
        elements=elements,
        parse_quality={
            str(key): float(value)
            for key, value in dict(metadata.get("parse_quality") or {}).items()
            if isinstance(value, (int, float))
        },
        warnings=list(run.warnings or []),
    )


def rebuild_version(
    session: Session,
    version: DocumentVersion,
    *,
    lexicon_path: str | Path,
    dry_run: bool,
) -> dict[str, Any]:
    parsed = load_active_document(session, version)
    entity_agent = EntityExtractAgent(
        [
            DictionaryExtractor(lexicon_path),
            PatternExtractor(),
            VisualSemanticExtractor(),
        ]
    )
    relation_agent = RelationExtractAgent()
    mentions = entity_agent.extract(parsed)
    assertions = relation_agent.extract(parsed, mentions)
    assertions.extend(relation_agent.derive_competition(assertions, mentions))
    clean = DataCleanAgent().clean(
        document_version_id=version.id,
        mentions=mentions,
        assertions=assertions,
    )
    saved = (0, 0, 0)
    if not dry_run:
        saved = CanonicalRepository(session).save_clean_result(clean)
    table_assertions = [
        item
        for item in clean.assertions
        if item.extraction_method == "schema_rule:FINANCIAL_TABLE_CELL"
    ]
    return {
        "document_id": version.document_id,
        "document_version_id": version.id,
        "active_parse_run_id": version.active_parse_run_id,
        "elements": len(parsed.elements),
        "mentions_extracted": len(clean.mentions),
        "assertions_extracted": len(clean.assertions),
        "table_cell_assertions": len(table_assertions),
        "table_cell_evidence_complete": sum(
            item.evidence_table_cell is not None for item in table_assertions
        ),
        "conflicts_extracted": len(clean.conflicts),
        "quality_level": clean.quality_level.value,
        "mentions_saved": saved[0],
        "assertions_saved": saved[1],
        "conflicts_saved": saved[2],
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--lexicon", default="config/entities.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with Session(get_engine()) as session:
        query = select(DocumentVersion).where(DocumentVersion.active_parse_run_id.is_not(None))
        if args.document_id:
            query = query.where(DocumentVersion.document_id.in_(args.document_id))
        versions = list(session.scalars(query.order_by(DocumentVersion.created_at)))
        results: list[dict[str, Any]] = []
        for version in versions:
            result = rebuild_version(
                session,
                version,
                lexicon_path=args.lexicon,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                session.commit()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        print(
            json.dumps(
                {
                    "status": "complete",
                    "versions": len(results),
                    "dry_run": args.dry_run,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
