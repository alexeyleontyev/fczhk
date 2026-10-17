"""Unique player names and own goals with an unknown author."""

import sqlalchemy as sa
from alembic import op

revision = "9c2d8f4a10b7"
down_revision = "8b1d6a0c42ef"
branch_labels = None
depends_on = None


def replace_own_goal_check(expression, name):
    bind = op.get_bind()
    table = sa.Table("result_goals", sa.MetaData(), autoload_with=bind)
    checks = [
        c
        for c in table.constraints
        if isinstance(c, sa.CheckConstraint)
        and "own_goal" in str(c.sqltext)
        and "assist_id" in str(c.sqltext)
    ]
    if any(c.name == name for c in checks):
        return
    if bind.dialect.name == "sqlite":
        for constraint in checks:
            table.constraints.remove(constraint)
        with op.batch_alter_table("result_goals", recreate="always", copy_from=table) as batch:
            batch.create_check_constraint(name, expression)
    else:
        for constraint in checks:
            op.drop_constraint(constraint.name, "result_goals", type_="check")
        op.create_check_constraint(name, "result_goals", expression)


def upgrade():
    bind = op.get_bind()
    duplicates = (
        bind.execute(sa.text("SELECT alias FROM players GROUP BY alias HAVING count(*) > 1"))
        .scalars()
        .all()
    )
    if duplicates:
        raise ValueError(f"Сначала разберите повторяющиеся имена игроков: {duplicates}")
    if "uq_players_alias" not in {i["name"] for i in sa.inspect(bind).get_indexes("players")}:
        op.create_index("uq_players_alias", "players", ["alias"], unique=True)
    replace_own_goal_check("kind <> 'own_goal' OR assist_id IS NULL", "ck_own_goal_no_assist")


def downgrade():
    bind = op.get_bind()
    if bind.scalar(
        sa.text("SELECT count(*) FROM result_goals WHERE kind = 'own_goal' AND author_id IS NULL")
    ):
        raise ValueError("Сначала уточните авторов автоголов: старая схема не допускает NULL")
    replace_own_goal_check(
        "kind <> 'own_goal' OR (author_id IS NOT NULL AND assist_id IS NULL)",
        "ck_own_goal_known_author",
    )
    op.drop_index("uq_players_alias", table_name="players")
