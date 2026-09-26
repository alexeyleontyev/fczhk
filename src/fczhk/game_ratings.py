"""Experimental OpenSkill ratings replayed from completed match results.

Field players only: keeper histories and placeholder identities are too sparse for
the first team-selection model. The result is reconstructed in date order so edits
to historical results are reflected without mutating community ratings.
"""

from dataclasses import dataclass

from openskill.models import ThurstoneMostellerFull
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Match, MatchResult, Player, ResultGoal, ResultParticipant

MODEL_VERSION = "openskill-6.2.0/tmfull-field-v1"


@dataclass(frozen=True)
class HistoricalGame:
    match_id: int
    day: str
    white: tuple[int, ...]
    black: tuple[int, ...]
    white_keepers: tuple[int, ...]
    black_keepers: tuple[int, ...]
    score: tuple[int, int]


def history(db: Session) -> list[HistoricalGame]:
    canonical = {p.id: p.merged_into or p.id for p in db.scalars(select(Player))}
    matches = db.scalars(
        select(Match)
        .join(MatchResult, MatchResult.match_id == Match.id)
        .where(MatchResult.completed.is_(True))
        .order_by(Match.game_day, Match.id)
    )
    result = []
    for match in matches:
        participants = list(
            db.scalars(
                select(ResultParticipant).where(ResultParticipant.match_id == match.id)
            )
        )
        teams = {
            (side, position): tuple(
                canonical[p.player_id]
                for p in participants
                if p.team == side and p.position == position
            )
            for side in ("white", "black")
            for position in ("field", "keeper")
        }
        field = {side: teams[side, "field"] for side in ("white", "black")}
        if not all(field.values()):
            continue
        if len(set(field["white"] + field["black"])) != sum(map(len, field.values())):
            raise ValueError(f"В игре {match.game_day} повторяется игрок")
        goals = db.scalars(select(ResultGoal).where(ResultGoal.match_id == match.id))
        counts = {"white": 0, "black": 0}
        for goal in goals:
            counts[goal.team] += 1
        result.append(
            HistoricalGame(
                match_id=match.id,
                day=match.game_day,
                white=field["white"],
                black=field["black"],
                white_keepers=teams["white", "keeper"],
                black_keepers=teams["black", "keeper"],
                score=(counts["white"], counts["black"]),
            )
        )
    return result


def replay(
    db: Session,
    margin: float = 0.0,
    before_day: str | None = None,
    include_keepers: bool = False,
) -> dict:
    """Return chronological predictions; keeper mode keeps field and keeper skills separate."""
    if margin < 0:
        raise ValueError("margin не может быть отрицательным")
    model = ThurstoneMostellerFull(margin=margin)
    ratings = {}
    appearances = {}
    predictions = []
    for game in history(db):
        if before_day is not None and game.day >= before_day:
            break
        if include_keepers:
            ids = (
                tuple((pid, "field") for pid in game.white)
                + tuple((pid, "keeper") for pid in game.white_keepers),
                tuple((pid, "field") for pid in game.black)
                + tuple((pid, "keeper") for pid in game.black_keepers),
            )
        else:
            ids = (game.white, game.black)
        teams = [[ratings.setdefault(pid, model.rating(name=str(pid))) for pid in side] for side in ids]
        win_white = model.predict_win(teams)[0]
        outcome = 1.0 if game.score[0] > game.score[1] else (
            0.0 if game.score[0] < game.score[1] else 0.5
        )
        predictions.append(
            {"day": game.day, "score": game.score, "p_white": win_white, "outcome": outcome}
        )
        updated = model.rate(teams, scores=list(game.score))
        for side_ids, side_ratings in zip(ids, updated, strict=True):
            for pid, rating in zip(side_ids, side_ratings, strict=True):
                ratings[pid] = rating
                appearances[pid] = appearances.get(pid, 0) + 1
    return {
        "model": "ThurstoneMostellerFull",
        "margin": margin,
        "include_keepers": include_keepers,
        "players": {
            pid: {"mu": rating.mu, "sigma": rating.sigma, "games": appearances[pid]}
            for pid, rating in ratings.items()
        },
        "predictions": predictions,
    }


def prediction_error(predictions: list[dict], decisive_only: bool = False) -> float | None:
    """Squared error for white win probability, with draws at target 0.5."""
    if decisive_only:
        predictions = [p for p in predictions if p["outcome"] != 0.5]
    if not predictions:
        return None
    return sum((p["p_white"] - p["outcome"]) ** 2 for p in predictions) / len(predictions)


def leaderboard(db: Session) -> dict:
    """Read-only preview; keep it separate from community ratings and team runs."""
    run = replay(db)
    aliases = {
        p.id: p.alias
        for p in db.scalars(select(Player).where(Player.id.in_(run["players"])))
    }
    players = [
        {
            "player_id": pid,
            "alias": aliases[pid],
            "mu": rating["mu"],
            "sigma": rating["sigma"],
            "ordinal": rating["mu"] - 3 * rating["sigma"],
            "games": rating["games"],
        }
        for pid, rating in run["players"].items()
    ]
    players.sort(key=lambda item: (-item["ordinal"], -item["games"], item["alias"]))
    return {
        "model": run["model"],
        "model_version": MODEL_VERSION,
        "margin": run["margin"],
        "matches": len(run["predictions"]),
        "provisional": True,
        "players": players,
    }
