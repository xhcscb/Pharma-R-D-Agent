"""Collapse team-internal access into restricted access.

Revision ID: 0002_two_access_classes
Revises: 0001_initial
"""

from alembic import op

revision = "0002_two_access_classes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("source_record", "raw_artifact", "document_version", "dataset_snapshot"):
        op.execute(
            f"UPDATE {table} SET access_class = 'restricted' "
            "WHERE access_class = 'team_internal'"
        )


def downgrade() -> None:
    # The former team_internal/restricted distinction cannot be reconstructed safely.
    pass
