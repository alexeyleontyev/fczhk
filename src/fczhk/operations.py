"""Operational health and maintenance, with no credentials in responses or logs."""

from datetime import timedelta

from sqlalchemy import delete, func, or_, select

from .db import now
from .models import LoginSession, Match, Publication, ServiceHeartbeat


def heartbeat(factory, error=None):
    with factory() as db, db.begin():
        row = db.scalar(
            select(ServiceHeartbeat).where(ServiceHeartbeat.name == "worker").with_for_update()
        )
        if row is None:
            row = ServiceHeartbeat(name="worker")
            db.add(row)
        row.checked_at = now()
        row.error = error
        if error is None:
            row.succeeded_at = now()


def cleanup_sessions(factory):
    with factory() as db, db.begin():
        return db.execute(delete(LoginSession).where(LoginSession.expires_at <= now())).rowcount


def status(db, cfg):
    at = now()
    row = db.get(ServiceHeartbeat, "worker")
    age = (at - row.succeeded_at).total_seconds() if row and row.succeeded_at else None
    counts = dict(
        db.execute(select(Publication.status, func.count()).group_by(Publication.status)).all()
    )
    oldest = db.scalar(
        select(func.min(Publication.next_attempt_at)).where(
            Publication.status == "pending", Publication.stale.is_(False)
        )
    )
    queue_age = max(0, (at - oldest).total_seconds()) if oldest else 0
    sending_stuck = db.scalar(
        select(func.count())
        .select_from(Publication)
        .where(Publication.status == "sending", Publication.claimed_at < at - timedelta(minutes=5))
    )
    problems = counts.get("failed", 0) + counts.get("uncertain", 0)
    stale_errors = db.scalar(
        select(func.count())
        .select_from(Publication)
        .where(
            Publication.stale.is_(True),
            Publication.stale_marked.is_(False),
            Publication.status == "sent",
            Publication.error.startswith("Не удалось пометить"),
        )
    )
    worker_ok = age is not None and age < cfg.worker_stale_seconds and row.error is None
    return dict(
        status="ok"
        if worker_ok
        and not problems
        and not stale_errors
        and not sending_stuck
        and queue_age < cfg.publication_stale_seconds
        else "degraded",
        worker=dict(
            healthy=worker_ok,
            age_seconds=age,
            checked_at=row.checked_at if row else None,
            succeeded_at=row.succeeded_at if row else None,
            error=row.error if row else None,
        ),
        publications=counts,
        queue_age_seconds=queue_age,
        stuck_sending=sending_stuck,
        stale_mark_errors=stale_errors,
    )


def publication_problems(db):
    return [
        dict(
            id=p.id,
            match_id=p.match_id,
            game_day=day,
            kind=p.kind,
            status=p.status,
            stale=p.stale,
            stale_marked=p.stale_marked,
            error=p.error,
            attempts=p.attempts,
            message_ids=p.message_ids,
            next_attempt_at=p.next_attempt_at,
        )
        for p, day in db.execute(
            select(Publication, Match.game_day)
            .join(Match)
            .where(
                or_(
                    Publication.status.in_(["failed", "uncertain", "pending", "sending"]),
                    (
                        Publication.stale.is_(True)
                        & Publication.stale_marked.is_(False)
                        & Publication.status.in_(["sent", "demo"])
                    ),
                )
            )
            .order_by(Publication.id.desc())
            .limit(100)
        )
    ]
