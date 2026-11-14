"""Betting markets: prices from the score model, frozen per approved line-up.

A selection is a string id such as ``1x2:a``, ``total:under:10.5``, ``handicap:b:+1.5``,
``team:a:over:5.5`` or ``player:42:over:1.5`` (team ``a`` is white, ``b`` black). Every line is a
half line, so a selection can only win or lose. Score selections are masks on the score matrix;
player selections split the team's goals between named players and everybody else: given the
team scored x, the named players' goals are multinomial with their scoring shares. A combination
is priced from the joint probability of all its selections, evaluated per posterior draw.

Margins depend on the fair probability of an outcome (``margin_curve``): small at even money,
large on long shots, and scaled per market and side.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from threading import Lock

import numpy as np
from scipy import stats
from sqlalchemy import func, select

from . import odds_model as om
from .db import now
from .guest_keepers import SHARED_KEEPER_ALIASES
from .models import (
    Match,
    MatchOdds,
    MatchResult,
    Player,
    PricingModel,
    ResultGoal,
    ResultParticipant,
    TeamSnapshot,
)
from .services import DomainError

MIN_MATCHES = 10  # completed matches needed before the first odds
N_DRAWS = 400
MIN_VOTES = 3  # a rating from fewer voters keeps only votes / 3 of its distance from the average
MAX_LEGS = 10
IMPOSSIBLE = 1e-9  # a combination below this joint probability is not offered
IMPLIED_TOL = 1e-9  # relative: a selection that moves the joint probability less is implied
PLAYER_MIN_EXP = 1.0
PLAYER_RANGE = (0.25, 0.75)
PLAYER_LINES = (0.5, 1.5, 2.5, 3.5)
# Exact scores: the most likely ones, with the gaps inside each row and column filled, 8 to 12.
SCORES = (8, 12)
# Every exact score is a 2-4% shot; the curve would put 150%+ on it, so it gets a flat margin.
SCORE_MARGIN = 0.20

# Margin per outcome by fair probability: 6.5% at even money, 3% on a 95% favourite, 100% on a
# 5% long shot, log-linear in the log-odds in between, growing below 5% up to a cap.
MARGIN_ANCHORS = ((0.05, 1.00), (0.50, 0.065), (0.95, 0.03))
MARGIN_CAP = 3.0
MIN_ODDS = 1.01
# Unders carry three times the base margin: the model has run a little high on goals, so the
# under is where the book is exposed. Player overs are the least tested market.
MARGIN_SCALE = {
    "1x2": 1.0,
    "handicap": 1.0,
    "total_over": 1.0,
    "total_under": 3.0,
    "player_over": 1.6,
    "player_under": 3.0,
}
TEAM_NAME = {"a": "Белые", "b": "Чёрные"}
SELECTION = re.compile(
    r"^(?:1x2:(?P<outcome>a|draw|b)"
    r"|total:(?P<t_side>over|under):(?P<t_line>\d+\.5)"
    r"|handicap:(?P<h_team>a|b):(?P<h_line>[+-]\d+\.5)"
    r"|team:(?P<tt_team>a|b):(?P<tt_side>over|under):(?P<tt_line>\d+\.5)"
    r"|player:(?P<pid>\d+):(?P<p_side>over|under):(?P<p_line>\d+\.5)"
    r"|score:(?P<s_white>\d{1,2}):(?P<s_black>\d{1,2}))$"
)


# --------------------------------------------------------------------------- margins


def margin_curve(p, scale: float = 1.0):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    x = np.log(p / (1 - p))
    xs = np.array([np.log(a / (1 - a)) for a, _ in MARGIN_ANCHORS])
    ys = np.log([m for _, m in MARGIN_ANCHORS])
    y = np.interp(x, xs, ys)
    slope = (ys[1] - ys[0]) / (xs[1] - xs[0])
    y = np.where(x < xs[0], ys[0] + slope * (x - xs[0]), y)
    return np.minimum(np.exp(y) * scale, MARGIN_CAP)


def leg_margin(leg: dict, p: float) -> float:
    return SCORE_MARGIN if leg["kind"] == "score" else float(margin_curve(p, leg_scale(leg)))


def leg_scale(leg: dict) -> float:
    if leg["kind"] == "score":
        return 1.0
    if leg["kind"] in ("1x2", "handicap"):
        return MARGIN_SCALE[leg["kind"]]
    kind = "player" if leg["kind"] == "player" else "total"
    return MARGIN_SCALE[f"{kind}_{leg['side']}"]


# --------------------------------------------------------------------------- selections


def parse(selection: str) -> dict:
    m = SELECTION.match(selection)
    if not m:
        raise DomainError(f"Неизвестный исход: {selection}", 422)
    g = m.groupdict()
    if g["outcome"]:
        return dict(kind="1x2", side=g["outcome"])
    if g["t_side"]:
        return dict(kind="total", side=g["t_side"], line=float(g["t_line"]))
    if g["h_team"]:
        return dict(kind="handicap", side=g["h_team"], line=float(g["h_line"]))
    if g["s_white"]:
        return dict(kind="score", white=int(g["s_white"]), black=int(g["s_black"]))
    if g["tt_team"]:
        return dict(kind="team", team=g["tt_team"], side=g["tt_side"], line=float(g["tt_line"]))
    return dict(kind="player", player=int(g["pid"]), side=g["p_side"], line=float(g["p_line"]))


def label(leg: dict, names: dict[int, str]) -> str:
    side = {"over": "больше", "under": "меньше"}
    if leg["kind"] == "1x2":
        return {"a": "Победа белых", "draw": "Ничья", "b": "Победа чёрных"}[leg["side"]]
    if leg["kind"] == "total":
        return f"Тотал {side[leg['side']]} {leg['line']:g}"
    if leg["kind"] == "handicap":
        return f"{TEAM_NAME[leg['side']]} фора {leg['line']:+g}"
    if leg["kind"] == "score":
        return f"Счёт {leg['white']}:{leg['black']}"
    if leg["kind"] == "team":
        return f"{TEAM_NAME[leg['team']]}: тотал {side[leg['side']]} {leg['line']:g}"
    return f"{names.get(leg['player'], 'Игрок')}: голов {side[leg['side']]} {leg['line']:g}"


def score_mask(legs: list[dict], size: int) -> np.ndarray:
    x, y = np.indices((size, size))
    mask = np.ones((size, size), dtype=bool)
    for leg in legs:
        if leg["kind"] == "1x2":
            mask &= {"a": x > y, "draw": x == y, "b": x < y}[leg["side"]]
        elif leg["kind"] == "total":
            mask &= (x + y > leg["line"]) if leg["side"] == "over" else (x + y < leg["line"])
        elif leg["kind"] == "handicap":
            mask &= (x - y + leg["line"] > 0) if leg["side"] == "a" else (y - x + leg["line"] > 0)
        elif leg["kind"] == "team":
            goals = x if leg["team"] == "a" else y
            mask &= (goals > leg["line"]) if leg["side"] == "over" else (goals < leg["line"])
        elif leg["kind"] == "score":
            mask &= (x == leg["white"]) & (y == leg["black"])
    return mask


def _conditional(shares: np.ndarray, allowed: np.ndarray) -> np.ndarray:
    """P(each listed player's goals are allowed | team goals = x), shape (S, K+1): the
    multinomial is peeled one player at a time."""
    n_draws, m = shares.shape
    size = allowed.shape[1]
    r_in, r_out = np.indices((size, size))
    g = r_in - r_out
    state = np.broadcast_to(np.eye(size), (n_draws, size, size)).copy()
    left = np.ones(n_draws)
    for j in range(m):
        q = np.clip(shares[:, j] / np.maximum(left, 1e-12), 0.0, 1.0)
        step = stats.binom.pmf(g[None], r_in[None], q[:, None, None])
        step = step * (allowed[j][np.clip(g, 0, size - 1)] & (g >= 0))[None]
        state = state @ step
        left = left - shares[:, j]
    return state.sum(axis=2)


def probability(sim: om.Simulation, legs: list[dict]) -> float:
    size = sim.mats.shape[1]
    weights = sim.mats * score_mask(legs, size)[None]
    goals = np.arange(size)
    for team, letter, axis in (("white", "a", "sxy,sx->sxy"), ("black", "b", "sxy,sy->sxy")):
        ids, shares = sim.shares[team]
        allowed: dict[int, np.ndarray] = {}
        for leg in legs:
            if leg["kind"] == "player" and leg["player"] in ids:
                col = ids.index(leg["player"])
                ok = goals > leg["line"] if leg["side"] == "over" else goals < leg["line"]
                allowed[col] = allowed.get(col, np.ones(size, dtype=bool)) & ok
        if allowed:
            cols = list(allowed)
            cond = _conditional(shares[:, cols], np.array([allowed[c] for c in cols]))
            weights = np.einsum(axis, weights, cond)
    return float(weights.sum(axis=(1, 2)).mean())


def essential(sim: om.Simulation, legs: list[dict], p: float) -> list[int]:
    """Indices of the selections that matter. A selection implied by the others (over 10.5
    next to over 11.5, a team scoring next to one of its players scoring) does not change the
    joint probability, so it must not add margin either. Broader selections are tried first."""
    keep = list(range(len(legs)))
    if len(legs) < 2:
        return keep
    order = sorted(keep, key=lambda i: -probability(sim, [legs[i]]))
    for i in order:
        rest = [j for j in keep if j != i]
        if rest and abs(probability(sim, [legs[j] for j in rest]) - p) <= IMPLIED_TOL * max(
            p, 1e-12
        ):
            keep = rest
    return keep


def price(sim: om.Simulation, legs: list[dict]) -> dict:
    """Fair probability and offered odds. Selections implied by the others are dropped first.
    The offered price uses the larger of the joint probability and the product of single
    probabilities (the joint model was not shown to beat independence on combinations), with
    the larger of the legs' compounded margins and the margin curve applied to the combination
    as one outcome."""
    p = probability(sim, legs)
    if p < IMPOSSIBLE:
        # Mutually exclusive selections: the joint probability, not independence, decides.
        return dict(p=p, singles=[], independent=0.0, odds=None, implied=[])
    keep = essential(sim, legs, p)
    implied = [i for i in range(len(legs)) if i not in keep]
    legs = [legs[i] for i in keep]
    singles = [probability(sim, [leg]) for leg in legs] if len(legs) > 1 else [p]
    independent = float(np.prod(singles))
    priced = max(p, independent)
    per_leg = float(np.prod([1 + leg_margin(leg, q) for leg, q in zip(legs, singles, strict=True)]))
    if any(leg["kind"] == "score" for leg in legs):
        whole = per_leg  # an exact score is a long shot by design; the curve does not apply
    else:
        whole = 1 + float(margin_curve(priced, max(leg_scale(leg) for leg in legs)))
    odds = max(MIN_ODDS, round(1 / (priced * max(per_leg, whole)), 2))
    return dict(p=p, singles=singles, independent=independent, odds=odds, implied=implied)


def central_scores(mat: np.ndarray) -> list[tuple[int, int]]:
    """The most likely scores with no gaps: if 5:4 and 5:6 are in, so is 5:5 (within a row and
    within a column). The largest top-k whose filled set still has at most SCORES[1] scores."""
    order = np.dstack(np.unravel_index(np.argsort(-mat, axis=None), mat.shape))[0]
    best: set[tuple[int, int]] = set()
    for k in range(SCORES[0], SCORES[1] + 1):
        chosen = {(int(a), int(b)) for a, b in order[:k]}
        while True:
            filled = set(chosen)
            for a in {a for a, _ in chosen}:
                cols = [b for x, b in chosen if x == a]
                filled |= {(a, b) for b in range(min(cols), max(cols) + 1)}
            for b in {b for _, b in chosen}:
                rows = [a for a, y in chosen if y == b]
                filled |= {(a, b) for a in range(min(rows), max(rows) + 1)}
            if filled == chosen:
                break
            chosen = filled
        if len(chosen) > SCORES[1]:
            break
        best = chosen
    if not best:  # the top SCORES[0] already spread too wide: keep them as they are
        best = {(int(a), int(b)) for a, b in order[: SCORES[0]]}
    return sorted(best, key=lambda s: (s[0] - s[1], s[0] + s[1]), reverse=True)


def _main_line(values: np.ndarray, probs: np.ndarray) -> float:
    i = int(np.argmin(np.abs(np.cumsum(probs) - 0.5)))
    return float(values[i]) + 0.5


def catalogue(sim: om.Simulation, names: dict[int, str]) -> list[dict]:
    """Every offered selection with its fair probability and offered odds."""
    mat = sim.mats.mean(axis=0)
    size = mat.shape[0]
    k = np.arange(size)
    total = np.bincount(np.add.outer(k, k).ravel(), weights=mat.ravel())
    margin_values = np.arange(-(size - 1), size)
    margin = np.bincount((np.subtract.outer(k, k) + size - 1).ravel(), weights=mat.ravel())
    t0 = _main_line(np.arange(len(total)), total)
    h0 = -_main_line(margin_values, margin)
    ids = ["1x2:a", "1x2:draw", "1x2:b"]
    for step in (-2, -1, 0, 1, 2):
        line = t0 + step
        if line > 0:
            ids += [f"total:over:{line:g}", f"total:under:{line:g}"]
    for step in (-2, -1, 0, 1, 2):
        line = h0 + step
        ids += [f"handicap:a:{line:+g}", f"handicap:b:{-line:+g}"]
    for team, axis in (("a", 1), ("b", 0)):
        pmf = mat.sum(axis=axis)
        base = _main_line(k, pmf)
        for step in (-1, 0, 1):
            if base + step > 0:
                ids += [f"team:{team}:over:{base + step:g}", f"team:{team}:under:{base + step:g}"]
    ids += [f"score:{a}:{b}" for a, b in central_scores(mat)]
    team_pmf = {"white": mat.sum(axis=1), "black": mat.sum(axis=0)}  # mat[white goals, black goals]
    group = {
        "1x2": "Исход",
        "total": "Тотал матча",
        "handicap": "Фора",
        "team": "Тотал команды",
        "score": "Точный счёт",
    }
    out = []
    for sid in ids:
        leg = parse(sid)
        result = price(sim, [leg])
        if result["odds"] is not None:
            out.append(
                dict(
                    id=sid,
                    group=group[leg["kind"]],
                    label=label(leg, names),
                    p=result["p"],
                    odds=result["odds"],
                )
            )
    for team in ("white", "black"):
        players, shares = sim.shares[team]
        expected = float(team_pmf[team] @ k)
        for col, pid in enumerate(players):
            pi = shares[:, col]
            if expected * float(pi.mean()) <= PLAYER_MIN_EXP:
                continue
            per_draw = sim.mats.sum(axis=2) if team == "white" else sim.mats.sum(axis=1)
            for line in PLAYER_LINES:
                tail = stats.binom.sf(int(line), k[None, :], pi[:, None])
                p_over = float((tail * per_draw).sum(1).mean())
                if not PLAYER_RANGE[0] <= p_over <= PLAYER_RANGE[1]:
                    continue
                for side in ("over", "under"):
                    sid = f"player:{pid}:{side}:{line:g}"
                    leg = parse(sid)
                    result = price(sim, [leg])
                    out.append(
                        dict(
                            id=sid,
                            group="Голы игроков",
                            label=label(leg, names),
                            p=result["p"],
                            odds=result["odds"],
                        )
                    )
    return out


# --------------------------------------------------------------------------- data from the club


def _canonical(db) -> tuple[dict[int, Player], dict[int, int]]:
    people = {p.id: p for p in db.scalars(select(Player))}
    return people, {pid: p.merged_into or pid for pid, p in people.items()}


def _shared_keeper(player: Player) -> bool:
    return player.telegram_id is None and player.alias in SHARED_KEEPER_ALIASES


def community_marks(db, ids: list[int]) -> dict[int, tuple[float, float] | None]:
    """Field marks 0..5 (trimmed mean of votes); ratings from few voters are shrunk towards the
    average of well-rated players."""
    from .ratings import aggregate

    scores = aggregate(db, ids)
    raw = {
        pid: (float(a), float(d), n)
        for (pid, pos), (a, d, n) in scores.items()
        if pos == "field" and a is not None and d is not None and n > 0
    }
    solid = [v for v in raw.values() if v[2] >= MIN_VOTES]
    if not solid:
        return {pid: (a, d) for pid, (a, d, _) in raw.items()}
    ca, cd = np.mean([v[0] for v in solid]), np.mean([v[1] for v in solid])
    out = {}
    for pid, (a, d, n) in raw.items():
        w = min(n / MIN_VOTES, 1.0)
        out[pid] = (float(ca + (a - ca) * w), float(cd + (d - cd) * w))
    return out


def history_from_db(db) -> om.History | None:
    people, canonical = _canonical(db)
    results = list(
        db.execute(
            select(MatchResult.match_id)
            .join(Match, Match.id == MatchResult.match_id)
            .where(MatchResult.completed.is_(True), Match.status != "cancelled")
            .order_by(Match.starts_at, Match.id)
        ).scalars()
    )
    if len(results) < MIN_MATCHES:
        return None
    parts: dict[int, list] = {}
    for r in db.scalars(select(ResultParticipant).where(ResultParticipant.match_id.in_(results))):
        parts.setdefault(r.match_id, []).append(r)
    goals: dict[int, list] = {}
    for g in db.scalars(select(ResultGoal).where(ResultGoal.match_id.in_(results))):
        goals.setdefault(g.match_id, []).append(g)
    real = lambda pid: not _shared_keeper(people[pid])  # noqa: E731
    pids = sorted(
        {canonical[r.player_id] for rows in parts.values() for r in rows if real(r.player_id)}
    )
    pos = {pid: i for i, pid in enumerate(pids)}
    marks = community_marks(db, pids)
    n_g, n_p = len(results), len(pids)
    out_a, out_b = np.zeros((n_g, n_p)), np.zeros((n_g, n_p))
    no_gk = {"white": np.ones(n_g), "black": np.ones(n_g)}
    goals_t = {"white": np.zeros(n_g, dtype=int), "black": np.zeros(n_g, dtype=int)}
    members = np.zeros((2 * n_g, n_p), dtype=bool)
    member_gk = np.zeros((2 * n_g, n_p), dtype=bool)
    team_goals = np.zeros(2 * n_g)
    scored = np.zeros(n_p)
    gk_scored = 0
    recent_total = recent_named = 0
    for gi, mid in enumerate(results):
        for r in parts.get(mid, []):
            row = 2 * gi + (r.team == "black")
            if not real(r.player_id):
                continue
            i = pos[canonical[r.player_id]]
            members[row, i] = True
            if r.position == "keeper":
                member_gk[row, i] = True
                no_gk[r.team][gi] = 0.0
            else:
                (out_a if r.team == "white" else out_b)[gi, i] = 1.0
        for g in goals.get(mid, []):
            goals_t[g.team][gi] += 1
            named = g.kind == "goal" and g.author_id is not None and real(g.author_id)
            if gi >= n_g - om.RECENT_MATCHES:
                recent_total += 1
                recent_named += named
            if named:
                row = 2 * gi + (g.team == "black")
                i = pos.get(canonical[g.author_id])
                if i is not None and members[row, i]:
                    team_goals[row] += 1
                    scored[i] += 1
                    gk_scored += int(member_gk[row, i])
    for out in (out_a, out_b):
        n = out.sum(axis=1, keepdims=True)
        out *= om.ON_PITCH / np.maximum(n, 1.0)
    return om.History(
        player_ids=pids,
        r_att=np.array([marks[p][0] if marks.get(p) else np.nan for p in pids]),
        r_def=np.array([marks[p][1] if marks.get(p) else np.nan for p in pids]),
        out_a=out_a,
        out_b=out_b,
        no_gk_a=no_gk["white"],
        no_gk_b=no_gk["black"],
        goals_a=goals_t["white"],
        goals_b=goals_t["black"],
        members=members,
        member_gk=member_gk,
        team_goals=team_goals,
        scored=scored,
        gk_scored=gk_scored,
        scorer_rate=(recent_named + 1) / (recent_total + 1),
    )


def latest_model(db) -> PricingModel | None:
    return db.scalar(select(PricingModel).order_by(PricingModel.id.desc()).limit(1))


def refit_if_needed(db) -> PricingModel | None:
    """Fit a new model when a completed result is newer than the latest model."""
    newest = db.scalar(
        select(func.max(MatchResult.updated_at)).where(MatchResult.completed.is_(True))
    )
    model = latest_model(db)
    if newest is None or (model is not None and model.source_updated_at >= newest):
        return model
    history = history_from_db(db)
    if history is None:
        return model
    data = om.fit(history)
    model = PricingModel(
        data=data, n_matches=data["n_matches"], source_updated_at=newest, created_at=now()
    )
    db.add(model)
    db.flush()
    return model


def approved_lineup(db, match: Match) -> list[dict]:
    snapshot = db.scalar(
        select(TeamSnapshot).where(
            TeamSnapshot.match_id == match.id, TeamSnapshot.version == match.approved_version
        )
    )
    if snapshot is None:
        raise DomainError("Утверждённые составы не найдены", 409)
    return snapshot.teams


def betting_open(match: Match, at=None) -> bool:
    return (
        match.status == "approved"
        and match.approved_version is not None
        and (at or now()) < match.starts_at
    )


def snapshot(db, match: Match) -> MatchOdds:
    """Odds for the match's approved line-up, computed once and then frozen."""
    if match.status not in ("approved", "completed") or match.approved_version is None:
        raise DomainError("Коэффициенты появятся после утверждения составов", 409)
    odds = db.scalar(
        select(MatchOdds).where(
            MatchOdds.match_id == match.id, MatchOdds.approved_version == match.approved_version
        )
    )
    if odds:
        return odds
    if match.status != "approved":
        raise DomainError("Коэффициенты на эту игру не рассчитывались", 404)
    model = latest_model(db)
    if model is None:
        raise DomainError(
            "Коэффициенты появятся, когда в базе будет достаточно сыгранных матчей", 409
        )
    people, canonical = _canonical(db)
    teams = approved_lineup(db, match)
    lineup = {"white": [], "black": []}
    names = {}
    for row in teams:
        pid = canonical.get(row["player_id"], row["player_id"])
        if _shared_keeper(people[pid]):
            continue
        lineup[row["team"]].append((pid, row["position"] == "keeper"))
        names[pid] = row["alias"]
    marks = community_marks(db, [pid for team in lineup.values() for pid, _ in team])
    inputs = dict(
        lineup={t: [[pid, gk] for pid, gk in players] for t, players in lineup.items()},
        marks={str(pid): list(v) for pid, v in marks.items()},
        names={str(pid): name for pid, name in names.items()},
        seed=match.id * 1000 + match.approved_version,
    )
    sim = _simulate(model.data, inputs)
    odds = MatchOdds(
        match_id=match.id,
        approved_version=match.approved_version,
        model_id=model.id,
        inputs=inputs,
        markets=catalogue(sim, names),
        created_at=now(),
    )
    db.add(odds)
    db.flush()
    _remember(odds.id, sim)
    return odds


def _simulate(model_data: dict, inputs: dict) -> om.Simulation:
    lineup = {
        t: [(int(pid), bool(gk)) for pid, gk in players] for t, players in inputs["lineup"].items()
    }
    marks = {int(pid): tuple(v) for pid, v in inputs["marks"].items()}
    return om.simulate(model_data, lineup, marks, n_draws=N_DRAWS, seed=inputs["seed"])


_CACHE: OrderedDict[int, om.Simulation] = OrderedDict()
_CACHE_LOCK = Lock()


def _remember(odds_id: int, sim: om.Simulation):
    with _CACHE_LOCK:
        _CACHE[odds_id] = sim
        _CACHE.move_to_end(odds_id)
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)


