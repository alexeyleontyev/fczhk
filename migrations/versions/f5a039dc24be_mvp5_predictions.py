"""MVP 5: one revisable score prediction per player and match."""

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "f5a039dc24be"
down_revision = "e4f928cb13ad"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "predictions",
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("white_score", sa.Integer(), nullable=False),
        sa.Column("black_score", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("approved_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("white_score BETWEEN 0 AND 200 AND black_score BETWEEN 0 AND 200"),
        sa.CheckConstraint("revision >= 1"),
    )


def downgrade():
    op.drop_table("predictions")
