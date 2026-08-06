"""Create canonical provenance and fact schema.

Revision ID: 0001_initial
Revises:
"""

from alembic import op

from pharma_data.storage.canonical import models  # noqa: F401
from pharma_data.storage.canonical.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
