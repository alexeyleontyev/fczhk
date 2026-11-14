"""Betting points: weekly freebets, balances, the leaderboard and the bank.

Points are virtual. Every movement is a ``WalletEntry``; balances, the leaderboard and the bank
are read models computed from those entries, so nothing can drift out of step with the journal.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select

from .db import now
from .models import Player, WalletEntry
from .results import identities
from .scheduling import MOSCOW
from .services import DomainError, audit

UNIT = 100  # amounts are stored in hundredths of a point
FREEBET_POINTS = 100
RECENT_ENTRIES = 20
BANK_KINDS = ("stake", "payout", "refund")


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
        id=e.id, kind=e.kind, amount=points(e.amount), week=e.freebet_week, created_at=e.created_at
    )


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
    return dict(
        server_time=at,
        balance=points(total),
        profit=points(total - freebets),
        freebets=points(freebets),
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
        row = totals.setdefault(pid, dict(balance=0, freebets=0, staked=0, returned=0))
        row["balance"] += amount
        if kind == "freebet":
            row["freebets"] += amount
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
                profit=points(row["balance"] - row["freebets"]),
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
    freebets = sum(row["freebets"] for row in totals.values())
    return dict(
        rows=rows,
        bank=dict(
            # What players have lost to the bank: stakes taken minus what was paid back.
            balance=points(-(bank["stake"] + bank["payout"] + bank["refund"])),
            staked=points(-bank["stake"]),
            paid_out=points(bank["payout"]),
            refunded=points(bank["refund"]),
        ),
        freebets_issued=points(freebets),
        players=len(rows),
    )
