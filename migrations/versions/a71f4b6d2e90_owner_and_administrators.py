"""Persist administrator decisions; the owner is configured by Telegram ID."""

import sqlalchemy as sa
from alembic import op

revision = "a71f4b6d2e90"
down_revision = "9c2d8f4a10b7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("players", sa.Column("admin_access", sa.Boolean(), nullable=True))
    op.add_column(
        "players",
        sa.Column(
            "admin_access_revision", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )


def downgrade():
    decided = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM players WHERE admin_access IS NOT NULL"))
        .scalar_one()
    )
    if decided:
        raise ValueError(
            "Есть назначения или отзывы прав администратора; downgrade потеряет решения владельца"
        )
    op.drop_column("players", "admin_access_revision")
    op.drop_column("players", "admin_access")
