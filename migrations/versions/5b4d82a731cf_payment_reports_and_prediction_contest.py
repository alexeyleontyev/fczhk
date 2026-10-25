"""Player payment reports and a new prediction contest starting from the sheet totals."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from fczhk.db import UTCDateTime

revision = "5b4d82a731cf"
down_revision = "1c8d7e0f325a"
branch_labels = None
depends_on = None

# Immutable snapshot of column B («Сумма»), downloaded on 2026-10-25.
# Source CSV SHA256: b5fb2d2530515a9fbb98e65fa2d049c3f0f1c21d400f348221ed7054c192040a
SOURCE = "https://docs.google.com/spreadsheets/d/1A9zju1qrvvLqfUXAx1E3hYplLoQ6iLNYLa-vMNOq58A/edit?gid=1925724999"
BASELINE_HALF = (
    ("Абозз", 0),
    ("Андреас", 4),
    ("Валера", 10),
    ("Валя", 9),
    ("Виталик Ястреб", 1),
    ("Виталя пьяный", 10),
    ("Володька", 11),
    ("Гриша", 1),
    ("Даня", 7),
    ("Джанник", 8),
    ("Джикия", 1),
    ("Дима Михей", 8),
    ("Дубр", 18),
    ("Илюха", 12),
    ("Камиль", 2),
    ("Кузьма", 2),
    ("Маэстро", 2),
    ("Михаил Крам", 10),
    ("Миша Банкир", 4),
    ("Нави", 18),
    ("Оникей", 6),
    ("Паша", 16),
    ("Рандом", 0),
    ("Рузаль", 6),
    ("Серега", 4),
    ("Стэс", 2),
    ("Толян", 9),
    ("Чез", 1),
)


def upgrade():
    op.add_column(
        "registrations",
        sa.Column("payment_reported", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "registrations", sa.Column("payment_reported_at", UTCDateTime(), nullable=True)
    )
    # Existing forecasts remain in history but do not contribute to the new contest.
    op.add_column(
        "predictions",
        sa.Column("scoring_version", sa.Integer(), nullable=False, server_default="2"),
    )
    op.execute(sa.text("UPDATE predictions SET scoring_version = 1"))
    baselines = op.create_table(
        "prediction_baselines",
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id"), primary_key=True),
        sa.Column("season", sa.String(40), primary_key=True),
        sa.Column("points_half", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(250), nullable=False),
        sa.CheckConstraint("points_half >= 0"),
    )
    db = op.get_bind()
    people = sa.table(
        "players",
        sa.column("id", sa.Integer()),
        sa.column("alias", sa.String()),
        sa.column("merged_into", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    def normalize(name):
        return name.strip().casefold().replace("ё", "е")

    active = list(
        db.execute(sa.select(people.c.id, people.c.alias).where(people.c.merged_into.is_(None)))
    )
    for alias, points in BASELINE_HALF:
        matches = [pid for pid, name in active if normalize(name) == normalize(alias)]
        if len(matches) > 1:
            raise ValueError(f"Неоднозначное имя в стартовом рейтинге: {alias}")
        if matches:
            pid = matches[0]
        else:
            pid = db.execute(
                people.insert()
                .values(alias=alias, created_at=datetime.now(UTC))
                .returning(people.c.id)
            ).scalar_one()
        db.execute(
            baselines.insert().values(
                player_id=pid, season="2026", points_half=points, source=SOURCE
            )
        )


def downgrade():
    db = op.get_bind()
    if (
        db.execute(
            sa.text("SELECT count(*) FROM registrations WHERE payment_reported = true")
        ).scalar_one()
        or db.execute(
            sa.text("SELECT count(*) FROM predictions WHERE scoring_version = 2")
        ).scalar_one()
    ):
        raise ValueError("Сохранены новые оплаты или прогнозы; downgrade потеряет данные")
    op.drop_table("prediction_baselines")
    with op.batch_alter_table("predictions") as batch:
        batch.drop_column("scoring_version")
    with op.batch_alter_table("registrations") as batch:
        batch.drop_column("payment_reported_at")
        batch.drop_column("payment_reported")
