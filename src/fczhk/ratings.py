import hashlib
import json
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import balancing, game_balancing, game_ratings
from .db import now
from .models import (
    BalanceRun,
    ImportedRating,
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
        raise DomainError("Оценки может оставлять только зарегистрированный игрок", 404)
    return p


def catalog_player(db: Session, player_id: int) -> Player:
    p = db.get(Player, player_id)
    if not p or p.merged_into:
        raise DomainError("Игрок не найден", 404)
    if p.shared_keeper:
        raise DomainError("У общей карточки вратаря нет персональных оценок")
    return p


def own_rating(db: Session, actor: int, target_ids: list[int], position: str):
    return db.scalar(
        select(Rating)
        .where(
            Rating.author_id == actor,
            Rating.player_id.in_(target_ids),
            Rating.position == position,
        )
        .order_by(Rating.updated_at.desc(), Rating.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def reconcile_linked_ratings(db: Session, target_ids: list[int]):
    groups = {}
    for row in db.scalars(
        select(Rating)
        .where(Rating.player_id.in_(target_ids))
        .order_by(Rating.updated_at, Rating.id)
    ):
        groups.setdefault((row.author_id, row.position), []).append(row)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        # Invalidate edits opened before two separately rated cards became one identity.
        latest = rows[-1]
        latest.revision = max(row.revision for row in rows) + 1
        latest.updated_at = now()
        db.add(
            RatingHistory(
                rating_id=latest.id,
                revision=latest.revision,
                attack=latest.attack,
                defense=latest.defense,
            )
        )


def aggregate(db: Session, ids: list[int]) -> dict:
    if not ids:
        return {}
    canonical = {p.id: p.merged_into or p.id for p in db.scalars(select(Player))}
    relevant = [pid for pid, target in canonical.items() if target in ids]
    current = list(
        db.scalars(
            select(Rating)
            .where(Rating.player_id.in_(relevant))
            .order_by(Rating.updated_at, Rating.id)
        )
    )
    imported = list(
        db.scalars(
            select(ImportedRating)
            .where(ImportedRating.player_id.in_(relevant))
            .order_by(ImportedRating.id)
        )
    )
    # Guest links and later app edits must not turn one person's vote into two.
    votes = {}
    for row in imported:
        key = (canonical[row.author_id], canonical[row.player_id], row.position)
        if key[0] != key[1]:
            votes[key] = (row.attack_milli, row.defense_milli)
    for row in current:
        key = (canonical[row.author_id], canonical[row.player_id], row.position)
        if key[0] != key[1]:
            votes[key] = (row.attack * 100 if row.attack is not None else None, row.defense * 100)
    totals = {}
    for (_, pid, pos), (attack, defense) in votes.items():
        values = totals.setdefault((pid, pos), [0, 0, 0])
        if attack is not None:
            values[0] += attack
        values[1] += defense
        values[2] += 1
    return {
        key: (
            Fraction(attack, count * 1000) if key[1] == "field" else None,
            Fraction(defense, count * 1000),
            count,
        )
        for key, (attack, defense, count) in totals.items()
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


def community_leaderboards(db: Session) -> dict:
    """Current mean community scores, excluding unrated positions."""
    people = [
        p
        for p in db.scalars(select(Player).where(Player.merged_into.is_(None)))
        if not p.shared_keeper
    ]
    scores = aggregate(db, [p.id for p in people])
    boards = {}
    for metric, position in (
        ("field_total", "field"),
        ("field_attack", "field"),
        ("field_defense", "field"),
        ("keeper_defense", "keeper"),
    ):
        rows = []
        for player in people:
            attack, defense, _ = scores.get((player.id, position), (None, None, 0))
            if defense is None:
                continue
            value = {
                "field_total": attack + defense if attack is not None else None,
                "field_attack": attack,
                "field_defense": defense,
                "keeper_defense": defense,
            }[metric]
            if value is not None:
                rows.append(
                    dict(
                        player_id=player.id,
                        alias=player.alias,
                        score=float(value),
                        attack=float(attack) if attack is not None else None,
                        defense=float(defense),
                    )
                )
        boards[metric] = sorted(
            rows, key=lambda row: (-row["score"], row["alias"], row["player_id"])
        )
    return {"boards": boards}


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
    catalog_player(db, target)
    canonical = {p.id: p.merged_into or p.id for p in db.scalars(select(Player))}
    target_ids = [pid for pid, resolved in canonical.items() if resolved == target]
    own = own_rating(db, actor, target_ids, position)
    result = dict(
        own=rating_data(own), averages=public_averages(db, [target], admin)[target][position]
    )
    imported = list(
        db.scalars(
            select(ImportedRating)
            .where(ImportedRating.player_id.in_(target_ids), ImportedRating.position == position)
            .order_by(ImportedRating.id)
        )
    )
    if own is None:
        previous = next(
            (row for row in reversed(imported) if canonical[row.author_id] == actor), None
        )
        if previous:
            result["imported_own"] = dict(
                attack=previous.attack_milli / 1000,
                defense=previous.defense_milli / 1000,
            )
    if admin:
        people = {p.id: p for p in db.scalars(select(Player))}
        reviews = {}
        for row in imported:
            author_id = canonical[row.author_id]
            if author_id != target:
                reviews[author_id] = dict(
                    author_id=author_id,
                    author=people[author_id].alias,
                    attack=row.attack_milli / 1000,
                    defense=row.defense_milli / 1000,
                    revision=0,
                    at=row.imported_at,
                    history=[],
                    source="sheet",
                )
        for rating, author in db.execute(
            select(Rating, Player)
            .join(Player, Player.id == Rating.author_id)
            .where(Rating.player_id.in_(target_ids), Rating.position == position)
            .order_by(Rating.updated_at, Rating.id)
        ):
            history = list(
                db.scalars(
                    select(RatingHistory)
                    .where(RatingHistory.rating_id == rating.id)
                    .order_by(RatingHistory.revision.desc())
                )
            )
            author_id = canonical[author.id]
            reviews[author_id] = dict(
                author_id=author_id,
                author=people[author_id].alias,
                **rating_data(rating),
                history=[rating_data(h) for h in history],
            )
        result["reviews"] = sorted(
            reviews.values(), key=lambda row: (row["author"], row["author_id"])
        )
    return result


def save_rating(db: Session, actor: int, target: int, body):
    lock_ratings(db)
    registered_player(db, actor)
    catalog_player(db, target)
    if actor == target:
        raise DomainError("Нельзя оценивать себя")
    target_ids = [target, *db.scalars(select(Player.id).where(Player.merged_into == target))]
    row = own_rating(db, actor, target_ids, body.position)
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
    from .services import ensure_pregame

    ensure_pregame(db, match)
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
        community = (
            dict(attack=float(a) if a is not None else None, defense=float(d))
            if d is not None
            else None
        )
        fallback = temps.get(r.id)
        temporary = (
            dict(
                attack=fallback.attack / 10 if fallback.attack is not None else None,
                defense=fallback.defense / 10,
            )
            if fallback and fallback.position == r.position
            else None
        )
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
            community=community,
            temporary=temporary,
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


def game_inputs_for(db: Session, match: Match) -> tuple[list[dict], str]:
    inputs, _ = inputs_for(db, match)
    replayed = game_ratings.replay(db, before_day=match.game_day)
    for row in inputs:
        rating = replayed["players"].get(row["player_id"])
        row["game_mu"] = rating["mu"] if rating else 25.0
        row["game_sigma"] = rating["sigma"] if rating else 25.0 / 3.0
        row["game_count"] = rating["games"] if rating else 0
    prior = [
        (game.match_id, game.day, game.white, game.black, game.score)
        for game in game_ratings.history(db)
        if game.day < match.game_day
    ]
    key = {
        "model": game_ratings.MODEL_VERSION,
        "margin": 0.0,
        "game_day": match.game_day,
        "prior": prior,
        "roster": [
            (row["registration_id"], row["player_id"], row["game_mu"], row["game_sigma"])
            for row in inputs
        ],
    }
    fingerprint = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    return inputs, fingerprint


def create_run(db: Session, actor: int, match: Match, settings: BalanceSettings) -> BalanceRun:
    if match.status not in ("finalized", "approved"):
        raise DomainError("Сначала финализируйте список")
    lock_ratings(db)
    inputs, fingerprint = (
        game_inputs_for(db, match) if settings.method == "game" else inputs_for(db, match)
    )
    if settings.method == "community":
        missing = [r["alias"] for r in inputs if r["source"] == "missing"]
        if missing:
            raise DomainError("Нужны рейтинги полевых: " + ", ".join(missing))
    try:
        result = (
            game_balancing.generate(inputs, settings)
            if settings.method == "game"
            else balancing.generate(inputs, settings)
        )
        if settings.method == "game":
            result["rating_model_version"] = game_ratings.MODEL_VERSION
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
    _, fingerprint = (
        game_inputs_for(db, match)
        if run.settings.get("method") == "game"
        else inputs_for(db, match)
    )
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


def strength_summary(inputs, assignments):
    def totals(rows):
        values = []
        for row in rows:
            if row["defense"] is None or (row["position"] == "field" and row["attack"] is None):
                continue
            value = Fraction(str(row["defense"]))
            if row["position"] == "field":
                value += Fraction(str(row["attack"]))
            values.append(value)
        rated_total = float(sum(values, Fraction()))
        return dict(
            total=rated_total if len(values) == len(rows) else None,
            rated_total=rated_total,
            rated=len(values),
            count=len(rows),
        )

    return {
        **totals(inputs),
        "teams": {
            team: totals([row for row in inputs if assignments.get(row["registration_id"]) == team])
            for team in ("white", "black")
        },
    }


def team_rating_data(db: Session, match: Match, approval=False) -> dict:
    from .auctions import formation_method

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
        return dict(
            summary=None, strength=None, inputs=[], method="legacy-manual", frozen=True, stale=False
        )
    inputs, fingerprint = inputs_for(db, match)
    strength_inputs = inputs
    draft = db.get(TeamRatingDraft, match.id)
    run = db.get(BalanceRun, draft.run_id) if draft else None
    if run and run.settings.get("method") == "game":
        _, fingerprint = game_inputs_for(db, match)
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
    regs = [r for r in entries(db, match.id) if r.selected]
    assignments = {r.id: r.team for r in regs}
    keepers = effective(db, [r for r in regs if r.position == "keeper"])
    game_summary = (
        game_balancing.game_summary(inputs, assignments)
        if draft and run and run.settings.get("method") == "game"
        else None
    )
    return dict(
        inputs=inputs,
        fingerprint=run.fingerprint if run else fingerprint,
        roster_version=match.roster_version,
        method=("auto-game-edited" if draft.edited else "auto-game")
        if draft and run and run.settings.get("method") == "game"
        else ("auto-edited" if draft.edited else "auto")
        if draft
        else formation_method(db, match, assignments),
        run_id=run.id if run else None,
        variant=draft.variant if draft else None,
        settings=run.settings if run else None,
        summary=balancing.summary(inputs, assignments),
        strength=strength_summary([*strength_inputs, *keepers.values()], assignments),
        game_summary=game_summary,
        frozen=False,
        stale=stale,
    )


def public_team_data(db: Session, match: Match) -> dict:
    data = team_rating_data(db, match)
    return {
        key: data.get(key)
        for key in (
            "summary",
            "strength",
            "game_summary",
            "method",
            "frozen",
            "stale",
            "run_id",
            "variant",
        )
    }


def strength_text(value):
    if value["total"] is not None:
        return f"{value['total']:.2f}"
    return f"неполная: {value['rated_total']:.2f} по {value['rated']} из {value['count']} игроков"