def simulation(db, odds: MatchOdds) -> om.Simulation:
    """The frozen simulation behind a snapshot: deterministic from its model and inputs."""
    with _CACHE_LOCK:
        sim = _CACHE.get(odds.id)
    if sim is None:
        sim = _simulate(db.get(PricingModel, odds.model_id).data, odds.inputs)
        _remember(odds.id, sim)
    return sim


def legs_for(odds: MatchOdds, selections: list[str]) -> list[dict]:
    if not 1 <= len(selections) <= MAX_LEGS:
        raise DomainError(f"В ставке от 1 до {MAX_LEGS} исходов", 422)
    if len(set(selections)) != len(selections):
        raise DomainError("Исход выбран дважды", 422)
    offered = {s["id"] for s in odds.markets}
    missing = [s for s in selections if s not in offered]
    if missing:
        raise DomainError("Такого исхода нет в линии на эту игру", 422)
    return [parse(s) for s in selections]


def quote(db, odds: MatchOdds, selections: list[str]) -> dict:
    legs = legs_for(odds, selections)
    names = {int(k): v for k, v in odds.inputs["names"].items()}
    result = price(simulation(db, odds), legs)
    if result["odds"] is None:
        raise DomainError("Такая комбинация невозможна", 422)
    return dict(
        odds_id=odds.id,
        selections=selections,
        labels=[label(leg, names) for leg in legs],
        odds=result["odds"],
        implied=[label(legs[i], names) for i in result["implied"]],
        probability=result["p"],
    )


def view(db, match: Match, odds: MatchOdds, admin: bool = False) -> dict:
    groups: OrderedDict[str, list] = OrderedDict()
    for s in odds.markets:
        groups.setdefault(s["group"], []).append(dict(id=s["id"], label=s["label"], odds=s["odds"]))
    return dict(
        odds_id=odds.id,
        match_id=match.id,
        approved_version=odds.approved_version,
        open=betting_open(match) and match.approved_version == odds.approved_version,
        closes_at=match.starts_at,
        created_at=odds.created_at,
        groups=[dict(name=name, selections=items) for name, items in groups.items()],
    ) | (_model_info(db, odds) if admin else {})


def _model_info(db, odds: MatchOdds) -> dict:
    """Internal details of the pricing model, for administrators only."""
    model = db.get(PricingModel, odds.model_id)
    return dict(model=dict(n_matches=model.n_matches, fitted_at=model.created_at))
