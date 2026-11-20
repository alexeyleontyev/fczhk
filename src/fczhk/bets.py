"""Placing and settling bets.

Settlement is a reconciliation: for every bet of a match the code computes what the bet should
have paid back given the current state of the match, and posts only the difference to the points
journal. The same function therefore settles a finished match, refunds bets after a line-up
change or a cancellation, and re-settles after an administrator corrects a result -- a payout is
taken back or added with a ``correction`` entry, and running it twice changes nothing.

Rules:
- a bet is refunded when the approved line-up changes after it was placed, or the match is
  cancelled;
- a player goals selection is void when the player did not play or when his team has a goal
  without a named scorer; a player assists selection is void when the player did not play (a goal
  without a named assistant is a goal without an assist); a combination with a void selection is
  refunded as a whole;
- nobody may bet on "under" for his own goals or assists: it would be his to decide;
- otherwise a bet wins when every selection wins, and pays stake times odds.
"""

from __future__ import annotations

from sqlalchemy import case, func, select

from . import odds as od
from .db import now
from .models import Bet, Match, MatchResult, Player, ResultGoal, ResultParticipant, WalletEntry
from .services import DomainError, audit
from .wallet import UNIT, balance, points

MIN_STAKE = UNIT  # one point


def place(db, actor: int, match: Match, body) -> Bet:
    # The caller locks the match first. Serialize spending and profile links on the player.
    db.scalar(select(Player).where(Player.id == actor).with_for_update())
    if not od.betting_open(match):
        raise DomainError("Приём ставок на эту игру закрыт", 409)
    odds = od.snapshot(db, match)
    if body.odds_id != odds.id:
        raise DomainError("Составы изменились, коэффициенты обновлены. Проверьте ставку.", 409)
    under_players = {
        leg["player"]
        for leg in od.legs_for(odds, body.selections)
        if leg["kind"] in od.PLAYER_GROUP and leg["side"] == "under"
    }
    # A frozen line can still reference a guest card that was linked to the bettor later.
    if (
        under_players
        and db.scalar(
            select(Player.id)
            .where(
                Player.id.in_(under_players),
                func.coalesce(Player.merged_into, Player.id) == actor,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError("Нельзя ставить на «меньше» по своим голам и передачам", 422)
    quote = od.quote(db, odds, body.selections)
    if round(body.odds, 2) != quote["odds"]:
        raise DomainError(f"Коэффициент изменился: теперь {quote['odds']:g}", 409)
    stake = round(body.stake * UNIT)
    if stake < MIN_STAKE:
        raise DomainError("Минимальная ставка — 1 очко", 422)
    if stake > balance(db, actor):
        raise DomainError("Недостаточно очков на балансе", 409)
    bet = Bet(
        player_id=actor,
        match_id=match.id,
        odds_id=odds.id,
        approved_version=odds.approved_version,
        selections=list(body.selections),
        labels=quote["labels"],
        stake=stake,
        odds=round(quote["odds"] * 100),
        status="open",
        credited=0,
        created_at=now(),
    )
    db.add(bet)
    db.flush()
    db.add(
        WalletEntry(
            player_id=actor, kind="stake", amount=-stake, bet_id=bet.id, created_at=bet.created_at
        )
    )
    audit(db, actor, "bet.placed", match.id, bet_id=bet.id, stake=points(stake), odds=quote["odds"])
    return bet


def _result(db, match: Match):
    result = db.get(MatchResult, match.id)
    if result is None or not result.completed:
        return None
    canonical = {p.id: p.merged_into or p.id for p in db.scalars(select(Player))}
    goals = list(db.scalars(select(ResultGoal).where(ResultGoal.match_id == match.id)))
    played = {
        canonical[r.player_id]: r.team
        for r in db.scalars(select(ResultParticipant).where(ResultParticipant.match_id == match.id))
    }
    scorers: dict[int, int] = {}
    assistants: dict[int, int] = {}
    unknown = {"white": False, "black": False}
    for g in goals:
        if g.kind == "goal" and g.author_id is None:
            unknown[g.team] = True
        elif g.kind == "goal":
            pid = canonical[g.author_id]
            scorers[pid] = scorers.get(pid, 0) + 1
        if g.kind == "goal" and g.assist_id is not None:
            pid = canonical[g.assist_id]
            # Only an assist to a goal of the player's own team counts.
            if played.get(pid) == g.team:
                assistants[pid] = assistants.get(pid, 0) + 1
    return dict(
        white=sum(g.team == "white" for g in goals),
        black=sum(g.team == "black" for g in goals),
        played=played,
        scorers=scorers,
        assistants=assistants,
        unknown=unknown,
        canonical=canonical,
    )


def _leg_result(leg: dict, r: dict) -> str:
    x, y = r["white"], r["black"]
    if leg["kind"] in od.PLAYER_GROUP:
        pid = r["canonical"].get(leg["player"], leg["player"])
        team = r["played"].get(pid)
        if team is None or (leg["kind"] == "player" and r["unknown"][team]):
            return "void"
        credited = r["scorers" if leg["kind"] == "player" else "assistants"]
        n = credited.get(pid, 0)
        won = n > leg["line"] if leg["side"] == "over" else n < leg["line"]
        return "won" if won else "lost"
    won = bool(od.score_mask([leg], max(x, y) + 1)[x, y])
    return "won" if won else "lost"


def _target(bet: Bet, match: Match, result: dict | None) -> tuple[str, int, dict | None]:
    """(status, credited, outcome) the bet should have now."""
    if match.status == "cancelled":
        return "void", bet.stake, dict(reason="Игра отменена")
    if bet.approved_version != match.approved_version:
        return "void", bet.stake, dict(reason="Составы изменились после ставки")
    if result is None:
        return "open", 0, None
    legs = [od.parse(s) for s in bet.selections]
    per_leg = [_leg_result(leg, result) for leg in legs]
    outcome = dict(score=dict(white=result["white"], black=result["black"]), legs=per_leg)
    if "void" in per_leg:
        outcome["reason"] = "Игрок не играл или в протоколе есть гол без автора"
        return "void", bet.stake, outcome
    if all(v == "won" for v in per_leg):
        return "won", round(bet.stake * bet.odds / 100), outcome
    return "lost", 0, outcome


def reconcile_match(db, match: Match) -> int:
    """Bring every bet of the match in line with its current state; returns bets changed."""
    bets = list(
        db.scalars(select(Bet).where(Bet.match_id == match.id).order_by(Bet.id).with_for_update())
    )
    if not bets:
        return 0
    result = _result(db, match)
    changed = 0
    for bet in bets:
        status, credited, outcome = _target(bet, match, result)
        if status == bet.status and credited == bet.credited and outcome == bet.outcome:
            continue
        delta = credited - bet.credited
        if delta:
            first = bet.credited == 0 and bet.settled_at is None
            kind = (
                ("refund" if status == "void" else "payout")
                if first and delta > 0
                else "correction"
            )
            db.add(
                WalletEntry(
                    player_id=bet.player_id,
                    kind=kind,
                    amount=delta,
                    bet_id=bet.id,
                    created_at=now(),
                )
            )
        previous = bet.status
        bet.status, bet.credited, bet.outcome = status, credited, outcome
        bet.settled_at = None if status == "open" else now()
        audit(
            db,
            None,
            "bet.settled",
            match.id,
            bet_id=bet.id,
            status=status,
            previous=previous,
            credited=points(credited),
        )
        changed += 1
    db.flush()
    return changed


def serialize(bet: Bet) -> dict:
    return dict(
        id=bet.id,
        match_id=bet.match_id,
        selections=bet.selections,
        labels=bet.labels,
        stake=points(bet.stake),
        odds=bet.odds / 100,
        potential=points(round(bet.stake * bet.odds / 100)),
        status=bet.status,
        credited=points(bet.credited),
        outcome=bet.outcome,
        created_at=bet.created_at,
        settled_at=bet.settled_at,
    )


def my_bets(db, viewer: int, match_id: int | None = None, limit: int = 50) -> list[dict]:
    ids = [viewer, *db.scalars(select(Player.id).where(Player.merged_into == viewer))]
    query = select(Bet).where(Bet.player_id.in_(ids))
    if match_id is not None:
        query = query.where(Bet.match_id == match_id)
    return [
        serialize(b)
        for b in db.scalars(query.order_by(Bet.created_at.desc(), Bet.id.desc()).limit(limit))
    ]


def reconcile_open(db) -> int:
    """Safety net for the worker: reconcile every match that still has an open bet."""
    match_ids = set(db.scalars(select(Bet.match_id).where(Bet.status == "open")))
    changed = 0
    for mid in sorted(match_ids):
        match = db.scalar(select(Match).where(Match.id == mid).with_for_update())
        changed += reconcile_match(db, match)
    return changed


def worker_tick(factory) -> None:
    """Refit the pricing model after new results and settle anything the hooks missed.

    Failures are logged and retried on the next tick: they must not stop message delivery."""
    import logging

    log = logging.getLogger(__name__)
    for step in (od.refit_if_needed, reconcile_open):
        try:
            with factory() as db, db.begin():
                step(db)
        except Exception as exc:  # noqa: BLE001 - the worker keeps running
            log.error("Betting step %s failed (%s); retrying", step.__name__, type(exc).__name__)


def _aliases(db) -> dict[int, str]:
    people = {p.id: p for p in db.scalars(select(Player))}
    return {pid: people[p.merged_into or pid].display_alias for pid, p in people.items()}


def match_bets(db, match: Match) -> list[dict]:
    """Everybody's bets on a match. Hidden until kick-off, so nobody copies or reacts to them."""
    if now() < match.starts_at:
        raise DomainError("Ставки игроков откроются в момент начала игры", 409)
    alias = _aliases(db)
    rows = db.scalars(select(Bet).where(Bet.match_id == match.id).order_by(Bet.created_at, Bet.id))
    return [serialize(b) | dict(player_id=b.player_id, alias=alias[b.player_id]) for b in rows]


def archive(db, limit: int = 30) -> list[dict]:
    """Matches that already started and had bets, newest first, with totals per match."""
    from sqlalchemy import func

    started = now()
    rows = db.execute(
        select(
            Match.id,
            Match.starts_at,
            func.count(Bet.id),
            func.count(func.distinct(Bet.player_id)),
            func.sum(Bet.stake),
            func.sum(Bet.credited),
            func.sum(case((Bet.status == "open", 1), else_=0)),
        )
        .join(Bet, Bet.match_id == Match.id)
        .where(Match.starts_at <= started)
        .group_by(Match.id, Match.starts_at)
        .order_by(Match.starts_at.desc())
        .limit(limit)
    ).all()
    out = []
    for mid, starts_at, n, players, staked, credited, open_ in rows:
        result = _result(db, db.get(Match, mid))
        out.append(
            dict(
                match_id=mid,
                starts_at=starts_at,
                score=dict(white=result["white"], black=result["black"]) if result else None,
                bets=n,
                players=players,
                staked=points(staked),
                returned=points(credited),
                open=int(open_),
                # The bank's result on this match once every bet is settled.
                bank=points(staked - credited) if not open_ else None,
            )
        )
    return out
