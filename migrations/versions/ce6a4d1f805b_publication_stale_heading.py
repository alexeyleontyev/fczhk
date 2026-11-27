"""Store the replacement heading for a superseded publication."""

import sqlalchemy as sa
from alembic import op

revision = "ce6a4d1f805b"
down_revision = "a6c2f3ea94bd"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("publications", sa.Column("stale_heading", sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column("publications", "stale_heading")
