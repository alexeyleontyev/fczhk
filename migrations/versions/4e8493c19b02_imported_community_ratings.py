"""Store precise community votes imported from the historical spreadsheet."""

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "4e8493c19b02"
down_revision = "f5a039dc24be"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "imported_ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("position", sa.String(10), nullable=False),
        sa.Column("attack_milli", sa.Integer(), nullable=False),
        sa.Column("defense_milli", sa.Integer(), nullable=False),
        sa.Column("attack_cell", sa.String(12), nullable=False),
        sa.Column("defense_cell", sa.String(12), nullable=False),
        sa.Column("imported_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("source_id", "author_id", "player_id", "position"),
        sa.CheckConstraint("author_id <> player_id"),
        sa.CheckConstraint("position = 'field'"),
        sa.CheckConstraint("attack_milli BETWEEN 0 AND 5000"),
        sa.CheckConstraint("defense_milli BETWEEN 0 AND 5000"),
    )
    op.create_index("ix_imported_ratings_author_id", "imported_ratings", ["author_id"])
    op.create_index("ix_imported_ratings_player_id", "imported_ratings", ["player_id"])


def downgrade():
    op.drop_index("ix_imported_ratings_player_id", table_name="imported_ratings")
    op.drop_index("ix_imported_ratings_author_id", table_name="imported_ratings")
    op.drop_table("imported_ratings")
