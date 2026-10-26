"""Prepare hidden collections for automatic opening with an existing queue."""

import sqlalchemy as sa
from alembic import op

revision = "a6e91f2c704b"
down_revision = "9f0a4b7c2d61"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "matches", sa.Column("scheduled_opening_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_matches_scheduled_opening_at", "matches", ["scheduled_opening_at"])


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM matches WHERE scheduled_opening_at IS NOT NULL LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Нельзя удалить сохранённое расписание подготовленных сборов")
    op.drop_index("ix_matches_scheduled_opening_at", table_name="matches")
    op.drop_column("matches", "scheduled_opening_at")
