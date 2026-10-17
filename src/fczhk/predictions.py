"""Server deadlines and a standings read model derived from finalized results."""

from sqlalchemy import case, func, select

from .db import now
from .models import Match, MatchResult, Player, Prediction, ResultGoal
from .services import DomainError, audit


def points(white, black, actual_white, actual_black):
    predicted, actual = white - black, actual_white - actual_black
    if actual == 0:
        return int(predicted == 0)
    if predicted == 0 or (predicted > 0) != (actual > 0):
        return 0
    return 3 if predicted == actual else 1


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


def standings(db):
    scores = completed_scores()
    query = (
        select(Prediction, Player.alias, scores.c.white, scores.c.black)
        .join(Player, Player.id == Prediction.player_id)
        .outerjoin(scores, scores.c.match_id == Prediction.match_id)
        .join(Match, Match.id == Prediction.match_id)
        .where(Match.status != "cancelled")
    )
    totals = {}
    for prediction, alias, white, black in db.execute(query):
        row = totals.setdefault(
            prediction.player_id,
            dict(
                player_id=prediction.player_id,
                alias=alias,
                points=0,
                three_points=0,
                one_point=0,
                settled=0,
                predictions=0,
            ),
        )
        row["predictions"] += 1
        if white is not None:
            value = points(prediction.white_score, prediction.black_score, white, black)
            row["points"] += value
            row["three_points"] += int(value == 3)
            row["one_point"] += int(value == 1)
            row["settled"] += 1
    ordered = sorted(
        totals.values(), key=lambda row: (-row["points"], row["alias"].casefold(), row["player_id"])
    )
    previous = None
    rank = 0
    for index, row in enumerate(ordered, 1):
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
