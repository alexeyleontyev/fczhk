"""Store private collection photos and immutable publication attachments."""

import sqlalchemy as sa
from alembic import op

revision = "b7d8e2a9103f"
down_revision = "a6e91f2c704b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "post_images",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("mime_type", sa.String(30), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("players.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("size > 0 AND size <= 10000000"),
    )
    with op.batch_alter_table(
        "matches", table_args=(sa.CheckConstraint("field_limit >= 2 AND keeper_limit >= 0"),)
    ) as batch:
        batch.add_column(sa.Column("collection_image_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_match_collection_image", "post_images", ["collection_image_id"], ["id"]
        )
    with op.batch_alter_table("publications") as batch:
        batch.add_column(sa.Column("image_id", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_publication_image", "post_images", ["image_id"], ["id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM post_images LIMIT 1")).first():
        raise RuntimeError("Нельзя удалить сохранённые картинки к публикациям")
    with op.batch_alter_table("publications") as batch:
        batch.drop_constraint("fk_publication_image", type_="foreignkey")
        batch.drop_column("image_id")
    with op.batch_alter_table(
        "matches", table_args=(sa.CheckConstraint("field_limit >= 2 AND keeper_limit >= 0"),)
    ) as batch:
        batch.drop_constraint("fk_match_collection_image", type_="foreignkey")
        batch.drop_column("collection_image_id")
    op.drop_table("post_images")
