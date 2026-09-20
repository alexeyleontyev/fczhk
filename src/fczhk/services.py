from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db import now
from .models import (
    Audit,
    GameTemplate,
    Match,
    MatchResult,
    Player,
    Publication,
    Registration,
    ResultParticipant,
    TeamRatingDraft,
    TeamRatingSnapshot,
    TeamSnapshot,
)

MOSCOW = ZoneInfo("Europe/Moscow")


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message = message
        self.status = status


def audit(db: Session, actor: int | None, action: str, match_id=None, **data):
    db.add(Audit(actor_id=actor, action=action, match_id=match_id, data=data))


def get_match(db: Session, match_id: int, version: int | None = None, lock=False) -> Match:
    query = select(Match).where(Match.id == match_id)
    if lock:
        query = query.with_for_update()
    match = db.scalar(query.execution_options(populate_existing=True))
    if not match:
        raise DomainError("Игра не найдена", 404)
    if version is not None and version != match.version:
        raise DomainError("Данные изменились. Обновите игру и повторите действие.", 409)
    return match


def entries(db: Session, match_id: int) -> list[Registration]:
    return list(
        db.scalars(
            select(Registration)
            .where(Registration.match_id == match_id, Registration.active.is_(True))
            .order_by(Registration.registered_at, Registration.id)
            .execution_options(populate_existing=True)
        )
    )


def selection(match: Match, regs: list[Registration]) -> set[int]:
    if match.status not in ("draft", "open"):
        return {r.id for r in regs if r.selected}
    selected = {r.id for r in regs if r.forced}
    for position, limit in (("field", match.field_limit), ("keeper", match.keeper_limit)):
        occupied = sum(r.forced and r.position == position for r in regs)
        eligible = [r for r in regs if r.position == position and r.paid and not r.forced]
        selected.update(r.id for r in eligible[: max(0, limit - occupied)])
    return selected


def invalidate(db: Session, match: Match, roster_changed=True):
    from .auctions import guard, invalidate_roster

    ensure_pregame(db, match)
    if roster_changed:
        invalidate_roster(db, match)
        match.roster_version += 1
        draft = db.get(TeamRatingDraft, match.id)
        if draft:
            db.delete(draft)
    else:
        guard(db, match)
    match.approved_version = None
    if match.status == "approved":
        match.status = "finalized"
    for r in entries(db, match.id):
        r.team = None
    for pub in db.scalars(
        select(Publication).where(
            Publication.match_id == match.id,
            Publication.kind == "teams",
            Publication.stale.is_(False),
        )
    ):
        pub.stale = True
        if pub.status == "pending":
            pub.status = "cancelled"


def match_data(db: Session, match: Match) -> dict:
    from .auctions import latest
    from .ratings import effective, public_team_data
    from .results import result_data

    regs = entries(db, match.id)
    ratings = effective(db, regs)
    chosen = selection(match, regs)
    players = {
        p.id: p
        for p in db.scalars(select(Player).where(Player.id.in_([r.player_id for r in regs])))
    }
    queues = {"field": 0, "keeper": 0}
    rows = []
    for r in regs:
        queues[r.position] += 1
        p = players[r.player_id]
        rows.append(
            dict(
                id=r.id,
                player_id=p.id,
                alias=p.alias,
                guest=p.telegram_id is None,
                position=r.position,
                registered_at=r.registered_at,
                paid=r.paid,
                forced=r.forced,
                selected=r.id in chosen,
                team=r.team,
                rating={k: ratings[r.id][k] for k in ("attack", "defense", "source")},
                queue=queues[r.position],
                state=("selected" if match.status not in ("draft", "open") else "provisional")
                if r.id in chosen
                else ("reserve" if r.paid else "unpaid"),
            )
        )
    pubs = list(
        db.scalars(
            select(Publication)
            .where(Publication.match_id == match.id)
            .order_by(Publication.id.desc())
        )
    )
    auction = latest(db, match)
    return dict(
        id=match.id,
        starts_at=match.starts_at,
        game_day=match.game_day,
        location=match.location,
        description=match.description,
        cost=match.cost,
        payment_details=match.payment_details,
        status=match.status,
        version=match.version,
        field_limit=match.field_limit,
        keeper_limit=match.keeper_limit,
        roster_version=match.roster_version,
        registrations=rows,
        team_ratings=public_team_data(db, match),
        result=result_data(db, match) if db.get(MatchResult, match.id) else None,
        auction_status=auction.status if auction else None,
        publications=[
            dict(
                id=p.id,
                kind=p.kind,
                status=p.status,
                stale=p.stale,
                stale_marked=p.stale_marked,
                error=p.error,
            )
            for p in pubs
        ],
    )


