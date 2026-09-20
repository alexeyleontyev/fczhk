"""MVP 4: persistent captain auctions and sealed lots."""

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "e4f928cb13ad"
down_revision = "d3e718ba029c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auctions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("roster_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("white_captain", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("black_captain", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("white_budget", sa.Integer(), nullable=False),
        sa.Column("black_budget", sa.Integer(), nullable=False),
        sa.Column("white_limit", sa.Integer(), nullable=False),
        sa.Column("black_limit", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("white_budget BETWEEN 0 AND 100 AND black_budget BETWEEN 0 AND 100"),
        sa.CheckConstraint("white_captain <> black_captain"),
        sa.CheckConstraint("white_limit >= 1 AND black_limit >= 1"),
    )
    op.create_index("ix_auctions_match_id", "auctions", ["match_id"])
    op.create_table(
        "auction_lots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("auction_id", sa.Integer(), sa.ForeignKey("auctions.id"), nullable=False),
        sa.Column(
            "registration_id", sa.Integer(), sa.ForeignKey("registrations.id"), nullable=False
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("white_bid", sa.Integer()),
        sa.Column("black_bid", sa.Integer()),
        sa.Column("winner", sa.String(10)),
        sa.UniqueConstraint("auction_id", "number"),
        sa.CheckConstraint("white_bid IS NULL OR white_bid BETWEEN 0 AND 100"),
        sa.CheckConstraint("black_bid IS NULL OR black_bid BETWEEN 0 AND 100"),
    )
    op.create_index("ix_auction_lots_auction_id", "auction_lots", ["auction_id"])


def downgrade():
    op.drop_table("auction_lots")
    op.drop_table("auctions")
