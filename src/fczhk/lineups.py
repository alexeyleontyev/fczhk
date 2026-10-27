"""Personal previews and chat proposals; only confirmation changes shared teams."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from threading import Lock

from sqlalchemy import func, select

from . import auctions, balancing, game_balancing, game_ratings, ratings, results, services
from .db import now
from .models import (
    Audit,
    GameTemplate,
    MatchResult,
    Publication,
    ResultParticipant,
    TeamRatingSnapshot,
    TeamSnapshot,
)
from .schemas import BalanceSettings
from .services import DomainError

_calculation_lock = Lock()


def selected(db, match):
    rows = services.entries(db, match.id)
    ids = services.selection(match, rows)
    return [r for r in rows if r.id in ids]


def rating_opinions(db, match):
    if db.get(MatchResult, match.id):
        players = db.scalars(
            select(ResultParticipant).where(ResultParticipant.match_id == match.id)
        )
    else:
        players = selected(db, match)
    return {
        "authors": ratings.field_opinions(
            db, [p.player_id for p in players if p.position == "field"]
        )
    }


def data(db, match, cfg):
    regs = selected(db, match)
    people, canonical = results.identities(db)
    effective = ratings.effective(db, regs)
    skills = game_ratings.replay(db, before_day=match.game_day)["players"]
    inputs = []
    for r in sorted(regs, key=lambda row: row.id):
        skill = skills.get(r.player_id, {})
        inputs.append(
            {
                **effective[r.id],
                "alias": people[canonical[r.player_id]].display_alias,
                "game_mu": skill.get("mu", 25.0),
                "game_sigma": skill.get("sigma", 25.0 / 3),
                "game_count": skill.get("games", 0),
            }
        )
    frozen = None
    by_player = {}
    placements = {}
    if match.approved_version:
        snapshot = db.scalar(
            select(TeamRatingSnapshot)
            .join(TeamSnapshot)
            .where(
                TeamSnapshot.match_id == match.id, TeamSnapshot.version == match.approved_version
            )
        )
        if snapshot:
            placements = snapshot.data.get("lineup_placements", {})
            by_player = {
                (canonical[p["player_id"]], p["position"]): p
                for p in snapshot.data.get("lineup_inputs", snapshot.data.get("inputs", []))
            }
            frozen = [
                {
                    **p,
                    **by_player.get((p["player_id"], p["position"]), {}),
                    "registration_id": p["registration_id"],
                    "player_id": p["player_id"],
                    "alias": p["alias"],
                    "attack": by_player.get((p["player_id"], p["position"]), {}).get("attack"),
                    "defense": by_player.get((p["player_id"], p["position"]), {}).get("defense"),
                }
                for p in inputs
            ]
    assignments = {r.id: r.team for r in regs}
    if db.get(MatchResult, match.id):
        # Imported games have no registrations. Prefer saved game ratings, then
        # current community scores in the participant's actual position.
        actual = list(
            db.scalars(select(ResultParticipant).where(ResultParticipant.match_id == match.id))
        )
        current = ratings.public_averages(db, list({canonical[r.player_id] for r in actual}))
        inputs = []
        for r in actual:
            pid = canonical[r.player_id]
            saved = by_player.get((pid, r.position), {})
            has_saved = saved.get("defense") is not None and (
                r.position == "keeper" or saved.get("attack") is not None
            )
            score = saved if has_saved else current[pid][r.position]
            source = (
                "snapshot"
                if has_saved
                else "community"
                if score["defense"] is not None
                else "missing"
            )
            inputs.append(
                dict(
                    registration_id=-r.player_id,
                    player_id=pid,
                    alias=people[pid].display_alias,
                    position=r.position,
                    attack=score["attack"],
                    defense=score["defense"],
                    source=source,
                    game_mu=None,
                    game_sigma=None,
                    game_count=0,
                )
            )
        assignments = {-r.player_id: r.team for r in actual}
        actual_ids = {(canonical[r.player_id], r.position): -r.player_id for r in actual}
        placements = {
            str(actual_ids[canonical[r.player_id], r.position]): placements[str(r.id)]
            for r in regs
            if str(r.id) in placements and (canonical[r.player_id], r.position) in actual_ids
        }
        frozen = inputs
    auction = auctions.latest(db, match)
    public_auction = None
    if auction and auction.roster_version == match.roster_version:
        public = auctions.data(db, auction, None)
        public_auction = {key: public[key] for key in ("id", "status", "assignments", "prices")}
    return dict(
        version=match.version,
        roster_version=match.roster_version,
        fingerprint=hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        players=inputs,
        assignments=assignments,
        official_players=frozen,
        placements=placements,
        auction=public_auction,
        min_field_players=cfg.min_field_players,
        require_two_keepers=cfg.require_two_keepers,
        share_available=bool((template := db.get(GameTemplate, 1)) and template.extended_chat_id),
        editable=match.status in ("open", "finalized", "approved")
        and not db.get(MatchResult, match.id),
    )


def share(db, actor, match, body, cfg):
    """Queue a member's proposal without modifying registrations or official teams."""
    if match.status not in ("open", "finalized", "approved", "completed"):
        raise DomainError("Этим составом нельзя поделиться", 409)
    template = db.get(GameTemplate, 1)
    if not template or not template.extended_chat_id:
        raise DomainError("Администратор ещё не настроил чат для составов", 409)
    ratings.lock_ratings(db)
    current = data(db, match, cfg)
    if body.roster_version != match.roster_version or body.fingerprint != current["fingerprint"]:
        raise DomainError("Список или оценки изменились. Обновите доску перед публикацией.", 409)
    players = current["official_players"] if body.official else current["players"]
    if players is None:
        raise DomainError("Утверждённый состав изменился. Обновите доску.", 409)
    if set(body.assignments) != {p["registration_id"] for p in players}:
        raise DomainError("Список участников изменился. Обновите доску.", 409)
    if None in body.assignments.values() or set(body.assignments.values()) != {"white", "black"}:
        raise DomainError("Перед публикацией распределите всех игроков по двум командам")
    signature = hashlib.sha256(
        json.dumps(
            {**body.model_dump(mode="json"), "chat": template.extended_chat_id}, sort_keys=True
        ).encode()
    ).hexdigest()
    prefix = f"lineup:{match.id}:{actor.id}:"
    key = prefix + signature
    existing = db.scalar(select(Publication).where(Publication.dedupe_key == key))
    if existing:
        if existing.status in ("failed", "uncertain", "cancelled", "expired"):
            raise DomainError("Не удалось подтвердить отправку. Обратитесь к администратору.", 409)
        return dict(publication_id=existing.id, status=existing.status)
    if db.scalar(
        select(Audit.id).where(
            Audit.action == "lineup.shared",
            Audit.match_id == match.id,
            Audit.actor_id == actor.id,
            Audit.created_at > now() - timedelta(minutes=1),
        )
    ):
        raise DomainError("Подождите минуту перед публикацией нового варианта", 429)
    author = actor.display_alias
    if actor.telegram_username:
        author += f" (@{actor.telegram_username})"
    lines = [
        "⚽ Вариант состава",
        f"Автор: {author}",
        f"Игра {match.starts_at.astimezone(services.MOSCOW):%d.%m.%Y · %H:%M МСК}",
        "Суммы оценок — только полевые игроки, без вратарей.",
    ]
    for team, label in (("white", "⚪ Белые"), ("black", "⚫ Чёрные")):
        members = [p for p in players if body.assignments[p["registration_id"]] == team]

        def score(kind):
            relevant = [p for p in members if p["position"] == "field"]
            known = [p[kind] for p in relevant if p[kind] is not None]
            if not known:
                return "—"
            value = f"{sum(known):.2f}".rstrip("0").rstrip(".").replace(".", ",")
            return ("≥ " if len(known) < len(relevant) else "") + value

        values = [
            p[kind] for p in members if p["position"] == "field" for kind in ("attack", "defense")
        ]
        known = [value for value in values if value is not None]
        total = f"{sum(known):.2f}".rstrip("0").rstrip(".").replace(".", ",") if known else "—"
        if known and len(known) < len(values):
            total = "≥ " + total
        lines.extend(
            [
                "",
                f"{label} · {len(members)}",
                f"Атака {score('attack')} · Защита {score('defense')} · Σ {total}",
            ]
        )
        for p in sorted(
            members, key=lambda p: (p["position"] != "keeper", p["alias"], p["player_id"])
        ):
            lines.append(("🧤 " if p["position"] == "keeper" else "") + p["alias"])
    version = (
        db.scalar(
            select(func.max(Publication.version)).where(
                Publication.match_id == match.id, Publication.kind == "lineup_share"
            )
        )
        or 0
    ) + 1
    publication = Publication(
        match_id=match.id,
        kind="lineup_share",
        version=version,
        dedupe_key=key,
        chat_id=template.extended_chat_id,
        text="\n".join(lines),
    )
    db.add(publication)
    db.flush()
    services.audit(
        db,
        actor.id,
        "lineup.shared",
        match.id,
        publication_id=publication.id,
        assignments=body.assignments,
    )
    return dict(publication_id=publication.id, status=publication.status)


