"""Retain withdrawn votes and their revisions without reviving imported votes."""

import sqlalchemy as sa
from alembic import op

revision = "d7a4c2e910bf"
down_revision = "c8e4a1b2906d"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("ratings", "rating_history"):
        op.add_column(
            table, sa.Column("withdrawn", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    bind = op.get_bind()
    for table in ("ratings", "rating_history"):
        if bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE withdrawn")).scalar():
            raise RuntimeError("Нельзя потерять историю удаления оценок")
    for table in ("rating_history", "ratings"):
        op.drop_column(table, "withdrawn")
