"""Add access grants and quality-first PDF provenance.

Revision ID: 0003_quality_first_pdf
Revises: 0002_two_access_classes
"""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0003_quality_first_pdf"
down_revision = "0002_two_access_classes"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON()


def upgrade() -> None:
    op.create_table(
        "document_access_grant",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("document_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_record_id",
            sa.String(36),
            sa.ForeignKey("source_record.id", ondelete="SET NULL"),
        ),
        sa.Column("access_class", sa.String(40), nullable=False),
        sa.Column("license_status", sa.String(40), nullable=False),
        sa.Column("provenance_status", sa.String(80), nullable=False),
        sa.Column("authorization_reference", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "document_version_id", "access_class", name="uq_version_access_grant"
        ),
    )
    op.create_index(
        "ix_access_grant_class_active",
        "document_access_grant",
        ["access_class", "active"],
    )

    op.create_table(
        "mineru_backend",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("backend", sa.String(80), nullable=False),
        sa.Column("capabilities", JSON_TYPE, nullable=False),
        sa.Column("model_name", sa.String(200)),
        sa.Column("model_version", sa.String(120)),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("health_status", sa.String(40), nullable=False),
        sa.Column("allowed_access_classes", JSON_TYPE, nullable=False),
        sa.Column("tls_required", sa.Boolean(), nullable=False),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "parse_candidate",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("document_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parse_run_id",
            sa.String(36),
            sa.ForeignKey("processing_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer()),
        sa.Column("region_key", sa.String(160)),
        sa.Column("backend_name", sa.String(120), nullable=False),
        sa.Column("backend_version", sa.String(120)),
        sa.Column("node_id", sa.String(120)),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("diagnostics", JSON_TYPE, nullable=False),
        sa.Column("parameters", JSON_TYPE, nullable=False),
        sa.Column("raw_output_path", sa.Text()),
        sa.Column("raw_output_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_parse_candidate_version_page",
        "parse_candidate",
        ["document_version_id", "page_number"],
    )
    op.create_index(
        "ix_parse_candidate_run_selected", "parse_candidate", ["parse_run_id", "selected"]
    )

    op.create_table(
        "character_span",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "element_id",
            sa.String(36),
            sa.ForeignKey("document_element.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox", JSON_TYPE),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.UniqueConstraint("element_id", "char_start", "char_end", name="uq_element_span"),
    )

    op.create_table(
        "table_cell",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "element_id",
            sa.String(36),
            sa.ForeignKey("document_element.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("column_index", sa.Integer(), nullable=False),
        sa.Column("row_span", sa.Integer(), nullable=False),
        sa.Column("column_span", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox", JSON_TYPE),
        sa.Column("header_path", JSON_TYPE, nullable=False),
        sa.Column("normalized_value", sa.Text()),
        sa.Column("numeric_value", sa.Numeric(38, 12)),
        sa.Column("unit", sa.String(80)),
        sa.Column("currency", sa.String(20)),
        sa.Column("scale", sa.String(40)),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.UniqueConstraint("element_id", "row_index", "column_index", name="uq_table_cell"),
    )
    op.create_index("ix_table_cell_period", "table_cell", ["period_end"])

    op.create_table(
        "parse_review_item",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(36),
            sa.ForeignKey("document_version.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parse_run_id",
            sa.String(36),
            sa.ForeignKey("processing_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("region_key", sa.String(160)),
        sa.Column("gate_code", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("diagnostics", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_parse_review_open",
        "parse_review_item",
        ["status", "document_version_id", "page_number"],
    )

    with op.batch_alter_table("assertion_evidence") as batch_op:
        batch_op.add_column(sa.Column("table_cell_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_assertion_evidence_table_cell",
            "table_cell",
            ["table_cell_id"],
            ["id"],
            ondelete="SET NULL",
        )

    bind = op.get_bind()
    grant_table = sa.table(
        "document_access_grant",
        sa.column("id", sa.String(36)),
        sa.column("document_version_id", sa.String(36)),
        sa.column("source_record_id", sa.String(36)),
        sa.column("access_class", sa.String(40)),
        sa.column("license_status", sa.String(40)),
        sa.column("provenance_status", sa.String(80)),
        sa.column("active", sa.Boolean()),
        sa.column("metadata_json", JSON_TYPE),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    versions = bind.execute(
        sa.text(
            "SELECT id, source_record_id, access_class, license_status, metadata_json "
            "FROM document_version"
        )
    ).mappings()
    for row in versions:
        metadata = row["metadata_json"] or {}
        provenance = (
            metadata.get("provenance_status", "legacy_backfill")
            if isinstance(metadata, dict)
            else "legacy_backfill"
        )
        current_time = datetime.now(UTC)
        bind.execute(
            grant_table.insert(),
            {
                "id": str(uuid4()),
                "document_version_id": row["id"],
                "source_record_id": row["source_record_id"],
                "access_class": row["access_class"],
                "license_status": row["license_status"],
                "provenance_status": provenance,
                "active": True,
                "metadata_json": {},
                "created_at": current_time,
                "updated_at": current_time,
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("assertion_evidence") as batch_op:
        batch_op.drop_constraint(
            "fk_assertion_evidence_table_cell", type_="foreignkey"
        )
        batch_op.drop_column("table_cell_id")
    op.drop_index("ix_parse_review_open", table_name="parse_review_item")
    op.drop_table("parse_review_item")
    op.drop_index("ix_table_cell_period", table_name="table_cell")
    op.drop_table("table_cell")
    op.drop_table("character_span")
    op.drop_index("ix_parse_candidate_run_selected", table_name="parse_candidate")
    op.drop_index("ix_parse_candidate_version_page", table_name="parse_candidate")
    op.drop_table("parse_candidate")
    op.drop_table("mineru_backend")
    op.drop_index("ix_access_grant_class_active", table_name="document_access_grant")
    op.drop_table("document_access_grant")
