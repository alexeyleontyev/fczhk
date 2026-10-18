"""Assign existing games to 2026 and allow separately named historical seasons."""

import sqlalchemy as sa
from alembic import op

revision = "f97c3e8d210a"
down_revision = "e6b2f48a913c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "matches", sa.Column("season", sa.String(40), server_default="2026", nullable=False)
    )
    op.create_index("ix_matches_season", "matches", ["season"])


def downgrade():
    different = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM matches WHERE season != '2026'"))
        .scalar_one()
    )
    if different:
        raise ValueError("Есть игры других сезонов; downgrade потеряет разделение статистики")
    op.drop_index("ix_matches_season", table_name="matches")
    op.drop_column("matches", "season")