def create_match(db: Session, actor: int | None, data: dict) -> Match:
    # All creators lock the same template row: manual and scheduled creation serialize.
    db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
    day = data["starts_at"].astimezone(MOSCOW).date().isoformat()
    if db.scalar(select(Match.id).where(Match.game_day == day)):
        raise DomainError("На эту дату игра уже создана", 409)
    match = Match(game_day=day, **data)
    db.add(match)
    db.flush()
    audit(db, actor, "match.created", match.id)
    return match


def text_for(db: Session, match: Match, kind: str) -> str:
    when = match.starts_at.astimezone(MOSCOW).strftime("%d.%m.%Y · %H:%M МСК")
    header = f"ФКЖК · {when}\n📍 {match.location}"
    if kind == "collection":
        return (
            f"⚽ Открыта запись\n{header}\n\n"
            f"{match.field_limit} полевых + {match.keeper_limit} вратаря\n"
            f"Стоимость: {match.cost / 100:g} ₽\n{match.payment_details}\n\n"
            f"{match.description}\n\nПриоритет — время записи среди оплативших."
        )
    lines = [f"Составы утверждены\n{header}"]
    for team, label in (("white", "⚪ Белые"), ("black", "⚫ Черные")):
        lines.append(f"\n{label}")
        for r in entries(db, match.id):
            if r.selected and r.team == team:
                p = db.get(Player, r.player_id)
                lines.append(f"{'🧤 ' if r.position == 'keeper' else ''}{p.alias}")
    return "\n".join(lines)


def enqueue(db: Session, match: Match, kind: str, chat_id: str):
    version = match.version
    existing = db.scalar(
        select(Publication).where(
            Publication.match_id == match.id,
            Publication.kind == kind,
            Publication.version == version,
        )
    )
    if existing:
        return existing
    pub = Publication(
        match_id=match.id,
        kind=kind,
        version=version,
        text=text_for(db, match, kind),
        chat_id=chat_id,
    )
    db.add(pub)
    return pub


def open_match(db: Session, actor: int | None, match: Match, cfg: Settings):
    if match.status == "open":
        return
    if match.status != "draft":
        raise DomainError("Сбор уже финализирован")
    match.status = "open"
    match.version += 1
    enqueue(db, match, "collection", cfg.publication_chat_id)
    audit(db, actor, "match.opened", match.id)


def register(db: Session, actor: int, match: Match, position: str):
    if match.status != "open":
        raise DomainError("Самостоятельная запись доступна только в открытый сбор")
    r = db.scalar(
        select(Registration).where(
            Registration.match_id == match.id, Registration.player_id == actor
        )
    )
    if r and r.active and r.position == position:
        return  # A duplicate join is deliberately a no-op.
    if not r:
        r = Registration(match_id=match.id, player_id=actor, position=position)
        db.add(r)
    else:
        if r.forced:
            raise DomainError("Амплуа закрепленного участника меняет администратор")
        if not r.active:
            r.paid = False
            r.paid_at = None
        r.active = True
        r.position = position
    r.registered_at = now()
    match.version += 1
    db.flush()
    audit(db, actor, "registration.joined", match.id, registration_id=r.id, position=position)


def cancel(db: Session, actor: int, match: Match, r: Registration, admin=False):
    ensure_pregame(db, match)
    if not admin and match.status != "open":
        raise DomainError("После финализации изменения вносит администратор")
    if not r.active:
        return
    was_selected = r.selected or r.forced
    audit(db, actor, "registration.cancelled", match.id, registration_id=r.id, was_paid=r.paid)
    r.active = False
    r.paid = False
    r.paid_at = None
    r.selected = False
    r.forced = False
    r.team = None
    if was_selected:
        invalidate(db, match)
    match.version += 1


def confirm_payment(db: Session, actor: int, match: Match, r: Registration, paid: bool):
    if not r.active:
        raise DomainError("Заявка отменена")
    if r.paid == paid:
        return
    audit(db, actor, "payment.changed", match.id, registration_id=r.id, old=r.paid, new=paid)
    r.paid = paid
    r.paid_at = now() if paid else None
    match.version += 1


def finalize(db: Session, actor: int, match: Match):
    if match.status in ("finalized", "approved"):
        return
    if match.status != "open":
        raise DomainError("Сначала откройте сбор")
    regs = entries(db, match.id)
    selected = selection(match, regs)
    for r in regs:
        r.selected = r.id in selected
    match.status = "finalized"
    match.version += 1
    invalidate(db, match)
    audit(db, actor, "match.finalized", match.id, selected=sorted(selected))


