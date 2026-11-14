"""Betting points: weekly freebets, balances, the leaderboard and the bank.

Points are virtual. Every movement is a ``WalletEntry``; balances, the leaderboard and the bank
are read models computed from those entries, so nothing can drift out of step with the journal.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select

from .db import now
from .models import Bet, Player, WalletEntry
from .results import identities
from .scheduling import MOSCOW
from .services import DomainError, audit

UNIT = 100  # amounts are stored in hundredths of a point
FREEBET_POINTS = 100
RECENT_ENTRIES = 20
BANK_KINDS = ("stake", "payout", "refund", "correction")


def points(amount: int) -> float:
    return amount / UNIT


def week_key(at: datetime) -> str:
    """ISO week of a moment in Moscow time; weeks start on Monday 00:00."""
    year, week, _ = at.astimezone(MOSCOW).isocalendar()
    return f"{year}-W{week:02d}"


def next_week_start(at: datetime) -> datetime:
    local = at.astimezone(MOSCOW)
    monday = (local - timedelta(days=local.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday + timedelta(days=7)


def _owned_ids(db, player_id: int) -> list[int]:
    """The player's card and every historical card merged into it."""
    return [player_id, *db.scalars(select(Player.id).where(Player.merged_into == player_id))]


def balance(db, player_id: int) -> int:
    ids = _owned_ids(db, player_id)
    return int(
        db.scalar(
            select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
                WalletEntry.player_id.in_(ids)
            )
        )
    )


def _freebet_taken(db, ids: list[int], week: str) -> bool:
    return (
        db.scalar(
            select(WalletEntry.id)
            .where(WalletEntry.player_id.in_(ids), WalletEntry.freebet_week == week)
            .limit(1)
        )
        is not None
    )


def claim_freebet(db, actor: int, at: datetime | None = None) -> WalletEntry:
    at = at or now()
    # Lock the player's card: two taps on the button cannot both pass the check below.
    db.scalar(select(Player).where(Player.id == actor).with_for_update())
    week = week_key(at)
    if _freebet_taken(db, _owned_ids(db, actor), week):
        raise DomainError("Фрибет за эту неделю уже получен. Следующий — в понедельник.", 409)
    entry = WalletEntry(
        player_id=actor,
        kind="freebet",
        amount=FREEBET_POINTS * UNIT,
        freebet_week=week,
        created_at=at,
    )
    db.add(entry)
    db.flush()
    audit(db, actor, "wallet.freebet", week=week, amount=FREEBET_POINTS)
    return entry


def _entry(e: WalletEntry) -> dict:
    return dict(
        id=e.id,
        kind=e.kind,
        amount=points(e.amount),
        week=e.freebet_week,
        note=e.note,
        created_at=e.created_at,
    )


MAX_GRANT = 100_000  # points per grant, either sign


def grant(db, actor: int, player_id: int, amount: float, reason: str) -> WalletEntry:
    """An administrator adds points to (or takes them from) a player's balance, with a reason.

    Points stay virtual: a grant is for prizes and corrections, not a way to sell points. It is
    journalled, audited and shown to the player; it is not a bet result, so it changes neither
    the player's betting result nor the bank."""
    target = db.scalar(select(Player).where(Player.id == player_id).with_for_update())
    if target is None or target.merged_into:
        raise DomainError("Игрок не найден", 404)
    if target.shared_keeper:
        raise DomainError("Общей карточке вратаря очки не начисляются", 422)
    if player_id == actor:
        raise DomainError("Себе начислять очки нельзя", 422)
    cents = round(amount * UNIT)
    if cents == 0 or abs(cents) > MAX_GRANT * UNIT:
        raise DomainError(f"Сумма — от 0,01 до {MAX_GRANT} очков, со знаком", 422)
    reason = reason.strip()
    if not 3 <= len(reason) <= 200:
        raise DomainError("Укажите причину: от 3 до 200 символов", 422)
    entry = WalletEntry(
        player_id=player_id,
        kind="grant",
        amount=cents,
        actor_id=actor,
        note=reason,
        created_at=now(),
    )
    db.add(entry)
    db.flush()
    audit(db, actor, "wallet.grant", player_id=player_id, amount=points(cents), reason=reason)
    return entry