def complete_keepers(players, assignments):
    result = {
        p["registration_id"]: assignments.get(
            str(p["registration_id"]), assignments.get(p["registration_id"])
        )
        for p in players
    }
    counts = {
        team: sum(result[p["registration_id"]] == team for p in players if p["position"] == "field")
        for team in ("white", "black")
    }
    taken = set()
    for p in players:
        if p["position"] != "keeper":
            continue
        rid = p["registration_id"]
        available = [team for team in counts if team not in taken]
        if not available:
            result[rid] = None
            continue
        team = result[rid] if result[rid] in available else min(available, key=counts.get)
        result[rid] = team
        counts[team] += 1
        taken.add(team)
    return result


@lru_cache(maxsize=32)
def _generate(serialized, method):
    inputs = json.loads(serialized)
    settings = BalanceSettings(method=method)
    return (game_balancing.generate if method == "game" else balancing.generate)(inputs, settings)


def preview(db, match, cfg, method):
    services.ensure_pregame(db, match)
    if match.status not in ("open", "finalized", "approved"):
        raise DomainError("Подбор недоступен для этой игры", 409)
    current = data(db, match, cfg)
    field = [row for row in current["players"] if row["position"] == "field"]
    if method == "community" and any(p["source"] == "missing" for p in field):
        raise DomainError(
            "Нужны оценки полевых: "
            + ", ".join(p["alias"] for p in field if p["source"] == "missing")
        )
    try:
        # Fixed settings and a bounded cache avoid arbitrary, costly parameter searches.
        with _calculation_lock:
            result = deepcopy(_generate(json.dumps(field, sort_keys=True), method))
    except ValueError as exc:
        raise DomainError(str(exc)) from exc
    for variant in result["variants"]:
        variant["assignments"] = complete_keepers(current["players"], variant["assignments"])
    return {**current, "method": method, "result": result}


