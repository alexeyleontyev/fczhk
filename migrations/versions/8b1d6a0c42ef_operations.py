"""Operations, schedule exceptions and historical profile claims."""

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "8b1d6a0c42ef"
down_revision = "4e8493c19b02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_table(
        "service_heartbeats",
        sa.Column("name", sa.String(30), primary_key=True),
        sa.Column("checked_at", UTCDateTime(), nullable=False),
        sa.Column("succeeded_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.String(100), nullable=True),
    )
    op.create_table(
        "skipped_game_days",
        sa.Column("game_day", sa.String(10), primary_key=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "profile_claims",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("guest_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'rejected')"),
    )


def downgrade():
    op.drop_table("profile_claims")
    op.drop_table("skipped_game_days")
    op.drop_table("service_heartbeats")
    op.drop_index("ix_login_sessions_expires_at", table_name="login_sessions")
