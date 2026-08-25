"""Add canonical fact grouping and evidence hashes.

Revision ID: 0004_fact_evidence_integrity
Revises: 0003_quality_first_pdf
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0004_fact_evidence_integrity"
down_revision = "0003_quality_first_pdf"
branch_labels = None
depends_on = None


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("assertion") as batch_op:
        batch_op.add_column(sa.Column("fact_group_key", sa.String(64), nullable=True))
        batch_op.create_index("ix_assertion_fact_group", ["fact_group_key"])

    with op.batch_alter_table("assertion_evidence") as batch_op:
        batch_op.drop_constraint("uq_assertion_evidence_locator", type_="unique")
        batch_op.add_column(sa.Column("evidence_hash", sa.String(64), nullable=True))
        batch_op.create_unique_constraint(
            "uq_assertion_evidence_locator",
            ["assertion_id", "element_id", "utterance_id", "table_cell_id"],
        )
        batch_op.create_index(
            "ix_assertion_evidence_hash", ["assertion_id", "evidence_hash"]
        )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT ae.id, ae.document_version_id, ae.evidence_text, ae.page_number,
                   ae.bbox, ae.char_span, ae.audio_range, dv.content_hash,
                   tc.row_index, tc.column_index, tc.text AS cell_text, tc.bbox AS cell_bbox
            FROM assertion_evidence ae
            JOIN document_version dv ON dv.id = ae.document_version_id
            LEFT JOIN table_cell tc ON tc.id = ae.table_cell_id
            """
        )
    ).mappings()
    for row in rows:
        value = {
            "document_content_hash": row["content_hash"],
            "page_number": row["page_number"],
            "bbox": row["bbox"],
            "char_span": row["char_span"],
            "table_cell": (
                {
                    "row_index": row["row_index"],
                    "column_index": row["column_index"],
                    "text": row["cell_text"],
                    "bbox": row["cell_bbox"],
                }
                if row["row_index"] is not None
                else None
            ),
            "audio_range": row["audio_range"],
            "evidence_text": row["evidence_text"],
        }
        bind.execute(
            sa.text(
                "UPDATE assertion_evidence SET evidence_hash = :evidence_hash WHERE id = :id"
            ),
            {"evidence_hash": _stable_hash(value), "id": row["id"]},
        )


def downgrade() -> None:
    with op.batch_alter_table("assertion_evidence") as batch_op:
        batch_op.drop_index("ix_assertion_evidence_hash")
        batch_op.drop_constraint("uq_assertion_evidence_locator", type_="unique")
        batch_op.create_unique_constraint(
            "uq_assertion_evidence_locator",
            ["assertion_id", "element_id", "utterance_id"],
        )
        batch_op.drop_column("evidence_hash")
    with op.batch_alter_table("assertion") as batch_op:
        batch_op.drop_index("ix_assertion_fact_group")
        batch_op.drop_column("fact_group_key")
