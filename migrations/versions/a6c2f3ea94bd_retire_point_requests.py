"""Close bonus point requests and retire their undelivered Telegram messages."""

from alembic import op

revision = "a6c2f3ea94bd"
down_revision = "e1b5c7a93f20"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE point_requests
        SET status = 'cancelled', decided_at = CURRENT_TIMESTAMP
        WHERE status = 'pending'
        """
    )
    op.execute(
        """
        UPDATE publications
        SET status = 'cancelled', error = NULL
        WHERE kind IN ('points_request', 'points_decided')
          AND status IN ('pending', 'sending', 'failed', 'uncertain')
        """
    )


def downgrade():
    # A rollback must never requeue messages or reopen cancelled requests.
    pass
