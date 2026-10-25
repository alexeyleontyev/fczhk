"""Refresh sheet totals and add historical prediction counts."""

import sqlalchemy as sa
from alembic import op

revision = "9f0a4b7c2d61"
down_revision = "5b4d82a731cf"
branch_labels = None
depends_on = None

SOURCE = "https://docs.google.com/spreadsheets/d/1A9zju1qrvvLqfUXAx1E3hYplLoQ6iLNYLa-vMNOq58A/edit?gid=1925724999"
# Column «Сумма» and nonempty «Ставка» cells, including the newly added last column.
# Snapshot 2026-10-25, CSV SHA256 e9e15e0bcf642b47135b23bbb7e0a75594290945715cb5c390d0ffcef5b22e5e.
# Repeated date headers are distinct columns, not duplicate forecasts.
SNAPSHOT = (
    ("Абозз", 0, 1),
    ("Андреас", 8, 5),
    ("Валера", 10, 8),
    ("Валя", 9, 6),
    ("Виталик Ястреб", 1, 4),
    ("Виталя пьяный", 10, 5),
    ("Володька", 13, 7),
    ("Гриша", 1, 1),
    ("Даня", 11, 7),
    ("Джанник", 8, 5),
    ("Джикия", 1, 1),
    ("Дима Михей", 8, 7),
    ("Дубр", 18, 8),
    ("Илюха", 16, 8),
    ("Камиль", 6, 6),
    ("Кузьма", 6, 6),
    ("Маэстро", 2, 1),
    ("Михаил Крам", 14, 7),
    ("Миша Банкир", 4, 2),
    ("Нави", 22, 8),
    ("Оникей", 6, 1),
    ("Паша", 17, 7),
    ("Рандом", 0, 1),
    ("Рузаль", 6, 5),
    ("Серега", 4, 3),
    ("Стэс", 2, 1),
    ("Толян", 9, 8),
    ("Чез", 2, 4),
)


def upgrade():
    db = op.get_bind()
    players = sa.table("players", sa.column("id"), sa.column("alias"), sa.column("merged_into"))
    baseline = sa.table(
        "prediction_baselines",
        sa.column("player_id"),
        sa.column("season"),
        sa.column("points_half"),
        sa.column("predictions_count"),
        sa.column("source"),
    )
    audits = sa.table(
        "audit", sa.column("actor_id"), sa.column("action"), sa.column("data", sa.JSON())
    )
    people = {row.id: row for row in db.execute(sa.select(players))}
    baseline_ids = set(
        db.scalars(sa.select(baseline.c.player_id).where(baseline.c.season == "2026"))
    )
    aliases = {}

    def remember(alias, pid):
        if isinstance(alias, str) and pid in people:
            aliases.setdefault(" ".join(alias.casefold().replace("ё", "е").split()), set()).add(pid)

    def canonical(pid):
        seen = set()
        while people[pid].merged_into is not None:
            if pid in seen:
                raise ValueError("Цикл связей игроков в истории прогнозов")
            seen.add(pid)
            pid = people[pid].merged_into
        return pid

    for pid, player in people.items():
        remember(player.alias, pid)
    for row in db.execute(
        sa.select(audits).where(audits.c.action.in_(["guest.linked", "player.renamed"]))
    ):
        if row.action == "guest.linked":
            remember(row.data.get("guest_alias"), row.data.get("guest_id"))
            remember(row.data.get("previous_target_alias"), row.data.get("target_id"))
        else:
            remember(row.data.get("old"), row.data.get("player_id", row.actor_id))
    used = set()
    updates = []
    for alias, half_points, count in SNAPSHOT:
        candidates = aliases.get(" ".join(alias.casefold().replace("ё", "е").split()), set())
        matches = baseline_ids & candidates
        if not matches:
            linked = {canonical(pid) for pid in candidates}
            matches = {pid for pid in baseline_ids if canonical(pid) in linked}
        if len(matches) != 1 or used & matches:
            raise ValueError(f"Неоднозначная или отсутствующая история прогнозов: {alias}")
        pid = matches.pop()
        used.add(pid)
        updates.append((pid, half_points, count))
    with op.batch_alter_table(
        "prediction_baselines", table_args=(sa.CheckConstraint("points_half >= 0"),)
    ) as batch:
        batch.add_column(
            sa.Column("predictions_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint("ck_prediction_baseline_count", "predictions_count >= 0")
    for pid, half_points, count in updates:
        db.execute(
            baseline.update()
            .where(baseline.c.player_id == pid, baseline.c.season == "2026")
            .values(points_half=half_points, predictions_count=count, source=SOURCE)
        )


def downgrade():
    # Counts are reproducible from the immutable snapshot. Keep the refreshed points.
    with op.batch_alter_table(
        "prediction_baselines", table_args=(sa.CheckConstraint("points_half >= 0"),)
    ) as batch:
        batch.drop_constraint("ck_prediction_baseline_count", type_="check")
        batch.drop_column("predictions_count")
