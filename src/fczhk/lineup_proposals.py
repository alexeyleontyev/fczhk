"""Member proposals are independent of official assignments and chat publications."""

from sqlalchemy import select

from . import lineups, results, services
from .db import now
from .models import LineupProposal, MatchResult
from .ratings import lock_ratings
from .services import DomainError


def editable(db, match):
    return (
        match.status in ("open", "finalized", "approved")
        and now() < match.starts_at
        and not db.get(MatchResult, match.id)
    )


def ensure_editable(db, match):
    if not editable(db, match):
        raise DomainError("Предлагать и изменять варианты можно только до начала игры", 409)


def person_key(players):
    return {(p["registration_id"], p["player_id"], p["position"]) for p in players}


def roster_stale(proposal, current):
    return proposal.roster_version != current["roster_version"] or person_key(
        proposal.data["players"]
    ) != person_key(current["players"])


def public(proposal, current, people, canonical):
    author = people[canonical[proposal.author_id]]
    players = [
        {
            **p,
            "player_id": canonical.get(p["player_id"], p["player_id"]),
            "alias": people[canonical[p["player_id"]]].display_alias,
        }
        for p in proposal.data["players"]
    ]
    return dict(
        id=proposal.id,
        author_id=author.id,
        author=author.display_alias,
        revision=proposal.revision,
        roster_version=proposal.roster_version,
        fingerprint=proposal.fingerprint,
        updated_at=proposal.updated_at,
        roster_stale=roster_stale(proposal, current),
        ratings_changed=proposal.fingerprint != current["fingerprint"],
        **{k: proposal.data[k] for k in ("assignments", "placements")},
        players=players,
    )


def listing(db, actor, match, cfg):
    current = lineups.data(db, match, cfg)
    people, canonical = results.identities(db)
    proposals = list(
        db.scalars(
            select(LineupProposal)
            .where(LineupProposal.match_id == match.id)
            .order_by(LineupProposal.updated_at.desc(), LineupProposal.id)
        )
    )
    mine = next((p for p in proposals if p.author_id == actor), None)
    return dict(
        proposals=[public(p, current, people, canonical) for p in proposals if p.published],
        mine_revision=mine.revision if mine else 0,
        editable=editable(db, match),
    )


def validate(current, assignments, placements, cfg):
    players = current["players"]
    if set(assignments) != {p["registration_id"] for p in players}:
        raise DomainError("Участники изменились. Обновите свою прикидку.", 409)
    if not players or any(team not in ("white", "black") for team in assignments.values()):
        raise DomainError("Распределите всех участников по двум командам")
    field = {team: 0 for team in ("white", "black")}
    keepers = field.copy()
    for p in players:
        (keepers if p["position"] == "keeper" else field)[assignments[p["registration_id"]]] += 1
    if sum(field.values()) < cfg.min_field_players or abs(field["white"] - field["black"]) > 1:
        raise DomainError("Численность полевых должна быть равной или отличаться на одного")
    if max(keepers.values()) > 1 or (cfg.require_two_keepers and sum(keepers.values()) != 2):
        raise DomainError("Проверьте распределение вратарей")
    if abs(field["white"] + keepers["white"] - field["black"] - keepers["black"]) > 1:
        raise DomainError("Общая численность команд должна отличаться не более чем на одного")
    for rid, point in placements.items():
        if rid not in assignments or (point.y >= 0.5) != (assignments[rid] == "white"):
            raise DomainError("Положение игрока не соответствует его команде")


def save(db, actor, match, body, cfg):
    ensure_editable(db, match)
    lock_ratings(db)
    current = lineups.data(db, match, cfg)
    if body.roster_version != match.roster_version or body.fingerprint != current["fingerprint"]:
        raise DomainError("Участники или оценки изменились. Обновите свою прикидку.", 409)
    proposal = db.scalar(
        select(LineupProposal).where(
            LineupProposal.match_id == match.id, LineupProposal.author_id == actor
        )
    )
    if body.revision != (proposal.revision if proposal else 0):
        raise DomainError("Ваше предложение уже изменилось. Обновите список вариантов.", 409)
    validate(current, body.assignments, body.placements, cfg)
    if not proposal:
        proposal = LineupProposal(match_id=match.id, author_id=actor, revision=0)
        db.add(proposal)
    proposal.revision += 1
    proposal.roster_version = match.roster_version
    proposal.fingerprint = current["fingerprint"]
    proposal.data = dict(
        players=current["players"],
        assignments={str(k): v for k, v in body.assignments.items()},
        placements={str(k): v.model_dump() for k, v in body.placements.items()},
    )
    proposal.published = True
    proposal.updated_at = now()
    db.flush()
    services.audit(
        db,
        actor,
        "lineup.proposed",
        match.id,
        proposal_id=proposal.id,
        revision=proposal.revision,
    )
    return dict(id=proposal.id, revision=proposal.revision)


def withdraw(db, actor, match, revision):
    ensure_editable(db, match)
    proposal = db.scalar(
        select(LineupProposal).where(
            LineupProposal.match_id == match.id, LineupProposal.author_id == actor
        )
    )
    if not proposal or not proposal.published or proposal.revision != revision:
        raise DomainError("Предложение уже изменилось. Обновите список вариантов.", 409)
    proposal.published = False
    proposal.revision += 1
    proposal.updated_at = now()
    services.audit(
        db,
        actor,
        "lineup.proposal_withdrawn",
        match.id,
        proposal_id=proposal.id,
        revision=proposal.revision,
    )
    return dict(revision=proposal.revision)


def for_confirmation(db, match, body, current):
    proposal = db.get(LineupProposal, body.proposal_id)
    if (
        not proposal
        or proposal.match_id != match.id
        or not proposal.published
        or proposal.revision != body.proposal_revision
        or roster_stale(proposal, current)
    ):
        raise DomainError("Предложение изменилось или устарело. Обновите варианты.", 409)
    if body.source == "proposal" and (
        proposal.fingerprint != current["fingerprint"]
        or proposal.data["assignments"] != {str(k): v for k, v in body.assignments.items()}
        or proposal.data["placements"]
        != {str(k): v.model_dump() for k, v in body.placements.items()}
    ):
        raise DomainError("Вариант или оценки изменились. Сначала обновите свою прикидку.", 409)
    return dict(
        proposal_id=proposal.id, proposal_revision=proposal.revision, author_id=proposal.author_id
    )