def confirm(db, actor, match, body, cfg):
    services.ensure_pregame(db, match)
    auctions.guard(db, match)
    if match.status not in ("finalized", "approved"):
        raise DomainError("Сначала финализируйте список", 409)
    ratings.lock_ratings(db)
    current = data(db, match, cfg)
    if body.roster_version != match.roster_version or body.fingerprint != current["fingerprint"]:
        raise DomainError("Список или оценки изменились. Обновите доску перед подтверждением.", 409)
    if set(body.assignments) != {p["registration_id"] for p in current["players"]}:
        raise DomainError("Список участников изменился. Обновите доску.", 409)
    for rid, point in body.placements.items():
        team = body.assignments.get(rid)
        if team is None or (point.y >= 0.5) != (team == "white"):
            raise DomainError("Положение игрока не соответствует его команде", 400)
    if body.source in ("community", "game"):
        run = ratings.create_run(db, actor, match, BalanceSettings(method=body.source))
        ratings.apply_run(db, actor, match, run.id, body.variant)
        services.save_teams(db, actor, match, body.assignments)
    else:
        services.save_teams(db, actor, match, body.assignments, reset=True)
    services.approve(db, actor, match, cfg)
    snapshot = db.scalar(
        select(TeamRatingSnapshot)
        .join(TeamSnapshot)
        .where(TeamSnapshot.match_id == match.id, TeamSnapshot.version == match.approved_version)
    )
    snapshot.data = {
        **snapshot.data,
        "lineup_inputs": current["players"],
        "lineup_placements": {str(rid): p.model_dump() for rid, p in body.placements.items()},
    }
    services.audit(
        db,
        actor,
        "lineup.confirmed",
        match.id,
        source=body.source,
        variant=body.variant,
        fingerprint=body.fingerprint,
    )
    return services.match_data(db, match)
