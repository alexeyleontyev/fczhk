"""Archive metadata corrections keep results, identities and original imports intact."""

from datetime import datetime, time

from sqlalchemy import select

from .db import now
from .models import Audit, Match, Publication
from .scheduling import MOSCOW

UNKNOWN_LOCATION = "Не указано в историческом источнике"


def metadata_flags(db, ids):
    if not ids:
        return {}
    imported = set(
        db.scalars(
            select(Audit.match_id).where(
                Audit.match_id.in_(ids), Audit.action == "history.imported"
            )
        )
    )
    # Read only small correction records, not the large raw import payloads.
    known = {}
    for mid, data in db.execute(
        select(Audit.match_id, Audit.data)
        .where(Audit.match_id.in_(ids), Audit.action == "match.archive_details_edited")
        .order_by(Audit.id.desc())
    ):
        known.setdefault(mid, data["new"]["time_known"])
    return {
        mid: dict(historical=mid in imported, time_known=known.get(mid, mid not in imported))
        for mid in ids
    }


def edit_details(db, actor, match, body):
    from .services import DomainError, audit

    if match.status not in ("completed", "cancelled"):
        raise DomainError("Эта форма предназначена для архивной игры", 409)
    day = body.game_day.isoformat()
    if db.scalar(select(Match.id).where(Match.game_day == day, Match.id != match.id)):
        raise DomainError("На эту дату игра уже существует", 409)
    starts = datetime.combine(body.game_day, time.fromisoformat(body.start_time or "00:00"), MOSCOW)
    if body.start_time is None and day == match.game_day:
        starts = (
            match.starts_at
        )  # An unknown time must not silently replace the stored source value.
    if match.status == "completed" and (
        body.game_day > now().astimezone(MOSCOW).date()
        or (body.start_time is not None and starts > now())
    ):
        raise DomainError("Дата и время завершённой игры не могут быть в будущем")
    old = dict(
        game_day=match.game_day,
        starts_at=match.starts_at.isoformat(),
        time_known=metadata_flags(db, [match.id])[match.id]["time_known"],
        location=match.location,
        season=match.season,
    )
    new = dict(
        game_day=day,
        starts_at=starts.isoformat(),
        time_known=body.start_time is not None,
        location=body.location or UNKNOWN_LOCATION,
        season=body.season,
    )
    # Datetimes may have different offsets while representing the same instant.
    if (day, starts, new["time_known"], new["location"], new["season"]) == (
        match.game_day,
        match.starts_at,
        old["time_known"],
        match.location,
        match.season,
    ):
        return
    match.game_day, match.starts_at = day, starts
    match.location, match.season = new["location"], new["season"]
    match.version += 1
    for publication in db.scalars(
        select(Publication).where(
            Publication.match_id == match.id,
            Publication.kind.in_(("teams", "result", "lineup_share")),
            Publication.stale.is_(False),
        )
    ):
        publication.stale = True
        if publication.status == "pending":
            publication.status = "cancelled"
    audit(db, actor, "match.archive_details_edited", match.id, old=old, new=new)
    db.flush()
