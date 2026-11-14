"""Betting points journal: weekly freebets now, stakes, payouts and refunds later."""

import sqlalchemy as sa
from alembic import op

revision = "e1b5c7a93f20"
down_revision = "d7a4c2e910bf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wallet_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("freebet_week", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("player_id", "freebet_week", name="uq_wallet_freebet_week"),
        sa.CheckConstraint(
            "kind IN ('freebet', 'stake', 'payout', 'refund')", name="ck_wallet_entry_kind"
        ),
        sa.CheckConstraint(
            "(kind = 'freebet' AND freebet_week IS NOT NULL) OR (kind <> 'freebet' AND freebet_week IS NULL)",
            name="ck_wallet_freebet_week",
        ),
        sa.CheckConstraint(
            "(kind = 'stake' AND amount < 0) OR (kind <> 'stake' AND amount >= 0)",
            name="ck_wallet_entry_sign",
        ),
    )
    op.create_index("ix_wallet_entries_player_id", "wallet_entries", ["player_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM wallet_entries")).scalar():
        raise RuntimeError("Нельзя удалить журнал ставок с балансами игроков")
    op.drop_index("ix_wallet_entries_player_id", table_name="wallet_entries")
    op.drop_table("wallet_entries")
