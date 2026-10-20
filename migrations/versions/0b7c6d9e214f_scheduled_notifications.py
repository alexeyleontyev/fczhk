"""Configure notification destinations and durable, expiring scheduled announcements."""

import sqlalchemy as sa
from alembic import op

revision = "0b7c6d9e214f"
down_revision = "f97c3e8d210a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("game_template") as batch:
        for name in ("announcements_chat_id", "extended_chat_id"):
            batch.add_column(sa.Column(name, sa.String(100), nullable=False, server_default=""))
        for name in ("announcement_enabled", "payment_reminder_enabled"):
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )
        for name in (
            "extended_auction_enabled",
            "extended_registration_enabled",
            "extended_cancellation_enabled",
        ):
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true())
            )
        batch.add_column(
            sa.Column("announcement_minutes", sa.Integer(), nullable=False, server_default="30")
        )
        batch.add_column(
            sa.Column("payment_reminder_weekday", sa.Integer(), nullable=False, server_default="3")
        )
        batch.add_column(
            sa.Column("payment_reminder_time", sa.String(5), nullable=False, server_default="18:00")
        )
    with op.batch_alter_table("publications") as batch:
        batch.alter_column("match_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("dedupe_key", sa.String(160), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_unique_constraint("uq_publications_dedupe_key", ["dedupe_key"])


def downgrade():
    connection = op.get_bind()
    configured = connection.execute(
        sa.text(
            "SELECT count(*) FROM game_template WHERE announcements_chat_id != '' OR extended_chat_id != '' "
            "OR announcement_enabled OR payment_reminder_enabled OR announcement_minutes != 30 "
            "OR payment_reminder_weekday != 3 OR payment_reminder_time != '18:00' "
            "OR NOT extended_auction_enabled OR NOT extended_registration_enabled OR NOT extended_cancellation_enabled"
        )
    ).scalar_one()
    notices = connection.execute(
        sa.text(
            "SELECT count(*) FROM publications WHERE dedupe_key IS NOT NULL OR match_id IS NULL"
        )
    ).scalar_one()
    if configured or notices:
        raise ValueError("Настроены уведомления или сохранены анонсы; downgrade потеряет данные")
    with op.batch_alter_table("publications") as batch:
        batch.drop_constraint("uq_publications_dedupe_key", type_="unique")
        batch.drop_column("expires_at")
        batch.drop_column("dedupe_key")
        batch.alter_column("match_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("game_template") as batch:
        for name in (
            "announcements_chat_id",
            "extended_chat_id",
            "announcement_enabled",
            "announcement_minutes",
            "payment_reminder_enabled",
            "payment_reminder_weekday",
            "payment_reminder_time",
            "extended_auction_enabled",
            "extended_registration_enabled",
            "extended_cancellation_enabled",
        ):
            batch.drop_column(name)