def add_participant(
    db: Session, actor: int, match: Match, player_id: int, position: str, replace_id: int | None
):
    p = db.get(Player, player_id)
    if not p or p.merged_into:
        raise DomainError("Игрок не найден", 404)
    regs = entries(db, match.id)
    existing = next((r for r in regs if r.player_id == player_id), None)
    if existing and (existing.selected or existing.forced):
        raise DomainError("Игрок уже включен в состав", 409)
    selected = selection(match, regs)
    if replace_id is not None:
        old = next((r for r in regs if r.id == replace_id), None)
        if not old or old.id not in selected or old.player_id == player_id:
            raise DomainError("Выберите участника состава для замены")
        if old.position != position:
            raise DomainError("Замена должна быть в том же амплуа")
        cancel(db, actor, match, old, admin=True)
        regs = entries(db, match.id)
        # Before finalization, do not let provisional reordering refill the freed slot.
        selected.discard(old.id)
    limit = match.field_limit if position == "field" else match.keeper_limit
    if sum(r.id in selected and r.position == position for r in regs) >= limit:
        raise DomainError("Лимит заполнен. Выберите заменяемого участника.", 409)
    r = db.scalar(
        select(Registration).where(
            Registration.match_id == match.id, Registration.player_id == player_id
        )
    )
    if not r:
        r = Registration(
            match_id=match.id, player_id=player_id, position=position, registered_at=now()
        )
        db.add(r)
    elif not r.active or r.position != position:
        r.registered_at = now()
    r.position = position
    r.active = True
    r.forced = True
    r.selected = True
    db.flush()
    invalidate(db, match)
    match.version += 1
    audit(db, actor, "participant.added", match.id, player_id=player_id, replaced=replace_id)


def promote(db: Session, actor: int, match: Match, position: str):
    if match.status not in ("finalized", "approved"):
        raise DomainError("Переход из резерва доступен после финализации")
    regs = entries(db, match.id)
    limit = match.field_limit if position == "field" else match.keeper_limit
    if sum(r.selected and r.position == position for r in regs) >= limit:
        raise DomainError("Свободных мест нет")
    r = next((r for r in regs if not r.selected and r.paid and r.position == position), None)
    if not r:
        raise DomainError("В резерве нет оплативших игроков этого амплуа")
    r.selected = True
    invalidate(db, match)
    match.version += 1
    audit(db, actor, "reserve.promoted", match.id, registration_id=r.id)


def save_teams(
    db: Session, actor: int, match: Match, assignments: dict[int, str | None], reset=False
):
    if match.status not in ("finalized", "approved"):
        raise DomainError("Сначала финализируйте список")
    regs = [r for r in entries(db, match.id) if r.selected]
    if set(assignments) != {r.id for r in regs}:
        raise DomainError("Список участников изменился. Обновите составы.", 409)
    if not reset and all(r.team == assignments[r.id] for r in regs):
        return
    draft = db.get(TeamRatingDraft, match.id)
    if draft:
        if reset or match.status == "approved":
            db.delete(draft)
        elif any(r.position == "field" and r.team != assignments[r.id] for r in regs):
            draft.edited = True
    invalidate(db, match, roster_changed=False)
    for r in regs:
        r.team = assignments[r.id]
    match.version += 1
    audit(db, actor, "teams.saved", match.id, assignments=assignments, reset=reset)


