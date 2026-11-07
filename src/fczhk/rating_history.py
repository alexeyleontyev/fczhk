"""Daily community aggregates reconstructed from original votes and saved revisions."""

from collections import defaultdict
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import now
from .models import ImportedRating, Player, Rating, RatingHistory
from .ratings import COMMUNITY_RATING_METHOD, catalog_player, trimmed_average

MOSCOW = ZoneInfo("Europe/Moscow")


def daily_history(db: Session, target: int, admin: bool = False) -> dict:
    catalog_player(db, target)
    canonical = {p.id: p.merged_into or p.id for p in db.scalars(select(Player))}
    targets = [pid for pid, resolved in canonical.items() if resolved == target]
    as_of = now()
    events = []
    for row in db.scalars(
        select(ImportedRating).where(ImportedRating.player_id.in_(targets))
    ):
        if canonical[row.author_id] == target:
            continue
        events.append((
            row.imported_at, 0, row.id, 0, canonical[row.author_id], row.position,
            row.attack_milli, row.defense_milli, row.imported_at,
        ))

    # One statement captures current values and their revisions together.
    rows = {}
    revisions = defaultdict(list)
    for row, history in db.execute(
        select(Rating, RatingHistory)
        .outerjoin(RatingHistory, RatingHistory.rating_id == Rating.id)
        .where(Rating.player_id.in_(targets))
        .order_by(RatingHistory.revision, RatingHistory.id)
    ):
        rows[row.id] = row
        if history is not None:
            revisions[row.id].append(history)
    for row in rows.values():
        author = canonical[row.author_id]
        if author == target:
            continue
        history = revisions[row.id]
        for revision in history:
            # Match aggregate()'s precedence after linked cards share one author/target.
            latest = revision.revision == row.revision
            events.append((
                revision.created_at, 1, row.id, revision.revision, author, row.position,
                revision.attack * 100 if revision.attack is not None and not revision.withdrawn else None,
                revision.defense * 100 if not revision.withdrawn else None,
                row.updated_at if latest else revision.created_at,
            ))
        if not history or (
            history[-1].revision, history[-1].attack, history[-1].defense, history[-1].withdrawn
        ) != (row.revision, row.attack, row.defense, row.withdrawn):
            # Older imports/fixtures may only have a current vote. Do not invent its past.
            events.append((
                row.updated_at, 1, row.id, row.revision, author, row.position,
                row.attack * 100 if row.attack is not None and not row.withdrawn else None,
                row.defense * 100 if not row.withdrawn else None, row.updated_at,
            ))

    imported, application = {}, {}
    days = {"field": {}, "keeper": {}}
    changes = defaultdict(int)
    for at, kind, row_id, revision, author, position, attack, defense, precedence in sorted(events):
        if at > as_of:
            continue
        key = author, position
        if kind == 0:
            if key not in imported or row_id > imported[key][0]:
                imported[key] = row_id, attack, defense
        else:
            rank = precedence, row_id, revision
            if key not in application or rank >= application[key][0]:
                application[key] = rank, attack, defense
        votes = {k: value[1:] for k, value in imported.items() if k[1] == position}
        votes.update({k: value[1:] for k, value in application.items() if k[1] == position})
        votes = {k: v for k, v in votes.items() if v[1] is not None}
        attacks = [value[0] for value in votes.values() if value[0] is not None]
        defenses = [value[1] for value in votes.values()]
        a = trimmed_average(attacks) if position == "field" else None
        d = trimmed_average(defenses)
        date = at.astimezone(MOSCOW).date().isoformat()
        point = dict(
            date=date, at=at,
            attack=float(a) if a is not None else None,
            defense=float(d) if d is not None else None,
        )
        if admin:
            changes[position, date] += kind
            point.update(count=len(defenses), changes=changes[position, date])
        # This also folds an entire imported sheet into one daily starting point.
        days[position][date] = point
    return dict(
        as_of=as_of, timezone="Europe/Moscow", method=COMMUNITY_RATING_METHOD,
        **{position: list(points.values()) for position, points in days.items()},
    )
