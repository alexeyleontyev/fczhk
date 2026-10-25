"""Server deadlines and a standings read model derived from finalized results."""

from sqlalchemy import case, func, select

from .db import now
from .models import Match, MatchResult, Player, Prediction, PredictionBaseline, ResultGoal
from .results import identities
from .services import DomainError, audit

CATEGORIES = ("Б4", "Б13", "Н", "Ч13", "Ч4")
# Rows are predictions, columns are actual results. Store half-points exactly.
MATRIX_HALF = ((6, 2, 0, 0, 0), (1, 4, 1, 0, 0), (0, 1, 6, 1, 0), (0, 0, 1, 4, 1), (0, 0, 0, 2, 6))


def category(white, black):
    difference = white - black
    return (
        "Б4"
        if difference >= 4
        else "Б13"
        if difference > 0
        else "Н"
        if difference == 0
        else "Ч13"
        if difference > -4
        else "Ч4"
    )


def points(white, black, actual_white, actual_black):
    return (
        MATRIX_HALF[CATEGORIES.index(category(white, black))][
            CATEGORIES.index(category(actual_white, actual_black))
        ]
        / 2
    )


def completed_scores():
    return (
        select(
            MatchResult.match_id,
            func.sum(case((ResultGoal.team == "white", 1), else_=0)).label("white"),
            func.sum(case((ResultGoal.team == "black", 1), else_=0)).label("black"),
        )
        .outerjoin(ResultGoal, ResultGoal.match_id == MatchResult.match_id)
        .where(MatchResult.completed.is_(True))
        .group_by(MatchResult.match_id)
        .subquery()
    )


def standings(db, season: str | None = None):
    people, canonical = identities(db)
    scores = completed_scores()
    query = (
        select(Prediction, Player.alias, scores.c.white, scores.c.black)
        .join(Player, Player.id == Prediction.player_id)
        .outerjoin(scores, scores.c.match_id == Prediction.match_id)
        .join(Match, Match.id == Prediction.match_id)
        .where(Match.status != "cancelled", Prediction.scoring_version == 2)
    )
    if season is not None:
        query = query.where(Match.season == season)
    totals = {}

    def empty(pid):
        return dict(
            player_id=pid,
            alias=people[pid].alias,
            points=0,
            baseline_points=0,
            baseline_predictions=0,
            three_points=0,
            two_points=0,
            one_point=0,
            half_points=0,
            settled=0,
            predictions=0,
        )

    baseline_query = select(PredictionBaseline)
    if season is not None:
        baseline_query = baseline_query.where(PredictionBaseline.season == season)
    for baseline in db.scalars(baseline_query):
        pid = canonical[baseline.player_id]
        row = totals.setdefault(pid, empty(pid))
        row["baseline_points"] += baseline.points_half / 2
        row["points"] += baseline.points_half / 2
        row["baseline_predictions"] += baseline.predictions_count
        row["predictions"] += baseline.predictions_count
        row["settled"] += baseline.predictions_count
    for prediction, alias, white, black in db.execute(query):
        pid = canonical[prediction.player_id]
        row = totals.setdefault(pid, empty(pid))
        row["predictions"] += 1
        if white is not None:
            value = points(prediction.white_score, prediction.black_score, white, black)
            row["points"] += value
            row["three_points"] += int(value == 3)
            row["two_points"] += int(value == 2)
            row["one_point"] += int(value == 1)
            row["half_points"] += int(value == 0.5)
            row["settled"] += 1
    ordered = sorted(
        totals.values(), key=lambda row: (-row["points"], row["alias"].casefold(), row["player_id"])
    )
    previous = None
    rank = 0
    for index, row in enumerate(ordered, 1):
        row["average_points"] = row["points"] / row["predictions"] if row["predictions"] else None
        if row["points"] != previous:
            rank = index
        row["rank"] = rank
        previous = row["points"]
    return ordered


def match_predictions(db, match, viewer):
    at = now()
    closed = at >= match.starts_at
    available = not closed and match.status == "approved" and match.approved_version is not None
    scores = completed_scores()
    actual = db.execute(
        select(scores.c.white, scores.c.black).where(scores.c.match_id == match.id)
    ).first()
    rows = list(
        db.execute(
            select(Prediction, Player.alias)
            .join(Player, Player.id == Prediction.player_id)
            .where(Prediction.match_id == match.id)
            .order_by(Player.alias, Player.id)
        )
    )

    def serialize(prediction, alias):
        return dict(
            player_id=prediction.player_id,
            alias=alias,
            white_score=prediction.white_score,
            black_score=prediction.black_score,
            category=category(prediction.white_score, prediction.black_score),
            in_contest=prediction.scoring_version == 2,
            revision=prediction.revision,
            approved_version=prediction.approved_version,
            updated_at=prediction.updated_at,
            points=points(prediction.white_score, prediction.black_score, *actual)
            if actual
            else None,
            teams_changed=match.approved_version is None
            or prediction.approved_version != match.approved_version,
        )

    return dict(
        server_time=at,
        deadline=match.starts_at,
        available=available,
        closed=closed,
        approved_version=match.approved_version,
        count=len(rows),
        mine=next((serialize(p, alias) for p, alias in rows if p.player_id == viewer), None),
        forecasts=[serialize(p, alias) for p, alias in rows] if closed else [],
        actual=dict(white=actual.white, black=actual.black) if actual else None,
    )


def save(db, actor, match, body):
    # The caller locks the match first, so time is checked after any lock wait.
    accepted_at = now()
    if accepted_at >= match.starts_at:
        raise DomainError("Приём прогнозов завершён: игра уже началась", 409)
    if match.status != "approved" or match.approved_version is None:
        raise DomainError("Прогнозы доступны после утверждения составов", 409)
    if body.approved_version != match.approved_version:
        raise DomainError("Составы изменились. Проверьте команды и повторите прогноз.", 409)
    prediction = db.get(Prediction, (match.id, actor))
    if body.revision != (prediction.revision if prediction else 0):
        raise DomainError("Прогноз изменён в другой вкладке. Обновите страницу.", 409)
    if prediction is None:
        prediction = Prediction(
            match_id=match.id,
            player_id=actor,
            white_score=body.white_score,
            black_score=body.black_score,
            approved_version=match.approved_version,
        )
        db.add(prediction)
    else:
        prediction.white_score, prediction.black_score = body.white_score, body.black_score
        prediction.approved_version = match.approved_version
        prediction.revision += 1
    prediction.updated_at = accepted_at
    prediction.scoring_version = 2
    db.flush()
    # Do not expose still-secret score values through the administrative audit API.
    audit(db, actor, "prediction.saved", match.id, player_id=actor, revision=prediction.revision)


def validate_reschedule(db, match, starts_at):
    if starts_at == match.starts_at:
        return
    at = now()
    if at >= match.starts_at:
        raise DomainError(
            "Время начала уже наступило. Перенос времени не может заново открыть прогнозы."
        )
    if starts_at <= at and db.scalar(
        select(Prediction.player_id).where(Prediction.match_id == match.id).limit(1)
    ):
        raise DomainError("Для игры с прогнозами новое время начала должно быть в будущем")
