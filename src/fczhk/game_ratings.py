"""Experimental OpenSkill ratings replayed from completed match results.

Field players only: keeper histories and placeholder identities are too sparse for
the first team-selection model. The result is reconstructed in date order so edits
to historical results are reflected without mutating community ratings.
"""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache

from openskill.models import ThurstoneMostellerFull
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Match, MatchResult, Player, ResultGoal, ResultParticipant

MODEL_VERSION = "openskill-6.2.0/tmfull-field-v1"
DISPLAY_BASE = 1500
DISPLAY_SCALE = 10


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
    """Read completed games from every season, ordered by game date and match ID."""
    canonical = {p.id: p.merged_into or p.id for p in db.scalars(select(Player))}
    completed_ids = select(Match.id).join(MatchResult).where(MatchResult.completed.is_(True))
    matches = db.scalars(
        select(Match)
        .join(MatchResult, MatchResult.match_id == Match.id)
        .where(Match.id.in_(completed_ids))
        .order_by(Match.game_day, Match.id)
    )
    by_match = defaultdict(list)
    for row in db.scalars(
        select(ResultParticipant)
        .where(ResultParticipant.match_id.in_(completed_ids))
        .order_by(ResultParticipant.match_id, ResultParticipant.player_id)
    ):
        by_match[row.match_id].append(row)
    scores = defaultdict(lambda: {"white": 0, "black": 0})
    for row in db.scalars(select(ResultGoal).where(ResultGoal.match_id.in_(completed_ids))):
        scores[row.match_id][row.team] += 1
    result = []
    for match in matches:
        participants = by_match[match.id]
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
        counts = scores[match.id]
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
    """Accumulate ratings chronologically across all seasons, without seasonal resets."""
    games = tuple(
        game for game in history(db) if before_day is None or game.day < before_day
    )
    # Content-addressed cache: changed results, identities, or dates get a new key.
    # It cannot serve an old revision after imports or edits, even across processes.
    return deepcopy(_replay(games, margin, include_keepers))


@lru_cache(maxsize=32)
def _replay(games: tuple[HistoricalGame, ...], margin: float, include_keepers: bool):
    if margin < 0:
        raise ValueError("margin не может быть отрицательным")
    model = ThurstoneMostellerFull(margin=margin)
    ratings = {}
    appearances = {}
    predictions = []
    for game in games:
        if include_keepers:
            ids = (
                tuple((pid, "field") for pid in game.white)
                + tuple((pid, "keeper") for pid in game.white_keepers),
                tuple((pid, "field") for pid in game.black)
                + tuple((pid, "keeper") for pid in game.black_keepers),
            )
        else:
            ids = (game.white, game.black)
        teams = [
            [ratings.setdefault(pid, model.rating(name=str(pid))) for pid in side] for side in ids
        ]
        win_white = model.predict_win(teams)[0]
        outcome = (
            1.0
            if game.score[0] > game.score[1]
            else (0.0 if game.score[0] < game.score[1] else 0.5)
        )
        predictions.append(
            {
                "match_id": game.match_id,
                "day": game.day,
                "score": game.score,
                "p_white": win_white,
                "outcome": outcome,
            }
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


def forecast_history(
    db: Session,
    *,
    season: str | None = None,
    before_day: str | None = None,
    margin: float = 0.0,
    include_keepers: bool = False,
) -> list[dict]:
    """Forecast from all past seasons; season filters report rows, never training history."""
    predictions = replay(
        db, margin=margin, before_day=before_day, include_keepers=include_keepers
    )["predictions"]
    if season is None:
        return predictions
    match_ids = set(db.scalars(select(Match.id).where(Match.season == season)))
    return [p for p in predictions if p["match_id"] in match_ids]


def prediction_error(predictions: list[dict], decisive_only: bool = False) -> float | None:
    """Squared error for white win probability, with draws at target 0.5."""
    if decisive_only:
        predictions = [p for p in predictions if p["outcome"] != 0.5]
    if not predictions:
        return None
    return sum((p["p_white"] - p["outcome"]) ** 2 for p in predictions) / len(predictions)


def leaderboard(db: Session) -> dict:
    """Show cumulative ratings and appearances from the entire chronological history."""
    run = replay(db)
    aliases = {
        p.id: p.alias for p in db.scalars(select(Player).where(Player.id.in_(run["players"])))
    }
    players = [
        {
            "player_id": pid,
            "alias": aliases[pid],
            "mu": rating["mu"],
            "sigma": rating["sigma"],
            "ordinal": rating["mu"] - 3 * rating["sigma"],
            "rating": round(DISPLAY_BASE + DISPLAY_SCALE * (rating["mu"] - 3 * rating["sigma"])),
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
