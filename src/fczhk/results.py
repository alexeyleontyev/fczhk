"""Scores and statistics are derived from current events; audit keeps prior revisions."""

from collections import Counter

from sqlalchemy import delete, select

from .db import now
from .models import Match, MatchResult, Player, ResultGoal, ResultParticipant
from .ratings import lock_ratings
from .services import DomainError, audit, entries


def identities(db):
    people = {p.id: p for p in db.scalars(select(Player).execution_options(populate_existing=True))}
    canonical = {pid: p.merged_into or pid for pid, p in people.items()}
    return people, canonical


def result_data(db, match):
    result = db.get(MatchResult, match.id)
    people, canonical = identities(db)
    if result:
        participants = list(
            db.scalars(select(ResultParticipant).where(ResultParticipant.match_id == match.id))
        )
        goals = list(
            db.scalars(
                select(ResultGoal).where(ResultGoal.match_id == match.id).order_by(ResultGoal.id)
            )
        )
    else:
        participants = [r for r in entries(db, match.id) if r.selected and r.team]
        goals = []
    return dict(
        exists=result is not None,
        completed=bool(result and result.completed),
        version=match.version,
        score={team: sum(g.team == team for g in goals) for team in ("white", "black")},
        participants=[
            dict(
                player_id=canonical[p.player_id],
                alias=people[canonical[p.player_id]].alias,
                team=p.team,
                position=p.position,
            )
            for p in participants
        ],
        goals=[
            dict(
                id=g.id,
                team=g.team,
                kind=g.kind,
                author_id=canonical.get(g.author_id),
                assist_id=canonical.get(g.assist_id),
            )
            for g in goals
        ],
    )


def save_result(db, actor, match, body):
    if match.status not in ("approved", "completed"):
        raise DomainError("Сначала утвердите составы")
    if now() < match.starts_at:
        raise DomainError("Результат можно вводить после начала игры")
    # Serializes guest linking with identity validation and replacement of result rows.
    lock_ratings(db)
    old = result_data(db, match)
    if old["completed"] and not body.completed:
        raise DomainError("Исправления завершенного матча сохраняются как завершенный результат")
    participants = {p.player_id: p for p in body.participants}
    if len(participants) != len(body.participants):
        raise DomainError("Игрок не может участвовать дважды")
    people, _ = identities(db)
    if any(pid not in people or people[pid].merged_into for pid in participants):
        raise DomainError("Игрок не найден или его карточка объединена. Обновите результат.", 409)
    if body.completed and {p.team for p in participants.values()} != {"white", "black"}:
        raise DomainError("Подтвердите фактических участников обеих команд")
    if len({g.id for g in body.goals}) != len(body.goals):
        raise DomainError("Повторяющееся событие гола")
    for g in body.goals:
        if g.author_id is not None and g.author_id not in participants:
            raise DomainError("Автор гола должен быть фактическим участником")
        if g.assist_id is not None and g.assist_id not in participants:
            raise DomainError("Автор передачи должен быть фактическим участником")
        if g.kind == "own_goal":
            if not g.author_id or g.assist_id or participants[g.author_id].team == g.team:
                raise DomainError("Автогол: укажите автора из команды соперника без передачи")
        else:
            if g.author_id and participants[g.author_id].team != g.team:
                raise DomainError("Автор гола должен играть за команду, получившую гол")
            if g.assist_id and (
                g.assist_id == g.author_id or participants[g.assist_id].team != g.team
            ):
                raise DomainError("Передача допустима от другого участника той же команды")
    result = db.get(MatchResult, match.id)
    if not result:
        result = MatchResult(match_id=match.id)
        db.add(result)
        db.flush()
    db.execute(delete(ResultGoal).where(ResultGoal.match_id == match.id))
    db.execute(delete(ResultParticipant).where(ResultParticipant.match_id == match.id))
    db.add_all(ResultParticipant(match_id=match.id, **p.model_dump()) for p in body.participants)
    db.add_all(ResultGoal(match_id=match.id, **g.model_dump(mode="json")) for g in body.goals)
    result.completed, result.updated_at = body.completed, now()
    if body.completed:
        match.status = "completed"
    match.version += 1
    db.flush()
    new = result_data(db, match)
    audit(
        db,
        actor,
        "result.completed" if body.completed else "result.draft_saved",
        match.id,
        old=old,
        new=new,
    )
    return new


def player_stats(db, player_id):
    people, canonical = identities(db)
    if player_id not in people:
        raise DomainError("Игрок не найден", 404)
    player_id = canonical[player_id]
    total = dict(games=0, wins=0, losses=0, draws=0, goals=0, assists=0)
    history, partners = [], Counter()
    completed = list(
        db.scalars(
            select(Match)
            .join(MatchResult)
            .where(MatchResult.completed.is_(True))
            .order_by(Match.starts_at.desc(), Match.id.desc())
        )
    )
    # Batched reads avoid one query per historical match.
    rows = list(
        db.scalars(
            select(ResultParticipant).join(MatchResult).where(MatchResult.completed.is_(True))
        )
    )
    goals = list(
        db.scalars(select(ResultGoal).join(MatchResult).where(MatchResult.completed.is_(True)))
    )
    by_match, by_goals = {}, {}
    for row in rows:
        by_match.setdefault(row.match_id, []).append(row)
    for goal in goals:
        by_goals.setdefault(goal.match_id, []).append(goal)
    for match in completed:
        participants = by_match.get(match.id, [])
        mine = next((p for p in participants if canonical[p.player_id] == player_id), None)
        if not mine:
            continue
        events = by_goals.get(match.id, [])
        score = {t: sum(g.team == t for g in events) for t in ("white", "black")}
        other = "black" if mine.team == "white" else "white"
        outcome = (
            "draws"
            if score[mine.team] == score[other]
            else "wins"
            if score[mine.team] > score[other]
            else "losses"
        )
        total["games"] += 1
        total[outcome] += 1
        total["goals"] += sum(
            g.kind == "goal" and canonical.get(g.author_id) == player_id for g in events
        )
        total["assists"] += sum(canonical.get(g.assist_id) == player_id for g in events)
        partners.update(
            {
                canonical[p.player_id]
                for p in participants
                if p.team == mine.team and canonical[p.player_id] != player_id
            }
        )
        history.append(
            dict(match_id=match.id, starts_at=match.starts_at, team=mine.team, score=score)
        )
    return dict(
        player_id=player_id,
        alias=people[player_id].alias,
        **total,
        matches=history,
        partners=[
            dict(player_id=pid, alias=people[pid].alias, games=count)
            for pid, count in sorted(
                partners.items(), key=lambda item: (-item[1], people[item[0]].alias, item[0])
            )
        ],
    )
