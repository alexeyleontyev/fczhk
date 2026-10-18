"""Configure the weekly collection opening and game day without changing existing games."""

import sqlalchemy as sa
from alembic import op

revision = "e6b2f48a913c"
down_revision = "a71f4b6d2e90"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("game_template") as batch:
        batch.add_column(
            sa.Column("opening_weekday", sa.Integer(), server_default=sa.text("1"), nullable=False)
        )
        batch.add_column(
            sa.Column("opening_time", sa.String(5), server_default="12:00", nullable=False)
        )
        batch.add_column(
            sa.Column("game_weekday", sa.Integer(), server_default=sa.text("4"), nullable=False)
        )
        batch.create_check_constraint(
            "ck_template_opening_weekday", "opening_weekday BETWEEN 0 AND 6"
        )
        batch.create_check_constraint("ck_template_game_weekday", "game_weekday BETWEEN 0 AND 6")
        batch.create_check_constraint(
            "ck_template_opening_before_game",
            "opening_weekday != game_weekday OR opening_time < start_time",
        )


def downgrade():
    customized = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM game_template WHERE opening_weekday != 1 OR opening_time != '12:00' OR game_weekday != 4"
            )
        )
        .scalar_one()
    )
    if customized:
        raise ValueError("Настраиваемое расписание изменено; downgrade потеряет настройки")
    with op.batch_alter_table("game_template") as batch:
        batch.drop_constraint("ck_template_opening_before_game", type_="check")
        batch.drop_constraint("ck_template_game_weekday", type_="check")
        batch.drop_constraint("ck_template_opening_weekday", type_="check")
        batch.drop_column("game_weekday")
        batch.drop_column("opening_time")
        batch.drop_column("opening_weekday")
