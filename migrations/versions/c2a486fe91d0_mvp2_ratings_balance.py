"""MVP 2: current ratings, history, match fallbacks and immutable balance runs.

Revision ID: c2a486fe91d0
Revises: 990662d3f1e7
"""

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "c2a486fe91d0"
down_revision = "990662d3f1e7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rating_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "rating_state", sa.column("id", sa.Integer()), sa.column("revision", sa.Integer())
        ),
        [{"id": 1, "revision": 0}],
    )
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("position", sa.String(10), nullable=False),
        sa.Column("attack", sa.Integer()),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("author_id", "player_id", "position"),
        sa.CheckConstraint("author_id <> player_id"),
        sa.CheckConstraint("defense BETWEEN 0 AND 50"),
        sa.CheckConstraint(
            "(position = 'field' AND attack IS NOT NULL AND attack BETWEEN 0 AND 50) OR (position = 'keeper' AND attack IS NULL)"
        ),
    )
    op.create_index("ix_ratings_author_id", "ratings", ["author_id"])
    op.create_index("ix_ratings_player_id", "ratings", ["player_id"])
    op.create_table(
        "rating_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rating_id", sa.Integer(), sa.ForeignKey("ratings.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attack", sa.Integer()),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("rating_id", "revision"),
    )
    op.create_index("ix_rating_history_rating_id", "rating_history", ["rating_id"])
    op.create_table(
        "match_ratings",
        sa.Column(
            "registration_id", sa.Integer(), sa.ForeignKey("registrations.id"), primary_key=True
        ),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("position", sa.String(10), nullable=False),
        sa.Column("attack", sa.Integer()),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("defense BETWEEN 0 AND 50"),
        sa.CheckConstraint(
            "(position = 'field' AND attack IS NOT NULL AND attack BETWEEN 0 AND 50) OR (position = 'keeper' AND attack IS NULL)"
        ),
    )
    op.create_table(
        "balance_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("roster_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_balance_runs_match_id", "balance_runs", ["match_id"])
    op.create_table(
        "team_rating_drafts",
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("balance_runs.id"), nullable=False),
        sa.Column("variant", sa.Integer(), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "team_rating_snapshots",
        sa.Column(
            "snapshot_id", sa.Integer(), sa.ForeignKey("team_snapshots.id"), primary_key=True
        ),
        sa.Column("data", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("team_rating_snapshots")
    op.drop_table("team_rating_drafts")
    op.drop_table("balance_runs")
    op.drop_table("match_ratings")
    op.drop_table("rating_history")
    op.drop_table("ratings")
    op.drop_table("rating_state")
