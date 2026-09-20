import hashlib
import json
from fractions import Fraction

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import balancing
from .db import now
from .models import (
    BalanceRun,
    Match,
    MatchRating,
    Player,
    Rating,
    RatingHistory,
    RatingState,
    Registration,
    TeamRatingDraft,
    TeamRatingSnapshot,
    TeamSnapshot,
)
from .schemas import BalanceSettings, RatingValues
from .services import DomainError, audit, entries


def lock_ratings(db: Session):
    state = db.scalar(
        select(RatingState)
        .where(RatingState.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state is None:
        raise DomainError("Нужна миграция базы рейтингов: uv run fczhk migrate", 503)
    state.revision += 1
    db.flush()


def registered_player(db: Session, player_id: int) -> Player:
    p = db.get(Player, player_id)
    if not p or p.telegram_id is None or p.merged_into:
        raise DomainError("Оценивать можно только зарегистрированных игроков", 404)
    return p


def aggregate(db: Session, ids: list[int]) -> dict:
    rows = db.execute(
        select(
            Rating.player_id,
            Rating.position,
            func.sum(Rating.attack),
            func.sum(Rating.defense),
            func.count(Rating.id),
        )
        .where(Rating.player_id.in_(ids))
        .group_by(Rating.player_id, Rating.position)
    )
    return {
        (pid, pos): (Fraction(a, n * 10) if a is not None else None, Fraction(d, n * 10), n)
        for pid, pos, a, d, n in rows
    }


def public_averages(db: Session, ids: list[int], admin=False) -> dict:
    scores = aggregate(db, ids)
    result = {}
    for pid in ids:
        result[pid] = {}
        for pos in ("field", "keeper"):
            a, d, n = scores.get((pid, pos), (None, None, 0))
            row = dict(
                attack=float(a) if a is not None else None,
                defense=float(d) if d is not None else None,
            )
            if admin:
                row["count"] = n
            result[pid][pos] = row
    return result


def rating_data(row: Rating | RatingHistory | None) -> dict | None:
    if row is None:
        return None
    return dict(
        attack=row.attack / 10 if row.attack is not None else None,
        defense=row.defense / 10,
        revision=row.revision,
        at=row.updated_at if isinstance(row, Rating) else row.created_at,
    )


def review_data(db: Session, actor: int, target: int, position: str, admin: bool) -> dict:
    registered_player(db, target)
    own = db.scalar(
        select(Rating).where(
            Rating.author_id == actor, Rating.player_id == target, Rating.position == position
        )
    )
    result = dict(
        own=rating_data(own), averages=public_averages(db, [target], admin)[target][position]
    )
    if admin:
        reviews = []
        for rating, author in db.execute(
            select(Rating, Player)
            .join(Player, Player.id == Rating.author_id)
            .where(Rating.player_id == target, Rating.position == position)
            .order_by(Rating.id)
        ):
            history = list(
                db.scalars(
                    select(RatingHistory)
                    .where(RatingHistory.rating_id == rating.id)
                    .order_by(RatingHistory.revision.desc())
                )
            )
            reviews.append(
                dict(
                    author_id=author.id,
                    author=author.alias,
                    **rating_data(rating),
                    history=[rating_data(h) for h in history],
                )
            )
        result["reviews"] = reviews
    return result


def save_rating(db: Session, actor: int, target: int, body):
    lock_ratings(db)
    registered_player(db, actor)
    registered_player(db, target)
    if actor == target:
        raise DomainError("Нельзя оценивать себя")
    row = db.scalar(
        select(Rating)
        .where(
            Rating.author_id == actor, Rating.player_id == target, Rating.position == body.position
        )
        .execution_options(populate_existing=True)
    )
    if body.revision != (row.revision if row else 0):
        raise DomainError("Ваша оценка уже изменена. Откройте карточку заново.", 409)
    if row and row.attack == body.attack and row.defense == body.defense:
        return
    if row is None:
        row = Rating(
            author_id=actor,
            player_id=target,
            position=body.position,
            attack=body.attack,
            defense=body.defense,
            revision=1,
        )
        db.add(row)
    else:
        row.attack, row.defense = body.attack, body.defense
        row.revision += 1
    row.updated_at = now()
    db.flush()
    db.add(
        RatingHistory(
            rating_id=row.id, revision=row.revision, attack=row.attack, defense=row.defense
        )
    )
    audit(
        db, actor, "rating.saved", player_id=target, position=body.position, revision=row.revision
    )
    db.flush()


def set_temporary(db: Session, actor: int, match: Match, reg: Registration, body: RatingValues):
    lock_ratings(db)
    # The API may have loaded the guest card before a concurrent link committed.
    db.refresh(reg)
    if not reg.active or reg.position != body.position:
        raise DomainError("Временная оценка должна соответствовать активной заявке и амплуа")
    if match.status == "approved":
        raise DomainError(
            "Состав уже утвержден. Сначала перейдите к ручному распределению или выберите новый вариант."
        )
    if (reg.player_id, reg.position) in aggregate(db, [reg.player_id]):
        raise DomainError("Есть оценки сообщества. Подменять их временным рейтингом нельзя.", 409)
    row = db.get(MatchRating, reg.id)
    old = dict(attack=row.attack, defense=row.defense, position=row.position) if row else None
    if row is None:
        row = MatchRating(
            registration_id=reg.id,
            actor_id=actor,
            position=body.position,
            attack=body.attack,
            defense=body.defense,
            revision=1,
        )
        db.add(row)
    else:
        row.position, row.attack, row.defense = body.position, body.attack, body.defense
        row.actor_id, row.updated_at = actor, now()
        row.revision += 1
    match.version += 1
    audit(
        db,
        actor,
        "rating.temporary_saved",
        match.id,
        registration_id=reg.id,
        old=old,
        new=dict(attack=body.attack, defense=body.defense, position=body.position),
        unit="tenths",
    )
    db.flush()


def effective(db: Session, regs: list[Registration]) -> dict[int, dict]:
    scores = aggregate(db, [r.player_id for r in regs])
    temps = {
        t.registration_id: t
        for t in db.scalars(
            select(MatchRating).where(MatchRating.registration_id.in_([r.id for r in regs]))
        )
    }
    result = {}
    for r in regs:
        a, d, _ = scores.get((r.player_id, r.position), (None, None, 0))
        source = "community" if d is not None else "missing"
        fallback = temps.get(r.id)
        if source == "missing" and fallback and fallback.position == r.position:
            a = Fraction(fallback.attack, 10) if fallback.attack is not None else None
            d = Fraction(fallback.defense, 10)
            source = "temporary"
        result[r.id] = dict(
            registration_id=r.id,
            player_id=r.player_id,
            position=r.position,
            attack_fraction=[a.numerator, a.denominator] if a is not None else None,
            defense_fraction=[d.numerator, d.denominator] if d is not None else None,
            attack=float(a) if a is not None else None,
            defense=float(d) if d is not None else None,
            source=source,
        )
    return result


def inputs_for(db: Session, match: Match) -> tuple[list[dict], str]:
    field = [r for r in entries(db, match.id) if r.selected and r.position == "field"]
    ratings = effective(db, field)
    inputs = [ratings[r.id] for r in sorted(field, key=lambda r: r.id)]
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    # Names are display-only; changing an alias doesn't silently invalidate a rating snapshot.
    for row in inputs:
        row["alias"] = db.get(Player, row["player_id"]).alias
    return inputs, fingerprint


def create_run(db: Session, actor: int, match: Match, settings: BalanceSettings) -> BalanceRun:
    if match.status not in ("finalized", "approved"):
        raise DomainError("Сначала финализируйте список")
    lock_ratings(db)
    inputs, fingerprint = inputs_for(db, match)
    missing = [r["alias"] for r in inputs if r["source"] == "missing"]
    if missing:
        raise DomainError("Нужны рейтинги полевых: " + ", ".join(missing))
    try:
        result = balancing.generate(inputs, settings)
    except ValueError as exc:
        raise DomainError(str(exc)) from exc
    run = BalanceRun(
        match_id=match.id,
        actor_id=actor,
        roster_version=match.roster_version,
        fingerprint=fingerprint,
        inputs=inputs,
        settings=settings.model_dump(mode="json"),
        result=result,
    )
    db.add(run)
    db.flush()
    audit(
        db,
        actor,
        "balance.generated",
        match.id,
        run_id=run.id,
        settings=run.settings,
        variants=len(result["variants"]),
    )
    return run


def run_data(db: Session, match: Match, run: BalanceRun) -> dict:
    _, fingerprint = inputs_for(db, match)
    return dict(
        id=run.id,
        roster_version=run.roster_version,
        inputs=run.inputs,
        settings=run.settings,
        result=run.result,
        created_at=run.created_at,
        stale=run.roster_version != match.roster_version or fingerprint != run.fingerprint,
    )


def apply_run(db: Session, actor: int, match: Match, run_id: int, variant: int):
    from .services import invalidate

    if match.status not in ("finalized", "approved"):
        raise DomainError("Сначала финализируйте список")
    lock_ratings(db)
    run = db.get(BalanceRun, run_id)
    if run is None or run.match_id != match.id:
        raise DomainError("Расчет не найден", 404)
    if run_data(db, match, run)["stale"]:
        raise DomainError("Список или рейтинги изменились. Рассчитайте варианты заново.", 409)
    if variant >= len(run.result["variants"]):
        raise DomainError("Вариант не найден", 404)
    regs = [r for r in entries(db, match.id) if r.selected]
    keepers = {r.id: r.team for r in regs if r.position == "keeper"}
    assignments = {int(k): v for k, v in run.result["variants"][variant]["assignments"].items()}
    invalidate(db, match, roster_changed=False)
    for r in regs:
        r.team = assignments[r.id] if r.position == "field" else keepers.get(r.id)
    draft = db.get(TeamRatingDraft, match.id)
    if draft is None:
        draft = TeamRatingDraft(match_id=match.id, run_id=run.id, variant=variant)
        db.add(draft)
    draft.run_id, draft.variant, draft.edited = run.id, variant, False
    match.version += 1
    audit(db, actor, "balance.applied", match.id, run_id=run.id, variant=variant)
    db.flush()


def team_rating_data(db: Session, match: Match, approval=False) -> dict:
    if match.status in ("approved", "completed") and not approval:
        snapshot = db.scalar(
            select(TeamRatingSnapshot)
            .join(TeamSnapshot, TeamSnapshot.id == TeamRatingSnapshot.snapshot_id)
            .where(
                TeamSnapshot.match_id == match.id, TeamSnapshot.version == match.approved_version
            )
        )
        if snapshot:
            return {**snapshot.data, "frozen": True, "stale": False}
        # MVP 1 historical teams have no rating snapshot; never retrofit today's ratings.
        return dict(summary=None, inputs=[], method="legacy-manual", frozen=True, stale=False)
    inputs, fingerprint = inputs_for(db, match)
    draft = db.get(TeamRatingDraft, match.id)
    run = db.get(BalanceRun, draft.run_id) if draft else None
    stale = bool(
        run and (run.fingerprint != fingerprint or run.roster_version != match.roster_version)
    )
    if approval and stale:
        raise DomainError(
            "Рейтинги изменились после расчета. Пересчитайте варианты или начните ручное распределение заново.",
            409,
        )
    if run:
        inputs = run.inputs
    assignments = {r.id: r.team for r in entries(db, match.id) if r.selected}
    return dict(
        inputs=inputs,
        fingerprint=run.fingerprint if run else fingerprint,
        roster_version=match.roster_version,
        method=("auto-edited" if draft.edited else "auto") if draft else "manual",
        run_id=run.id if run else None,
        variant=draft.variant if draft else None,
        settings=run.settings if run else None,
        summary=balancing.summary(inputs, assignments),
        frozen=False,
        stale=stale,
    )


def public_team_data(db: Session, match: Match) -> dict:
    data = team_rating_data(db, match)
    return {
        key: data.get(key) for key in ("summary", "method", "frozen", "stale", "run_id", "variant")
    }
