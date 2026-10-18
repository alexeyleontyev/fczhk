"""Scores and statistics are derived from current events; audit keeps prior revisions."""

from collections import Counter

from sqlalchemy import delete, select

from .db import now
from .models import Audit, Match, MatchResult, Player, Publication, ResultGoal, ResultParticipant
from .ratings import lock_ratings
from .services import MOSCOW, DomainError, audit, entries


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
    source = db.scalar(
        select(Audit)
        .where(Audit.match_id == match.id, Audit.action == "history.imported")
        .order_by(Audit.id.desc())
        .limit(1)
    )
    switches = source.data.get("assist_team_switches", []) if source else []
    return dict(
        exists=result is not None,
        completed=bool(result and result.completed),
        version=match.version,
        score={team: sum(g.team == team for g in goals) for team in ("white", "black")},
        assist_team_switches=[
            {**item, "player_id": canonical.get(item["player_id"], item["player_id"])}
            for item in switches
        ],
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


def result_text(match, data, corrected=False):
    people = {p["player_id"]: p["alias"] for p in data["participants"]}
    score = data["score"]
    title = "🏁 Исправленный итог игры" if corrected else "🏁 Игра завершена"
    lines = [
        title,
        f"ФКЖК · {match.starts_at.astimezone(MOSCOW):%d.%m.%Y · %H:%M МСК}",
        f"📍 {match.location}",
        f"⚪ Белые {score['white']} : {score['black']} Чёрные ⚫",
        "Ничья"
        if score["white"] == score["black"]
        else "Победа белых"
        if score["white"] > score["black"]
        else "Победа чёрных",
    ]
    for team, label in (("white", "⚪ Белые"), ("black", "⚫ Чёрные")):
        lines.extend(["", label])
        for player in sorted(
            data["participants"],
            key=lambda p: (p["position"] != "keeper", p["alias"], p["player_id"]),
        ):
            if player["team"] == team:
                lines.append(("🧤 " if player["position"] == "keeper" else "") + player["alias"])
        lines.append("Голы и передачи:")
        goals = [g for g in data["goals"] if g["team"] == team]
        if not goals:
            lines.append("Голов нет")
        for number, goal in enumerate(goals, 1):
            author = people.get(goal["author_id"], "автор не указан")
            if goal["kind"] == "own_goal":
                lines.append(f"{number}. Автогол — {author}")
            else:
                assist = people.get(goal["assist_id"], "не указана")
                lines.append(f"{number}. ⚽ {author} · передача: {assist}")
    return "\n".join(lines)


def publish_result(db, match, data, cfg, corrected=False):
    # The match lock serializes corrections and publication revisions with the result write.
    for previous in db.scalars(
        select(Publication).where(
            Publication.match_id == match.id,
            Publication.kind == "result",
            Publication.stale.is_(False),
        )
    ):
        previous.stale = True
        if previous.status == "pending":
            previous.status = "cancelled"
    db.add(
        Publication(
            match_id=match.id,
            kind="result",
            version=match.version,
            chat_id=cfg.publication_chat_id,
            text=result_text(match, data, corrected),
        )
    )
    db.flush()


def save_result(db, actor, match, body, cfg):
    if match.status not in ("approved", "completed"):
        raise DomainError("Сначала утвердите составы")
    if now() < match.starts_at:
        raise DomainError("Результат можно вводить после начала игры")
    # Serializes guest linking with identity validation and replacement of result rows.
    lock_ratings(db)
    old = result_data(db, match)
    switches = {
        (item["goal_id"], item["player_id"], item["team"]) for item in old["assist_team_switches"]
    }
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
            if g.assist_id or (g.author_id and participants[g.author_id].team == g.team):
                raise DomainError(
                    "Автогол: автор из команды соперника либо неизвестен; без передачи"
                )
        else:
            if g.author_id and participants[g.author_id].team != g.team:
                raise DomainError("Автор гола должен играть за команду, получившую гол")
            if g.assist_id and (
                g.assist_id == g.author_id
                or (
                    participants[g.assist_id].team != g.team
                    and (str(g.id), g.assist_id, g.team) not in switches
                )
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
    if body.completed and (
        not old["completed"]
        or sorted(old["participants"], key=lambda p: p["player_id"])
        != sorted(new["participants"], key=lambda p: p["player_id"])
        or old["goals"] != new["goals"]
    ):
        publish_result(db, match, new, cfg, corrected=old["completed"])
    audit(
        db,
        actor,
        "result.completed" if body.completed else "result.draft_saved",
        match.id,
        old=old,
        new=new,
    )
    return new


def win_rate(wins: int, draws: int, games: int) -> float | None:
    return 100 * (2 * wins + draws) / (2 * games) if games else None


def player_stats(db, player_id, season: str | None = None):
    people, canonical = identities(db)
    if player_id not in people:
        raise DomainError("Игрок не найден", 404)
    player_id = canonical[player_id]
    total = dict(games=0, wins=0, losses=0, draws=0, goals=0, assists=0)
    history, partners = [], Counter()
    partner_outcomes = {outcome: Counter() for outcome in ("wins", "draws", "losses")}
    completed_ids = select(Match.id).join(MatchResult).where(MatchResult.completed.is_(True))
    if season is not None:
        completed_ids = completed_ids.where(Match.season == season)
    completed = list(
        db.scalars(
            select(Match)
            .join(MatchResult)
            .where(Match.id.in_(completed_ids))
            .order_by(Match.starts_at.desc(), Match.id.desc())
        )
    )
    # Batched reads avoid one query per historical match.
    rows = list(
        db.scalars(select(ResultParticipant).where(ResultParticipant.match_id.in_(completed_ids)))
    )
    goals = list(db.scalars(select(ResultGoal).where(ResultGoal.match_id.in_(completed_ids))))
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
        match_goals = sum(
            g.kind == "goal" and canonical.get(g.author_id) == player_id for g in events
        )
        match_assists = sum(canonical.get(g.assist_id) == player_id for g in events)
        total["goals"] += match_goals
        total["assists"] += match_assists
        teammates = {
            canonical[p.player_id]
            for p in participants
            if p.team == mine.team and canonical[p.player_id] != player_id
        }
        partners.update(teammates)
        partner_outcomes[outcome].update(teammates)
        history.append(
            dict(
                match_id=match.id,
                starts_at=match.starts_at,
                team=mine.team,
                score=score,
                goals=match_goals,
                assists=match_assists,
            )
        )
    return dict(
        player_id=player_id,
        alias=people[player_id].alias,
        **total,
        win_rate=win_rate(total["wins"], total["draws"], total["games"]),
        matches=history,
        partners=[
            dict(
                player_id=pid,
                alias=people[pid].alias,
                games=count,
                wins=partner_outcomes["wins"][pid],
                draws=partner_outcomes["draws"][pid],
                losses=partner_outcomes["losses"][pid],
                win_rate=win_rate(
                    partner_outcomes["wins"][pid], partner_outcomes["draws"][pid], count
                ),
            )
            for pid, count in sorted(
                partners.items(), key=lambda item: (-item[1], people[item[0]].alias, item[0])
            )
        ],
    )


def leaderboards(db, season: str | None = None):
    """Public all-time or per-season totals from completed results."""
    people, canonical = identities(db)
    completed_ids = select(Match.id).join(MatchResult).where(MatchResult.completed.is_(True))
    if season is not None:
        completed_ids = completed_ids.where(Match.season == season)
    completed = set(db.scalars(completed_ids))
    participants = list(
        db.scalars(select(ResultParticipant).where(ResultParticipant.match_id.in_(completed_ids)))
    )
    goals = list(db.scalars(select(ResultGoal).where(ResultGoal.match_id.in_(completed_ids))))
    scores = {match_id: {"white": 0, "black": 0} for match_id in completed}
    totals = {}
    for goal in goals:
        scores[goal.match_id][goal.team] += 1
        if goal.kind == "goal" and goal.author_id is not None:
            pid = canonical[goal.author_id]
            totals.setdefault(pid, _empty_total())["goals"] += 1
        if goal.assist_id is not None:
            pid = canonical[goal.assist_id]
            totals.setdefault(pid, _empty_total())["assists"] += 1
    for participant in participants:
        pid = canonical[participant.player_id]
        row = totals.setdefault(pid, _empty_total())
        own = scores[participant.match_id][participant.team]
        other = scores[participant.match_id]["black" if participant.team == "white" else "white"]
        row["games"] += 1
        if own > other:
            row["wins"] += 1
            row["points"] += 3
        elif own == other:
            row["draws"] += 1
            row["points"] += 1
        else:
            row["losses"] += 1
    players = [
        dict(
            player_id=pid,
            alias=people[pid].alias,
            **total,
            win_rate=win_rate(total["wins"], total["draws"], total["games"]),
            goal_assist=total["goals"] + total["assists"],
        )
        for pid, total in totals.items()
        if total["games"]
    ]
    metrics = ("points", "win_rate", "goals", "assists", "goal_assist")
    return {
        "matches": len(completed),
        "boards": {
            metric: sorted(
                players,
                key=lambda row: (-row[metric], -row["games"], row["alias"], row["player_id"]),
            )
            for metric in metrics
        },
    }


def _empty_total():
    return dict(games=0, wins=0, draws=0, losses=0, points=0, goals=0, assists=0)
