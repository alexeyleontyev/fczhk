"""Remember verified Telegram usernames independently of game aliases."""

import sqlalchemy as sa
from alembic import op

revision = "1c8d7e0f325a"
down_revision = "0b7c6d9e214f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("players", sa.Column("telegram_username", sa.String(32), nullable=True))


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM players WHERE telegram_username IS NOT NULL"))
        .scalar_one()
    ):
        raise ValueError("Сохранены Telegram-никнеймы; downgrade потеряет данные")
    with op.batch_alter_table("players") as batch:
        batch.drop_column("telegram_username")
