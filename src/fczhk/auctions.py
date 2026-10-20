"""Sealed bids serialize on the match row. Only resolved lots disclose both amounts."""

from copy import deepcopy
from html import escape
from random import SystemRandom
from uuid import uuid4

from sqlalchemy import func, select

from .models import Auction, AuctionLot, Player, Publication, TeamRatingDraft
from .notifications import extended_chat
from .ratings import lock_ratings
from .services import MOSCOW, DomainError, audit, ensure_pregame, entries, invalidate, save_teams

TEAMS = ("white", "black")
RUNNING = ("active", "paused")


def latest(db, match):
    return db.scalar(
        select(Auction)
        .where(Auction.match_id == match.id)
        .order_by(Auction.id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )


def guard(db, match):
    auction = latest(db, match)
    if auction and auction.status in RUNNING:
        raise DomainError("Сначала завершите или отмените аукцион", 409)


def invalidate_roster(db, match):
    auction = latest(db, match)
    if auction and auction.status in RUNNING:
        auction.status = "invalidated"
        auction.revision += 1
        audit(db, None, "auction.invalidated", match.id, auction_id=auction.id)


def formation_method(db, match, assignments):
    auction = latest(db, match)
    if (
        not auction
        or auction.status not in ("completed", "manual")
        or auction.roster_version != match.roster_version
    ):
        return "manual"
    original = auction.state["assignments"]
    return (
        "auction"
        if all(assignments.get(int(rid)) == team for rid, team in original.items())
        and auction.status == "completed"
        else "auction-edited"
    )


def data(db, auction, viewer):
    if not auction:
        return None
    lots = list(
        db.scalars(
            select(AuctionLot)
            .where(AuctionLot.auction_id == auction.id)
            .order_by(AuctionLot.number)
        )
    )
    state = auction.state
    people = {p["registration_id"]: p for p in state["participants"]}
    side = next((t for t in TEAMS if getattr(auction, t + "_captain") == viewer), None)
    current = next((lot for lot in lots if lot.status == "pending"), None)
    prices = {
        str(lot.registration_id): getattr(lot, lot.winner + "_bid")
        for lot in lots
        if lot.status == "won" and lot.winner
    }
    prices.update({str(rid): 0 for rid in state["automatic"]})
    return dict(
        id=auction.id,
        revision=auction.revision,
        status=auction.status,
        roster_version=auction.roster_version,
        rules="sealed-captains/v1",
        side=side,
        budgets={t: getattr(auction, t + "_budget") for t in TEAMS},
        limits={t: getattr(auction, t + "_limit") for t in TEAMS},
        captains={t: getattr(auction, t + "_captain") for t in TEAMS},
        participants=state["participants"],
        assignments=state["assignments"],
        automatic=state["automatic"],
        prices=prices,
        current=dict(
            id=current.id,
            number=current.number,
            round=current.round,
            player=people[current.registration_id],
            own_bid=getattr(current, side + "_bid") if side else None,
            submitted={t: getattr(current, t + "_bid") is not None for t in TEAMS},
        )
        if current and auction.status in RUNNING
        else None,
        lots=[
            dict(
                id=lot.id,
                number=lot.number,
                round=lot.round,
                player=people[lot.registration_id],
                status=lot.status,
                winner=lot.winner,
                white_bid=lot.white_bid,
                black_bid=lot.black_bid,
            )
            for lot in lots
            if lot.status in ("tied", "won")
        ],
    )


def apply_assignments(db, actor, match, auction):
    values = {
        r.id: auction.state["assignments"].get(str(r.id), auction.state["keepers"].get(str(r.id)))
        for r in entries(db, match.id)
        if r.selected
    }
    save_teams(db, actor, match, values, reset=True)


def announce(db, match, auction, text, cfg):
    # The caller holds the match lock. Replayed bids return before creating an outbox row.
    chat = extended_chat(db, "auction_lot")
    if not chat:
        return
    text += (
        f"\n\nОсталось баллов: ⚪ Белые — {auction.white_budget} · "
        f"⚫ Чёрные — {auction.black_budget}."
    )
    version = (
        db.scalar(
            select(func.max(Publication.version)).where(
                Publication.match_id == match.id, Publication.kind == "auction_lot"
            )
        )
        or 0
    ) + 1
    db.add(
        Publication(
            match_id=match.id,
            kind="auction_lot",
            version=version,
            chat_id=chat,
            text=f"🎯 Аукцион #{auction.id} · {match.starts_at.astimezone(MOSCOW):%d.%m.%Y}\n{text}",
        )
    )
    db.flush()


def announce_lot(db, match, auction, lot, cfg):
    player = next(
        p for p in auction.state["participants"] if p["registration_id"] == lot.registration_id
    )
    text = (
        f"Лот {lot.number} · круг {lot.round} · {player['alias']}\n"
        f"⚪ Белые: {lot.white_bid} баллов\n⚫ Чёрные: {lot.black_bid} баллов\n"
    )
    if lot.winner:
        team = "⚪ Белые" if lot.winner == "white" else "⚫ Чёрные"
        text += f"{team} получают игрока за {getattr(lot, lot.winner + '_bid')} баллов."
    else:
        text += (
            f"Равные ставки — игрок переходит на круг {lot.round + 1}. Команда пока не определена."
        )
    announce(db, match, auction, text, cfg)


def announce_start(db, match, auction, cfg):
    chat = extended_chat(db, "auction_start")
    if not chat:
        return
    lines = [
        f"🎯 Аукцион #{auction.id} начат!",
        f"Игра {match.starts_at.astimezone(MOSCOW):%d.%m.%Y · %H:%M МСК}",
        "",
    ]
    for team, label in (("white", "⚪ Капитан белых"), ("black", "⚫ Капитан чёрных")):
        player = db.get(Player, getattr(auction, team + "_captain"))
        lines.append(
            f'{label}: <a href="tg://user?id={player.telegram_id}">{escape(player.alias)}</a>'
        )
    lines.extend(["", "Капитаны, откройте игру и сделайте ставки.", f"Осталось баллов: ⚪ Белые — {auction.white_budget} · ⚫ Чёрные — {auction.black_budget}."])
    db.add(
        Publication(
            match_id=match.id,
            kind="auction_start",
            version=auction.id,
            chat_id=chat,
            text="\n".join(lines),
        )
    )
    db.flush()


def advance(db, actor, match, auction, cfg):
    state = deepcopy(auction.state)
    full = next(
        (
            t
            for t in TEAMS
            if sum(v == t for v in state["assignments"].values()) >= getattr(auction, t + "_limit")
        ),
        None,
    )
    if full:
        other = "black" if full == "white" else "white"
        for p in state["participants"]:
            rid = str(p["registration_id"])
            if rid not in state["assignments"]:
                state["assignments"][rid] = other
                state["automatic"].append(p["registration_id"])
                team = "⚪ Белые" if other == "white" else "⚫ Чёрные"
                announce(
                    db,
                    match,
                    auction,
                    f"{p['alias']} → {team} · 0 баллов.\nБез торгов: команда соперника заполнена.",
                    cfg,
                )
        state["queue"] = []
        auction.state = state
        auction.status = "completed"
        db.flush()
        apply_assignments(db, actor, match, auction)
        audit(
            db,
            actor,
            "auction.completed",
            match.id,
            auction_id=auction.id,
            assignments=state["assignments"],
            automatic=state["automatic"],
        )
        return
    if not state["queue"]:
        raise DomainError("Нарушена очередь аукциона", 409)
    item = state["queue"].pop(0)
    number = (
        db.scalar(
            select(AuctionLot.number)
            .where(AuctionLot.auction_id == auction.id)
            .order_by(AuctionLot.number.desc())
            .limit(1)
        )
        or 0
    ) + 1
    db.add(
        AuctionLot(
            id=str(uuid4()),
            auction_id=auction.id,
            registration_id=item["registration_id"],
            number=number,
            round=item["round"],
        )
    )
    auction.state = state
    db.flush()


def start(db, actor, match, body, cfg):
    ensure_pregame(db, match)
    if match.status not in ("finalized", "approved"):
        raise DomainError("Сначала финализируйте список")
    guard(db, match)
    lock_ratings(db)
    regs = [r for r in entries(db, match.id) if r.selected]
    field = [r for r in regs if r.position == "field"]
    if not 2 <= len(field) <= 16:
        raise DomainError("Для аукциона нужно от 2 до 16 полевых")
    captains = {body.white_captain, body.black_captain}
    eligible = {r.player_id for r in field if db.get(Player, r.player_id).telegram_id}
    if len(captains) != 2 or not captains <= eligible:
        raise DomainError("Назначьте двух разных зарегистрированных полевых капитанами")
    if len(field) % 2 and body.larger_team is None:
        raise DomainError("Выберите команду с дополнительным местом")
    queue = [{"registration_id": r.id, "round": 1} for r in field if r.player_id not in captains]
    SystemRandom().shuffle(queue)
    state = dict(
        queue=queue,
        assignments={
            str(r.id): "white" if r.player_id == body.white_captain else "black"
            for r in field
            if r.player_id in captains
        },
        keepers={str(r.id): r.team for r in regs if r.position == "keeper"},
        automatic=[],
        participants=[
            dict(
                registration_id=r.id, player_id=r.player_id, alias=db.get(Player, r.player_id).alias
            )
            for r in field
        ],
    )
    invalidate(db, match, roster_changed=False)
    draft = db.get(TeamRatingDraft, match.id)
    if draft:
        db.delete(draft)
    match.version += 1
    auction = Auction(
        match_id=match.id,
        roster_version=match.roster_version,
        white_captain=body.white_captain,
        black_captain=body.black_captain,
        white_limit=len(field) // 2 + int(len(field) % 2 and body.larger_team == "white"),
        black_limit=len(field) // 2 + int(len(field) % 2 and body.larger_team == "black"),
        state=state,
    )
    db.add(auction)
    db.flush()
    audit(
        db,
        actor,
        "auction.started",
        match.id,
        auction_id=auction.id,
        captains=sorted(captains),
        rules="sealed-captains/v1",
    )
    # Queue the captain notification before any immediate automatic assignments.
    announce_start(db, match, auction, cfg)
    advance(db, actor, match, auction, cfg)
    return auction


def bid(db, actor, match, body, cfg):
    auction = latest(db, match)
    if not auction or auction.id != body.auction_id:
        raise DomainError("Аукцион изменился. Обновите страницу.", 409)
    side = next((t for t in TEAMS if getattr(auction, t + "_captain") == actor), None)
    if side is None:
        raise DomainError("Ставки доступны только назначенным капитанам", 403)
    lot = db.get(AuctionLot, str(body.lot_id))
    if not lot or lot.auction_id != auction.id:
        raise DomainError("Лот не найден", 404)
    field = side + "_bid"
    existing = getattr(lot, field)
    # Replay can acknowledge a committed bid, but never mutates a later lot.
    if (
        existing is not None
        and existing == body.amount
        and lot.status in ("pending", "won", "tied")
    ):
        return auction
    if (
        auction.status != "active"
        or auction.roster_version != match.roster_version
        or lot.status != "pending"
    ):
        raise DomainError("Приём ставок на этот лот закрыт", 409)
    if existing is not None:
        raise DomainError("Отправленную ставку изменить нельзя", 409)
    if body.amount > getattr(auction, side + "_budget"):
        raise DomainError("Ставка превышает остаток бюджета")
    setattr(lot, field, body.amount)
    auction.revision += 1
    if lot.white_bid is not None and lot.black_bid is not None:
        state = deepcopy(auction.state)
        if lot.white_bid == lot.black_bid:
            lot.status = "tied"
            state["queue"].append(dict(registration_id=lot.registration_id, round=lot.round + 1))
        else:
            lot.status = "won"
            lot.winner = "white" if lot.white_bid > lot.black_bid else "black"
            amount = getattr(lot, lot.winner + "_bid")
            budget = lot.winner + "_budget"
            setattr(auction, budget, getattr(auction, budget) - amount)
            state["assignments"][str(lot.registration_id)] = lot.winner
        auction.state = state
        db.flush()
        audit(
            db,
            actor,
            "auction.lot_resolved",
            match.id,
            auction_id=auction.id,
            lot_id=lot.id,
            white_bid=lot.white_bid,
            black_bid=lot.black_bid,
            winner=lot.winner,
        )
        announce_lot(db, match, auction, lot, cfg)
        advance(db, actor, match, auction, cfg)
    db.flush()
    return auction


def control(db, actor, match, body):
    auction = latest(db, match)
    if not auction or auction.id != body.auction_id or auction.revision != body.revision:
        raise DomainError("Аукцион изменился. Обновите страницу.", 409)
    transitions = {"pause": ("active", "paused"), "resume": ("paused", "active")}
    if body.action in transitions:
        source, target = transitions[body.action]
        if auction.status != source or auction.roster_version != match.roster_version:
            raise DomainError("Переход недоступен", 409)
        auction.status = target
    else:
        if auction.status not in (*RUNNING, "invalidated"):
            raise DomainError("Торги уже завершены", 409)
        if body.action == "manual" and auction.roster_version != match.roster_version:
            raise DomainError("Состав изменился. Отмените старый аукцион и начните заново.", 409)
        auction.status = "manual" if body.action == "manual" else "cancelled"
        for lot in db.scalars(
            select(AuctionLot).where(
                AuctionLot.auction_id == auction.id, AuctionLot.status == "pending"
            )
        ):
            lot.status = "void"
        db.flush()
        if body.action == "manual":
            apply_assignments(db, actor, match, auction)
    auction.revision += 1
    audit(db, actor, "auction." + body.action, match.id, auction_id=auction.id)
    db.flush()
    return auction
