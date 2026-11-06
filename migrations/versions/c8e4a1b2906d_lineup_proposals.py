"""One published lineup proposal per member and game."""

import sqlalchemy as sa
from alembic import op

revision = "c8e4a1b2906d"
down_revision = "b7d8e2a9103f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lineup_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("roster_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("match_id", "author_id", name="uq_lineup_proposal_author"),
        sa.CheckConstraint("revision >= 1", name="ck_lineup_proposal_revision"),
    )
    op.create_index("ix_lineup_proposals_match_id", "lineup_proposals", ["match_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM lineup_proposals")).scalar():
        raise RuntimeError("Нельзя удалить сохранённые предложения составов")
    op.drop_table("lineup_proposals")
