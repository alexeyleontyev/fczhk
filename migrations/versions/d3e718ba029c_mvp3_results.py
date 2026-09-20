"""MVP 3: actual participants and result events, preserving all pre-match data."""

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "d3e718ba029c"
down_revision = "c2a486fe91d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "match_results",
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), primary_key=True),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "result_participants",
        sa.Column(
            "match_id", sa.Integer(), sa.ForeignKey("match_results.match_id"), primary_key=True
        ),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("team", sa.String(10), nullable=False),
        sa.Column("position", sa.String(10), nullable=False),
        sa.CheckConstraint("team IN ('white', 'black')"),
        sa.CheckConstraint("position IN ('field', 'keeper')"),
    )
    op.create_table(
        "result_goals",
        sa.Column(
            "match_id", sa.Integer(), sa.ForeignKey("match_results.match_id"), primary_key=True
        ),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("team", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.Column("assist_id", sa.Integer(), sa.ForeignKey("players.id")),
        sa.CheckConstraint("team IN ('white', 'black')"),
        sa.CheckConstraint("kind IN ('goal', 'own_goal')"),
        sa.CheckConstraint("author_id IS NULL OR assist_id IS NULL OR author_id <> assist_id"),
        sa.CheckConstraint("kind <> 'own_goal' OR (author_id IS NOT NULL AND assist_id IS NULL)"),
    )


def downgrade():
    op.drop_table("result_goals")
    op.drop_table("result_participants")
    op.drop_table("match_results")
