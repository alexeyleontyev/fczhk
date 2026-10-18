"""Small, batched archive projections; full rosters belong to match detail."""

from sqlalchemy import case, func, select

from .models import Audit, MatchResult, Registration, ResultGoal, ResultParticipant
from .services import selection


def summaries(db, matches):
    ids = [m.id for m in matches]
    if not ids:
        return []
    historical = set(
        db.scalars(
            select(Audit.match_id).where(
                Audit.match_id.in_(ids), Audit.action == "history.imported"
            )
        )
    )
    results = {
        r.match_id: r for r in db.scalars(select(MatchResult).where(MatchResult.match_id.in_(ids)))
    }
    counts = dict(
        db.execute(
            select(ResultParticipant.match_id, func.count())
            .where(ResultParticipant.match_id.in_(ids))
            .group_by(ResultParticipant.match_id)
        ).all()
    )
    scores = {
        mid: {"white": white, "black": black}
        for mid, white, black in db.execute(
            select(
                ResultGoal.match_id,
                func.sum(case((ResultGoal.team == "white", 1), else_=0)),
                func.sum(case((ResultGoal.team == "black", 1), else_=0)),
            )
            .where(ResultGoal.match_id.in_(ids))
            .group_by(ResultGoal.match_id)
        )
    }
    registrations = {}
    for row in db.scalars(
        select(Registration)
        .where(Registration.match_id.in_(ids), Registration.active.is_(True))
        .order_by(Registration.registered_at, Registration.id)
    ):
        registrations.setdefault(row.match_id, []).append(row)
    return [
        dict(
            id=m.id,
            starts_at=m.starts_at,
            game_day=m.game_day,
            season=m.season,
            location=m.location,
            historical=m.id in historical,
            status=m.status,
            version=m.version,
            participant_count=counts[m.id]
            if m.id in counts
            else len(selection(m, registrations.get(m.id, []))),
            result=dict(
                completed=results[m.id].completed, score=scores.get(m.id, {"white": 0, "black": 0})
            )
            if m.id in results
            else None,
        )
        for m in matches
    ]
