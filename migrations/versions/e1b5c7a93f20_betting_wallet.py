"""Betting on virtual points: fitted pricing models, frozen odds, bets and the points journal."""

import sqlalchemy as sa
from alembic import op

revision = "e1b5c7a93f20"
down_revision = "d7a4c2e910bf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pricing_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("n_matches", sa.Integer(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "match_odds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("approved_version", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Integer(), sa.ForeignKey("pricing_models.id"), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("markets", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("match_id", "approved_version", name="uq_match_odds_version"),
    )
    op.create_index("ix_match_odds_match_id", "match_odds", ["match_id"])
    op.create_table(
        "bets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("odds_id", sa.Integer(), sa.ForeignKey("match_odds.id"), nullable=False),
        sa.Column("approved_version", sa.Integer(), nullable=False),
        sa.Column("selections", sa.JSON(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("stake", sa.BigInteger(), nullable=False),
        sa.Column("odds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(5), nullable=False),
        sa.Column("credited", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open', 'won', 'lost', 'void')", name="ck_bet_status"),
        sa.CheckConstraint("stake > 0", name="ck_bet_stake"),
        sa.CheckConstraint("odds >= 101", name="ck_bet_odds"),
        sa.CheckConstraint("credited >= 0", name="ck_bet_credited"),
    )
    op.create_index("ix_bets_player_id", "bets", ["player_id"])
    op.create_index("ix_bets_match_id", "bets", ["match_id"])
    op.create_table(
        "wallet_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("freebet_week", sa.String(8), nullable=True),
        sa.Column("bet_id", sa.Integer(), sa.ForeignKey("bets.id"), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("player_id", "freebet_week", name="uq_wallet_freebet_week"),
        sa.CheckConstraint(
            "kind IN ('freebet', 'stake', 'payout', 'refund', 'correction', 'grant')",
            name="ck_wallet_entry_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'freebet' AND freebet_week IS NOT NULL) OR (kind <> 'freebet' AND freebet_week IS NULL)",
            name="ck_wallet_freebet_week",
        ),
        sa.CheckConstraint(
            "(kind = 'stake' AND amount < 0) OR (kind IN ('freebet', 'payout', 'refund') AND amount >= 0) OR kind = 'correction' OR (kind = 'grant' AND amount <> 0)",
            name="ck_wallet_entry_sign",
        ),
        sa.CheckConstraint(
            "(kind IN ('freebet', 'grant')) = (bet_id IS NULL)", name="ck_wallet_entry_bet"
        ),
        sa.CheckConstraint(
            "(kind = 'grant') = (actor_id IS NOT NULL AND note IS NOT NULL)",
            name="ck_wallet_entry_grant",
        ),
    )
    op.create_index("ix_wallet_entries_player_id", "wallet_entries", ["player_id"])
    op.create_table(
        "point_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("players.id"), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'cancelled')",
            name="ck_point_request_status",
        ),
        sa.CheckConstraint("amount > 0", name="ck_point_request_amount"),
    )
    op.create_index("ix_point_requests_player_id", "point_requests", ["player_id"])
    op.create_index(
        "uq_point_request_pending",
        "point_requests",
        ["player_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_wallet_entries_bet_id", "wallet_entries", ["bet_id"])


def downgrade():
    bind = op.get_bind()
    for table in ("wallet_entries", "bets", "point_requests"):
        if bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar():
            raise RuntimeError("Нельзя удалить журнал ставок с балансами игроков")
    op.drop_index("uq_point_request_pending", table_name="point_requests")
    op.drop_index("ix_point_requests_player_id", table_name="point_requests")
    op.drop_table("point_requests")
    op.drop_index("ix_wallet_entries_bet_id", table_name="wallet_entries")
    op.drop_index("ix_wallet_entries_player_id", table_name="wallet_entries")
    op.drop_table("wallet_entries")
    op.drop_index("ix_bets_match_id", table_name="bets")
    op.drop_index("ix_bets_player_id", table_name="bets")
    op.drop_table("bets")
    op.drop_index("ix_match_odds_match_id", table_name="match_odds")
    op.drop_table("match_odds")
    op.drop_table("pricing_models")