def approve(db: Session, actor: int, match: Match, cfg: Settings):
    from .auctions import guard
    from .ratings import lock_ratings, team_rating_data

    guard(db, match)
    if match.status == "approved":
        return
    if match.status != "finalized":
        raise DomainError("Сначала финализируйте список")
    # Read participants only after concurrent guest links / rating edits finish.
    lock_ratings(db)
    regs = [r for r in entries(db, match.id) if r.selected]
    if any(r.team not in ("white", "black") for r in regs):
        raise DomainError("Распределите всех участников по командам")
    field = [r for r in regs if r.position == "field"]
    if len(field) < cfg.min_field_players:
        raise DomainError(f"Нужно не менее {cfg.min_field_players} полевых игроков")
    white = sum(r.team == "white" for r in field)
    if abs(white - (len(field) - white)) > 1:
        raise DomainError("Численность полевых должна быть равной или отличаться на одного")
    keepers = [r for r in regs if r.position == "keeper"]
    if any(sum(r.team == t for r in keepers) > 1 for t in ("white", "black")):
        raise DomainError("В каждой команде не больше одного вратаря")
    if cfg.require_two_keepers and len(keepers) != 2:
        raise DomainError("Для утверждения нужны два вратаря")
    if abs(sum(r.team == "white" for r in regs) - sum(r.team == "black" for r in regs)) > 1:
        raise DomainError(
            "Назначьте вратаря так, чтобы общая численность отличалась не более чем на одного"
        )
    ratings = team_rating_data(db, match, approval=True)
    ratings["frozen"] = True
    match.version += 1
    match.approved_version = match.version
    match.status = "approved"
    snapshot = TeamSnapshot(
        match_id=match.id,
        version=match.version,
        teams=[
            dict(
                player_id=r.player_id,
                alias=db.get(Player, r.player_id).alias,
                position=r.position,
                team=r.team,
            )
            for r in regs
        ],
    )
    db.add(snapshot)
    db.flush()
    db.add(TeamRatingSnapshot(snapshot_id=snapshot.id, data=ratings))
    audit(db, actor, "teams.approved", match.id, version=match.version)


def publish_teams(db: Session, actor: int, match: Match, cfg: Settings):
    if match.status != "approved":
        raise DomainError("Сначала утвердите составы")
    enqueue(db, match, "teams", cfg.publication_chat_id)
    audit(db, actor, "teams.publication_requested", match.id)


def schedule_tick(db: Session, cfg: Settings, at: datetime | None = None) -> int | None:
    template = db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
    if not template or not template.enabled:
        return None
    local = (at or now()).astimezone(MOSCOW)
    monday = local.date() - timedelta(days=local.weekday())
    friday = monday + timedelta(days=4)
    opening = datetime.combine(monday + timedelta(days=1), datetime.min.time(), MOSCOW).replace(
        hour=12
    )
    hour, minute = map(int, template.start_time.split(":"))
    starts = datetime.combine(friday, datetime.min.time(), MOSCOW).replace(hour=hour, minute=minute)
    if not opening <= local < starts:
        return None
    match = db.scalar(select(Match).where(Match.game_day == friday.isoformat()).with_for_update())
    if match:
        # An existing manual draft is intentionally not opened by the worker.
        return None
    match = create_match(
        db,
        None,
        dict(
            starts_at=starts,
            location=template.location,
            description=template.description,
            cost=template.cost,
            payment_details=template.payment_details,
        ),
    )
    open_match(db, None, match, cfg)
    return match.id


def merge_guest(db: Session, actor: int, guest_id: int, target_id: int):
    from .ratings import lock_ratings

    lock_ratings(db)
    players = list(
        db.scalars(
            select(Player)
            .where(Player.id.in_([guest_id, target_id]))
            .order_by(Player.id)
            .with_for_update()
        )
    )
    guest = next((p for p in players if p.id == guest_id), None)
    target = next((p for p in players if p.id == target_id), None)
    if (
        not guest
        or not target
        or guest.telegram_id is not None
        or target.telegram_id is None
        or guest.merged_into
        or target.merged_into
    ):
        raise DomainError("Нужны отдельная карточка гостя и зарегистрированный игрок")
    regs = list(db.scalars(select(Registration).where(Registration.player_id == guest_id)))
    for r in regs:
        if db.scalar(
            select(Registration.id).where(
                Registration.match_id == r.match_id, Registration.player_id == target_id
            )
        ):
            raise DomainError(
                "У обеих карточек есть заявка на одну игру. Автослияние запрещено.", 409
            )
    for r in regs:
        r.player_id = target_id
    # Historical events retain their original IDs; read models resolve linked guests.
    linked_ids = list(db.scalars(select(Player.id).where(Player.merged_into == target_id))) + [
        target_id
    ]
    guest_games = select(ResultParticipant.match_id).where(ResultParticipant.player_id == guest_id)
    if db.scalar(
        select(ResultParticipant.match_id).where(
            ResultParticipant.match_id.in_(guest_games), ResultParticipant.player_id.in_(linked_ids)
        )
    ):
        raise DomainError(
            "Обе карточки есть в фактическом составе одной игры. Сначала исправьте результат.", 409
        )
    guest.merged_into = target_id
    audit(db, actor, "guest.linked", guest_id=guest_id, target_id=target_id)


def ensure_pregame(db: Session, match: Match):
    if db.get(MatchResult, match.id):
        raise DomainError("Результат уже внесен. Изменяйте фактический состав в результате матча.")