def grants(db, limit: int = 50) -> list[dict]:
    people = {p.id: p for p in db.scalars(select(Player))}
    rows = db.scalars(
        select(WalletEntry)
        .where(WalletEntry.kind == "grant")
        .order_by(WalletEntry.created_at.desc(), WalletEntry.id.desc())
        .limit(limit)
    )
    return [
        dict(
            id=e.id,
            player_id=e.player_id,
            alias=people[e.player_id].display_alias,
            actor=people[e.actor_id].display_alias,
            amount=points(e.amount),
            note=e.note,
            created_at=e.created_at,
        )
        for e in rows
    ]


def wallet_data(db, viewer: int, at: datetime | None = None) -> dict:
    at = at or now()
    ids = _owned_ids(db, viewer)
    week = week_key(at)
    sums = dict(
        db.execute(
            select(WalletEntry.kind, func.sum(WalletEntry.amount))
            .where(WalletEntry.player_id.in_(ids))
            .group_by(WalletEntry.kind)
        ).all()
    )
    recent = db.scalars(
        select(WalletEntry)
        .where(WalletEntry.player_id.in_(ids))
        .order_by(WalletEntry.created_at.desc(), WalletEntry.id.desc())
        .limit(RECENT_ENTRIES)
    )
    total = sum(sums.values())
    freebets = sums.get("freebet", 0)
    granted = sums.get("grant", 0)
    return dict(
        server_time=at,
        balance=points(total),
        # Betting result only: freebets and administrators' grants are not won or lost.
        profit=points(total - freebets - granted),
        freebets=points(freebets),
        grants=points(granted),
        freebet=dict(
            amount=FREEBET_POINTS,
            week=week,
            available=not _freebet_taken(db, ids, week),
            next_at=next_week_start(at),
        ),
        entries=[_entry(e) for e in recent],
    )


def leaderboard(db) -> dict:
    """Every player who has ever held points, by balance; and the bank's side of all bets."""
    people, canonical = identities(db)
    totals: dict[int, dict] = {}
    for player_id, kind, amount in db.execute(
        select(WalletEntry.player_id, WalletEntry.kind, func.sum(WalletEntry.amount)).group_by(
            WalletEntry.player_id, WalletEntry.kind
        )
    ):
        pid = canonical[player_id]
        row = totals.setdefault(pid, dict(balance=0, freebets=0, grants=0, staked=0, returned=0))
        row["balance"] += amount
        if kind == "freebet":
            row["freebets"] += amount
        elif kind == "grant":
            row["grants"] += amount
        elif kind == "stake":
            row["staked"] -= amount
        else:
            row["returned"] += amount
    ordered = sorted(
        totals.items(),
        key=lambda item: (-item[1]["balance"], people[item[0]].alias.casefold(), item[0]),
    )
    rows, previous, rank = [], None, 0
    for index, (pid, row) in enumerate(ordered, 1):
        if row["balance"] != previous:
            rank, previous = index, row["balance"]
        rows.append(
            dict(
                rank=rank,
                player_id=pid,
                alias=people[pid].display_alias,
                balance=points(row["balance"]),
                freebets=points(row["freebets"]),
                grants=points(row["grants"]),
                profit=points(row["balance"] - row["freebets"] - row["grants"]),
                staked=points(row["staked"]),
            )
        )
    bank = {kind: 0 for kind in BANK_KINDS}
    for kind, amount in db.execute(
        select(WalletEntry.kind, func.sum(WalletEntry.amount))
        .where(WalletEntry.kind.in_(BANK_KINDS))
        .group_by(WalletEntry.kind)
    ):
        bank[kind] = amount
    # Stakes of bets not yet settled are held, not won: the bank counts them separately.
    in_play = db.scalar(select(func.coalesce(func.sum(Bet.stake), 0)).where(Bet.status == "open"))
    freebets = sum(row["freebets"] for row in totals.values())
    return dict(
        rows=rows,
        bank=dict(
            # What players have lost to the bank on settled bets: stakes minus everything paid back.
            balance=points(-sum(bank.values()) - in_play),
            in_play=points(in_play),
            staked=points(-bank["stake"]),
            # payouts net of corrections after changed results
            paid_out=points(bank["payout"] + bank["correction"]),
            refunded=points(bank["refund"]),
        ),
        freebets_issued=points(freebets),
        grants_issued=points(sum(row["grants"] for row in totals.values())),
        players=len(rows),
    )
