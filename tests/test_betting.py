from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import select

from fczhk import bets, odds, odds_model
from fczhk.db import now
from fczhk.models import (
    Bet,
    Match,
    MatchOdds,
    MatchResult,
    Player,
    Rating,
    Registration,
    ResultGoal,
    ResultParticipant,
    TeamSnapshot,
    WalletEntry,
)
from fczhk.services import DomainError, settle_bets


def _league(db, rng, n_matches=30):
    """Synthetic club history: rated players, completed matches drawn from a known model."""
    authors = [Player(alias=f"Оценщик {i}", telegram_id=900 + i) for i in range(3)]
    field = [Player(alias=f"Полевой {i:02d}") for i in range(18)]
    keepers = [Player(alias=f"Вратарь {i}") for i in range(2)]
    db.add_all(authors + field + keepers)
    db.flush()
    att = rng.uniform(1, 5, len(field))
    dfn = rng.uniform(1, 5, len(field))
    for i, p in enumerate(field):
        for author in authors:
            jitter = rng.normal(0, 0.2, 2)
            db.add(
                Rating(
                    author_id=author.id,
                    player_id=p.id,
                    position="field",
                    attack=int(np.clip(round((att[i] + jitter[0]) * 10), 0, 50)),
                    defense=int(np.clip(round((dfn[i] + jitter[1]) * 10), 0, 50)),
                )
            )
    za, zd = (att - att.mean()) / att.std(), (dfn - dfn.mean()) / dfn.std()
    # Assists come from their own stream, so the goals stay as they were before assists existed.
    assist_rng = np.random.default_rng(11)
    start = now() - timedelta(days=7 * (n_matches + 2))
    for g in range(n_matches):
        order = rng.permutation(len(field))
        white, black = order[:8], order[8:16]
        m = Match(
            game_day=(start + timedelta(days=7 * g)).date().isoformat(),
            starts_at=start + timedelta(days=7 * g),
            location="Поле",
            status="completed",
            approved_version=1,
        )
        db.add(m)
        db.flush()
        db.add(
            MatchResult(match_id=m.id, completed=True, updated_at=m.starts_at + timedelta(hours=2))
        )
        for team, idx, keeper in (("white", white, keepers[0]), ("black", black, keepers[1])):
            for i in idx:
                db.add(
                    ResultParticipant(
                        match_id=m.id, player_id=field[i].id, team=team, position="field"
                    )
                )
            db.add(
                ResultParticipant(match_id=m.id, player_id=keeper.id, team=team, position="keeper")
            )
        for team, own, other in (("white", white, black), ("black", black, white)):
            lam = np.exp(np.log(5.5) + 7 / 8 * (0.1 * za[own].sum() - 0.09 * zd[other].sum()))
            w = np.exp(0.5 * za[own])
            for _ in range(rng.poisson(lam)):
                scorer = field[own[rng.choice(len(own), p=w / w.sum())]].id
                mates = [field[i].id for i in own if field[i].id != scorer]
                assist = (
                    mates[assist_rng.integers(len(mates))] if assist_rng.random() < 0.6 else None
                )
                db.add(
                    ResultGoal(
                        match_id=m.id,
                        id=str(uuid4()),
                        team=team,
                        kind="goal",
                        author_id=scorer,
                        assist_id=assist,
                    )
                )
    db.flush()
    return field, keepers


def _upcoming(db, field, keepers, version=1):
    m = Match(
        game_day=(now() + timedelta(days=3)).date().isoformat(),
        starts_at=now() + timedelta(days=3),
        location="Поле",
        status="approved",
        approved_version=version,
        version=version,
    )
    db.add(m)
    db.flush()
    teams = []
    for team, players, keeper in (
        ("white", field[:8], keepers[0]),
        ("black", field[8:16], keepers[1]),
    ):
        for p, pos in [(p, "field") for p in players] + [(keeper, "keeper")]:
            teams.append(dict(player_id=p.id, alias=p.alias, position=pos, team=team))
            db.add(
                Registration(match_id=m.id, player_id=p.id, team=team, position=pos, selected=True)
            )
    db.add(TeamSnapshot(match_id=m.id, version=version, teams=teams))
    db.flush()
    return m


@pytest.fixture
def club(env):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        field, keepers = _league(db, np.random.default_rng(7))
        model = odds.refit_if_needed(db)
        m = _upcoming(db, field, keepers)
        out = dict(
            match=m.id,
            field=[p.id for p in field],
            keepers=[p.id for p in keepers],
            model=model.id,
        )
    return out


def _freebet(call, role="player"):
    return call("POST", "/wallet/freebet", role=role)


def _bet(call, mid, selections, stake, role="player", expected=201):
    o = call("GET", f"/matches/{mid}/odds", role=role)
    q = call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"], selections=selections),
        role=role,
    )
    body = dict(odds_id=o["odds_id"], selections=selections, stake=stake, odds=q["odds"])
    return call("POST", f"/matches/{mid}/bets", body, role=role, expected=expected), q


def _finish(env, call, mid, white_goals, black_goals):
    """Move kick-off into the past and save a completed result with the given scorers; a goal is
    a scorer id (or None) or a (scorer, assistant) pair."""
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        db.get(Match, mid).starts_at = now() - timedelta(hours=2)
    result = call("GET", f"/matches/{mid}/result")

    def goal(team, g):
        author, assist = g if isinstance(g, tuple) else (g, None)
        return dict(id=str(uuid4()), team=team, kind="goal", author_id=author, assist_id=assist)

    goals = [goal("white", g) for g in white_goals] + [goal("black", g) for g in black_goals]
    return call(
        "PUT",
        f"/matches/{mid}/result",
        dict(
            version=result["version"],
            completed=True,
            participants=[
                {k: p[k] for k in ("player_id", "team", "position")} for p in result["participants"]
            ],
            goals=goals,
        ),
    )


def test_model_fits_on_club_history_and_reads_the_ratings(env):
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        assert odds.refit_if_needed(db) is None  # too few matches
        _league(db, np.random.default_rng(3), n_matches=40)
        history = odds.history_from_db(db)
        assert history.goals_a.shape == (40,) and history.members.sum() == 40 * 2 * 9
        np.testing.assert_allclose(history.out_a.sum(1), 7)
        model = odds.refit_if_needed(db)
        assert model.n_matches == 40 and model.data["converged"]
        assert model.data["summary"]["beta_a"] > 0 and model.data["summary"]["beta_d"] > 0
        assert odds.refit_if_needed(db).id == model.id  # nothing new: no refit


def test_odds_are_frozen_coherent_and_carry_a_margin(env, call, club):
    o = call("GET", f"/matches/{club['match']}/odds", role="player")
    assert o["available"] and o["open"] and o["bets"] == []
    groups = {g["name"]: g["selections"] for g in o["groups"]}
    assert set(groups) >= {"Исход", "Тотал матча", "Фора", "Тотал команды"}
    outcome = {s["id"]: s["odds"] for s in groups["Исход"]}
    assert 1.05 < sum(1 / v for v in outcome.values()) < 1.35
    for line in {s["id"].rsplit(":", 1)[1] for s in groups["Тотал матча"]}:
        over = next(s["odds"] for s in groups["Тотал матча"] if s["id"] == f"total:over:{line}")
        under = next(s["odds"] for s in groups["Тотал матча"] if s["id"] == f"total:under:{line}")
        assert 1 / over + 1 / under > 1.05
    assert all(s["odds"] >= odds.MIN_ODDS for g in o["groups"] for s in g["selections"])
    # a later rating change does not move frozen prices
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        for r in db.scalars(select(Rating).where(Rating.player_id == club["field"][0])):
            r.attack, r.defense = 50, 50
    again = call("GET", f"/matches/{club['match']}/odds", role="player")
    assert again["odds_id"] == o["odds_id"] and again["groups"] == o["groups"]
    with factory() as db:
        assert (
            db.scalar(select(MatchOdds).where(MatchOdds.match_id == club["match"])).model_id
            == club["model"]
        )


def test_quotes_singles_combos_and_impossible_combinations(call, club):
    mid = club["match"]
    o = call("GET", f"/matches/{mid}/odds", role="player")
    catalogue = {s["id"]: s["odds"] for g in o["groups"] for s in g["selections"]}
    single = call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"], selections=["1x2:a"]),
        role="player",
    )
    assert single["odds"] == catalogue["1x2:a"] and single["labels"] == ["Победа белых"]
    total = next(s for s in catalogue if s.startswith("total:over:"))
    combo = call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"], selections=["1x2:a", total]),
        role="player",
    )
    assert combo["odds"] > catalogue["1x2:a"] and combo["odds"] > catalogue[total]
    impossible = call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"], selections=["1x2:a", "1x2:b"]),
        role="player",
        expected=422,
    )
    assert "невозможна" in impossible["detail"]
    call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"], selections=["total:over:99.5"]),
        role="player",
        expected=422,
    )
    call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"] + 1, selections=["1x2:a"]),
        role="player",
        expected=409,
    )


def test_combination_probability_matches_brute_force_simulation(env, call, club):
    call("GET", f"/matches/{club['match']}/odds", role="player")
    _, factory, _, _, _ = env
    with factory() as db:
        snapshot = db.scalar(select(MatchOdds))
        sim = odds.simulation(db, snapshot)
    rng = np.random.default_rng(0)
    n, size = 200_000, sim.mats.shape[1]
    draw = rng.integers(0, len(sim.mats), n)
    flat = sim.mats.reshape(len(sim.mats), -1)
    cells = np.array([rng.choice(size * size, p=flat[d] / flat[d].sum()) for d in draw[:20000]])
    x, y = np.divmod(cells, size)
    ids, shares = sim.shares["white"]
    pa = shares[draw[:20000], 0]
    first = rng.binomial(x, pa)
    legs = [odds.parse("1x2:a"), odds.parse(f"player:{ids[0]}:over:0.5")]
    hit = (x > y) & (first >= 1)
    assert odds.probability(sim, legs) == pytest.approx(
        hit.mean(), abs=4 * np.sqrt(hit.mean() / len(hit))
    )


def test_bets_need_balance_current_odds_and_an_open_market(env, call, club):
    mid = club["match"]
    call(
        "POST",
        f"/matches/{mid}/bets",
        dict(odds_id=1, selections=["1x2:a"], stake=10, odds=2.0),
        role=None,
        expected=401,
    )
    _, quote = _bet(call, mid, ["1x2:a"], 10, expected=409)  # no points yet
    _freebet(call)
    placed, quote = _bet(call, mid, ["1x2:a"], 10)
    assert placed["bet"]["status"] == "open" and placed["bet"]["odds"] == quote["odds"]
    assert placed["wallet"]["balance"] == 90
    o = call("GET", f"/matches/{mid}/odds", role="player")
    wrong = dict(
        odds_id=o["odds_id"], selections=["1x2:a"], stake=1, odds=round(quote["odds"] + 0.5, 2)
    )
    assert (
        "Коэффициент изменился"
        in call("POST", f"/matches/{mid}/bets", wrong, role="player", expected=409)["detail"]
    )
    _bet(call, mid, ["1x2:b"], 91, expected=409)  # more than the balance
    _bet(call, mid, ["1x2:b"], 0.5, expected=422)  # below the minimum
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        db.get(Match, mid).starts_at = now() - timedelta(minutes=1)
    closed = call(
        "POST",
        f"/matches/{mid}/bets",
        dict(odds_id=o["odds_id"], selections=["1x2:b"], stake=1, odds=2.0),
        role="player",
        expected=409,
    )
    assert "закрыт" in closed["detail"]
    assert call("GET", f"/matches/{mid}/odds", role="player")["open"] is False


def test_settlement_and_correction_of_a_changed_result(env, call, club):
    mid, field = club["match"], club["field"]
    _freebet(call)
    _freebet(call, role="admin")
    win, _ = _bet(call, mid, ["1x2:a"], 20)
    lose, _ = _bet(call, mid, ["1x2:b"], 30, role="admin")
    _finish(env, call, mid, [field[0], field[1], field[2]], [field[8]])
    mine = {b["id"]: b for b in call("GET", "/bets", role="player")}
    assert mine[win["bet"]["id"]]["status"] == "won"
    payout = round(20 * win["bet"]["odds"], 2)
    assert call("GET", "/wallet", role="player")["balance"] == pytest.approx(80 + payout)
    assert call("GET", "/wallet", role="admin")["balance"] == 70
    board = call("GET", "/betting/leaderboard", role="player")
    assert board["bank"]["balance"] == pytest.approx(50 - payout)
    # the administrator corrects the score: the winner and loser swap
    _finish(env, call, mid, [field[0]], [field[8], field[9], field[10]])
    assert call("GET", "/wallet", role="player")["balance"] == 80
    admin_payout = round(30 * lose["bet"]["odds"], 2)
    assert call("GET", "/wallet", role="admin")["balance"] == pytest.approx(70 + admin_payout)
    entries = call("GET", "/wallet", role="player")["entries"]
    assert [e["kind"] for e in entries[:2]] == ["correction", "payout"]
    assert entries[0]["amount"] == pytest.approx(-payout)
    # running the settlement again posts nothing new
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        before = db.scalar(select(WalletEntry.id).order_by(WalletEntry.id.desc()))
        settle_bets(db, db.get(Match, mid))
        assert db.scalar(select(WalletEntry.id).order_by(WalletEntry.id.desc())) == before


def test_player_bets_are_refunded_when_a_goal_has_no_scorer(env, call, club):
    mid, field = club["match"], club["field"]
    _freebet(call)
    o = call("GET", f"/matches/{mid}/odds", role="player")
    player_lines = [
        s["id"] for g in o["groups"] if g["name"] == "Голы игроков" for s in g["selections"]
    ]
    white_ids = set(field[:8])
    white_line = next((s for s in player_lines if int(s.split(":")[1]) in white_ids), None)
    if white_line is None:  # nobody on white is expected to score more than once
        pytest.skip("no player line offered for white in this synthetic league")
    single, _ = _bet(call, mid, [white_line], 10)
    combo, _ = _bet(call, mid, ["1x2:a", white_line], 10)
    team_bet, _ = _bet(call, mid, ["1x2:a"], 10)
    _finish(env, call, mid, [field[0], None, field[1]], [])
    mine = {b["id"]: b for b in call("GET", "/bets", role="player")}
    assert mine[single["bet"]["id"]]["status"] == "void"
    assert mine[combo["bet"]["id"]]["status"] == "void"
    assert mine[team_bet["bet"]["id"]]["status"] == "won"  # score markets settle as usual
    assert "гол без автора" in mine[single["bet"]["id"]]["outcome"]["reason"]


def test_player_bet_void_when_the_player_did_not_play(env, call, club):
    mid, field = club["match"], club["field"]
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        bet = Bet(
            player_id=env[4]["player"],
            match_id=mid,
            odds_id=1,
            approved_version=1,
            selections=[f"player:{field[0]}:over:0.5"],
            labels=["x"],
            stake=1000,
            odds=200,
            status="open",
            credited=0,
        )
        call("GET", f"/matches/{mid}/odds", role="player")  # creates the snapshot with id 1
        db.add(bet)
    result = call("GET", f"/matches/{mid}/result")
    with factory() as db, db.begin():
        db.get(Match, mid).starts_at = now() - timedelta(hours=2)
    participants = [
        {k: p[k] for k in ("player_id", "team", "position")}
        for p in result["participants"]
        if p["player_id"] != field[0]
    ]
    call(
        "PUT",
        f"/matches/{mid}/result",
        dict(
            version=call("GET", f"/matches/{mid}/result")["version"],
            completed=True,
            participants=participants,
            goals=[],
        ),
    )
    with factory() as db:
        bet = db.scalar(select(Bet))
        assert bet.status == "void" and bet.credited == 1000


def test_line_up_change_and_cancellation_refund_open_bets(env, call, club):
    mid = club["match"]
    _freebet(call)
    placed, _ = _bet(call, mid, ["1x2:draw"], 25)
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        m = db.get(Match, mid)
        m.approved_version = 2  # a new approval after the bet
        settle_bets(db, m)
    bet = next(b for b in call("GET", "/bets", role="player") if b["id"] == placed["bet"]["id"])
    assert bet["status"] == "void" and "Составы изменились" in bet["outcome"]["reason"]
    assert call("GET", "/wallet", role="player")["balance"] == 100
    with factory() as db, db.begin():
        m = db.get(Match, mid)
        m.status = "cancelled"
        settle_bets(db, m)
        assert db.scalar(select(Bet)).status == "void"
    assert call("GET", "/wallet", role="player")["balance"] == 100  # refunded once, not twice


def test_worker_refits_after_a_new_result(env, club):
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        last = db.scalar(select(MatchResult).order_by(MatchResult.match_id.desc()))
        last.updated_at = now()
    bets.worker_tick(factory)
    with factory() as db:
        models = list(db.scalars(select(odds.PricingModel)))
        assert len(models) == 2 and models[-1].source_updated_at > models[0].source_updated_at


def test_simulation_is_reproducible_and_shares_sum_to_the_scorer_rate(env, call, club):
    call("GET", f"/matches/{club['match']}/odds", role="player")
    _, factory, _, _, _ = env
    with factory() as db:
        snapshot = db.scalar(select(MatchOdds))
        model = db.get(odds.PricingModel, snapshot.model_id).data
    a = odds._simulate(model, snapshot.inputs)
    b = odds._simulate(model, snapshot.inputs)
    np.testing.assert_array_equal(a.mats, b.mats)
    assert a.mats.sum(axis=(1, 2)) == pytest.approx(1.0)
    for team in ("white", "black"):
        np.testing.assert_allclose(a.shares[team][1].sum(1), model["scorer_rate"])
    assert odds_model.K_MAX + 1 == a.mats.shape[1]


def test_everybodys_bets_open_at_kick_off_and_stay_in_the_archive(env, call, club):
    mid, field = club["match"], club["field"]
    _freebet(call)
    _freebet(call, role="admin")
    mine, _ = _bet(call, mid, ["1x2:a"], 20)
    theirs, _ = _bet(call, mid, ["1x2:b"], 30, role="admin")
    hidden = call("GET", f"/matches/{mid}/bets", role="player", expected=409)
    assert "откроются" in hidden["detail"]
    assert call("GET", "/betting/archive", role="player") == []  # not started yet
    _finish(env, call, mid, [field[0], field[1]], [field[8]])
    rows = call("GET", f"/matches/{mid}/bets", role="player")
    assert [(r["alias"], r["labels"], r["stake"], r["status"]) for r in rows] == [
        ("Игрок", ["Победа белых"], 20, "won"),
        ("Администратор", ["Победа чёрных"], 30, "lost"),
    ]
    assert rows[0]["credited"] == pytest.approx(20 * mine["bet"]["odds"])
    archive = call("GET", "/betting/archive", role="player")
    assert len(archive) == 1
    entry = archive[0]
    assert entry["match_id"] == mid and entry["score"] == dict(white=2, black=1)
    assert (
        entry["bets"] == 2
        and entry["players"] == 2
        and entry["staked"] == 50
        and entry["open"] == 0
    )
    assert entry["bank"] == pytest.approx(50 - 20 * mine["bet"]["odds"])
    assert theirs["bet"]["status"] == "open"  # as placed; settled since


def test_model_details_are_for_administrators_only(call, club):
    mid = club["match"]
    assert "model" not in call("GET", f"/matches/{mid}/odds", role="player")
    assert call("GET", f"/matches/{mid}/odds", role="admin")["model"]["n_matches"] == 30


def test_implied_selections_add_no_margin(env, call, club):
    o = call("GET", f"/matches/{club['match']}/odds", role="player")
    _, factory, _, _, _ = env
    with factory() as db:
        snapshot = db.scalar(select(MatchOdds))
        sim = odds.simulation(db, snapshot)
    ids, _ = sim.shares["white"]

    def priced(*selections):
        return odds.price(sim, [odds.parse(s) for s in selections])

    # Over 11.5 already contains over 10.5: the combination is the narrower single.
    nested = priced("total:over:10.5", "total:over:11.5")
    assert nested["odds"] == priced("total:over:11.5")["odds"] and nested["implied"] == [0]
    # The same player over 0.5 and over 1.5; a team scoring next to its player scoring.
    two = priced(f"player:{ids[0]}:over:1.5", f"player:{ids[0]}:over:0.5")
    assert two["odds"] == priced(f"player:{ids[0]}:over:1.5")["odds"] and two["implied"] == [1]
    team = priced("team:a:over:0.5", f"player:{ids[0]}:over:0.5")
    assert team["odds"] == priced(f"player:{ids[0]}:over:0.5")["odds"] and team["implied"] == [0]
    # A band of totals narrows the outcome: both selections matter and the price grows.
    band = priced("total:over:8.5", "total:under:12.5")
    assert band["implied"] == [] and band["odds"] > priced("total:over:8.5")["odds"]

    total = next(
        s["id"] for g in o["groups"] for s in g["selections"] if s["id"].startswith("total:over:")
    )
    line = float(total.rsplit(":", 1)[1])
    wider = f"total:over:{line - 1}"
    if wider in {s["id"] for g in o["groups"] for s in g["selections"]}:
        q = call(
            "POST",
            f"/matches/{club['match']}/odds/quote",
            dict(odds_id=o["odds_id"], selections=[wider, total]),
            role="player",
        )
        assert len(q["implied"]) == 1 and q["odds"] == priced(total)["odds"]


def test_exact_scores_are_central_without_gaps_and_flat_margin(env, call, club):
    o = call("GET", f"/matches/{club['match']}/odds", role="player")
    group = next(g for g in o["groups"] if g["name"] == "Точный счёт")
    scores = {tuple(map(int, s["id"].split(":")[1:])) for s in group["selections"]}
    assert odds.SCORES[0] <= len(scores) <= odds.SCORES[1]
    for a, b in scores:  # no gaps within a row or a column
        assert all((a, c) in scores for c in range(b, max(y for x, y in scores if x == a) + 1))
        assert all((c, b) in scores for c in range(a, max(x for x, y in scores if y == b) + 1))
    _, factory, _, _, _ = env
    with factory() as db:
        sim = odds.simulation(db, db.scalar(select(MatchOdds)))
    mat = sim.mats.mean(axis=0)
    top = np.unravel_index(int(np.argmax(mat)), mat.shape)
    assert tuple(int(v) for v in top) in scores
    for s in group["selections"]:
        p = odds.probability(sim, [odds.parse(s["id"])])
        assert s["odds"] == odds.rounded(1 / (p * (1 + odds.SCORE_MARGIN)))
        assert s["label"].startswith("Счёт ")
    # A score decides the match result: the result next to it is implied, the other is impossible.
    a, b = max(scores, key=lambda s: s[0] - s[1])
    winner = "1x2:a" if a > b else "1x2:draw" if a == b else "1x2:b"
    loser = "1x2:b" if a >= b else "1x2:a"
    combo = odds.price(sim, [odds.parse(f"score:{a}:{b}"), odds.parse(winner)])
    assert combo["implied"] == [1]
    assert odds.price(sim, [odds.parse(f"score:{a}:{b}"), odds.parse(loser)])["odds"] is None
    # Settlement: the score bet wins only on that exact score.
    assert bets._leg_result(odds.parse("score:5:4"), dict(white=5, black=4)) == "won"
    assert bets._leg_result(odds.parse("score:5:4"), dict(white=4, black=5)) == "lost"


def test_long_odds_are_rounded_down_on_a_coarser_step():
    assert odds.rounded(1.876) == 1.87
    assert odds.rounded(9.999) == 9.99
    assert odds.rounded(10.0) == 10.0
    assert odds.rounded(12.38) == 12.3
    assert odds.rounded(19.99) == 19.9
    assert odds.rounded(20.0) == 20.0
    assert odds.rounded(44.71) == 44.0


def test_every_outfield_player_gets_goal_and_assist_lines(call, club):
    o = call("GET", f"/matches/{club['match']}/odds", role="player")
    groups = {g["name"]: [s["id"] for s in g["selections"]] for g in o["groups"]}
    on_pitch = set(club["field"][:16])
    for name, kind in (("Голы игроков", "player"), ("Передачи игроков", "assist")):
        priced = {int(i.split(":")[1]) for i in groups[name]}
        assert priced == on_pitch, name  # every outfield player, no goalkeeper
        assert all(i.startswith(kind + ":") for i in groups[name])
    assert len({i.rsplit(":", 1)[1] for i in groups["Тотал матча"]}) == len(odds.TOTAL_STEPS)
    labels = {s["id"]: s["label"] for g in o["groups"] for s in g["selections"]}
    first = groups["Передачи игроков"][0]
    assert ": передач " in labels[first]


def test_assist_probability_matches_brute_force_simulation(env, call, club):
    call("GET", f"/matches/{club['match']}/odds", role="player")
    _, factory, _, _, _ = env
    with factory() as db:
        sim = odds.simulation(db, db.scalar(select(MatchOdds)))
    rng = np.random.default_rng(1)
    n, size = 20000, sim.mats.shape[1]
    draw = rng.integers(0, len(sim.mats), n)
    flat = sim.mats.reshape(len(sim.mats), -1)
    cells = np.array([rng.choice(size * size, p=flat[d] / flat[d].sum()) for d in draw])
    x, y = np.divmod(cells, size)
    ids, goal_shares = sim.shares["white"]
    _, assist_shares = sim.assists["white"]
    scored = rng.binomial(x, goal_shares[draw, 0])
    assisted = rng.binomial(x, assist_shares[draw, 1])
    legs = [
        odds.parse("1x2:a"),
        odds.parse(f"player:{ids[0]}:over:0.5"),
        odds.parse(f"assist:{ids[1]}:over:0.5"),
    ]
    hit = (x > y) & (scored >= 1) & (assisted >= 1)
    assert odds.probability(sim, legs) == pytest.approx(
        hit.mean(), abs=4 * np.sqrt(hit.mean() / len(hit))
    )


def test_assist_bets_settle_on_the_protocol(env, call, club):
    mid, field = club["match"], club["field"]
    _freebet(call)
    won, _ = _bet(call, mid, [f"assist:{field[1]}:over:0.5"], 10)
    lost, _ = _bet(call, mid, [f"assist:{field[2]}:over:0.5"], 10)
    # A goal without a named scorer does not void assist bets: it is a goal without an assist.
    kept, _ = _bet(call, mid, [f"assist:{field[3]}:under:0.5"], 10)
    _finish(env, call, mid, [(field[0], field[1]), None], [field[8]])
    mine = {b["id"]: b for b in call("GET", "/bets", role="player")}
    assert mine[won["bet"]["id"]]["status"] == "won"
    assert mine[lost["bet"]["id"]]["status"] == "lost"
    assert mine[kept["bet"]["id"]]["status"] == "won"


@pytest.mark.parametrize("linked_after_pricing", [False, True])
def test_nobody_bets_on_under_for_his_own_goals_or_assists(env, call, club, linked_after_pricing):
    mid, me = club["match"], club["field"][0]
    _, factory, _, _, ids = env
    o = call("GET", f"/matches/{mid}/odds", role="player")
    catalogue = {s["id"]: s["odds"] for g in o["groups"] for s in g["selections"]}
    with factory() as db, db.begin():
        actor = ids["player"] if linked_after_pricing else me
        if linked_after_pricing:
            db.get(Player, me).merged_into = actor
            db.flush()
        match = db.get(Match, mid)
        for kind in ("player", "assist"):
            under = next(i for i in catalogue if i.startswith(f"{kind}:{me}:under:"))
            body = SimpleNamespace(odds_id=o["odds_id"], selections=[under], stake=1, odds=0)
            with pytest.raises(DomainError, match="своим голам и передачам") as exc:
                bets.place(db, actor, match, body)
            assert exc.value.status == 422


def test_a_model_without_assists_is_refitted(env, club):
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        old = db.get(odds.PricingModel, club["model"])
        assert "assist_shares" in old.data
        old.data = {k: v for k, v in old.data.items() if not k.startswith("assist")} | {
            "version": 1
        }
    with factory() as db, db.begin():
        new = odds.refit_if_needed(db)
        assert new.id != club["model"] and new.data["version"] == odds_model.MODEL_VERSION
        assert "assist_shares" in new.data


def test_players_with_few_matches_carry_more_margin_on_both_sides(env, call, club):
    call("GET", f"/matches/{club['match']}/odds", role="player")
    _, factory, _, _, _ = env
    with factory() as db:
        sim = odds.simulation(db, db.scalar(select(MatchOdds)))
    me = club["field"][0]
    assert sim.games[me] >= odds.NEW_PLAYER_MATCHES  # a regular of the synthetic league
    assert odds.newcomer(0) == 1 + odds.NEW_PLAYER_EXTRA and odds.newcomer(99) == 1.0
    regular = {
        side: odds.price(sim, [odds.parse(f"assist:{me}:{side}:0.5")]) for side in ("over", "under")
    }
    sim.games = {**sim.games, me: 2}
    for side, before in regular.items():
        after = odds.price(sim, [odds.parse(f"assist:{me}:{side}:0.5")])
        assert after["p"] == before["p"] and after["odds"] < before["odds"], side


def _grant(env, role, amount):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        db.add(
            WalletEntry(
                player_id=ids[role],
                kind="grant",
                amount=amount * 100,
                actor_id=ids["admin" if role == "player" else "player"],
                note="тест",
                created_at=now(),
            )
        )


def _line(call, mid):
    o = call("GET", f"/matches/{mid}/odds", role="player")
    return o, {s["id"]: s for g in o["groups"] for s in g["selections"]}


def test_the_line_follows_the_bets(env, call, club):
    mid = club["match"]
    _, before = _line(call, mid)
    assert not any("base" in s for s in before.values())  # no bets: the model's line
    _grant(env, "player", 1000)
    first, _ = _bet(call, mid, ["1x2:b"], 100)
    for _ in range(5):
        _bet(call, mid, ["1x2:b"], 100)
    o, after = _line(call, mid)
    # The loaded outcome gets cheaper, the others dearer; the model's price is shown beside.
    assert after["1x2:b"]["odds"] < before["1x2:b"]["odds"] == after["1x2:b"]["base"]
    assert after["1x2:a"]["odds"] > before["1x2:a"]["odds"]
    assert after["1x2:draw"]["odds"] > before["1x2:draw"]["odds"]
    # Correlated markets move with it: Black's handicaps get cheaper too.
    black = [s for s in after if s.startswith("handicap:b:")]
    assert any(after[s]["odds"] < before[s]["odds"] for s in black)
    assert all(after[s]["odds"] <= before[s]["odds"] for s in black)
    # A quote matches the shown line; a bet keeps the odds it was placed at.
    q = call(
        "POST",
        f"/matches/{mid}/odds/quote",
        dict(odds_id=o["odds_id"], selections=["1x2:b"]),
        role="player",
    )
    assert q["odds"] == after["1x2:b"]["odds"]
    mine = {b["id"]: b for b in o["bets"]}
    assert mine[first["bet"]["id"]]["odds"] == before["1x2:b"]["odds"]


def test_a_player_bet_moves_that_players_line(env, call, club):
    mid = club["match"]
    _, before = _line(call, mid)
    sid = next(s for s in before if s.startswith("player:") and s.endswith(":over:0.5"))
    _grant(env, "player", 1000)
    _bet(call, mid, [sid], 500)
    _, after = _line(call, mid)
    assert after[sid]["odds"] < before[sid]["odds"]
    under = sid.replace(":over:", ":under:")
    assert after[under]["odds"] >= before[under]["odds"]


def test_the_move_is_capped_and_the_capped_line_keeps_its_margin(env, call, club):
    mid = club["match"]
    _, before = _line(call, mid)
    _grant(env, "player", 5000)
    _bet(call, mid, ["1x2:draw"], 4000)  # a huge bet on the long shot hits the cap
    _, after = _line(call, mid)
    _, factory, _, _, _ = env
    with factory() as db:
        snapshot = db.scalar(select(MatchOdds).where(MatchOdds.match_id == mid))
        fair = {s["id"]: s["p"] for s in snapshot.markets}
        tilt = odds.live(db, snapshot)
        moved = {sid: p * tilt([odds.parse(sid)]) for sid, p in fair.items()}
        factor = {sid: moved[sid] / fair[sid] for sid in fair}
    low, high = 1 / (1 + odds.DYNAMIC_CAP), 1 + odds.DYNAMIC_CAP
    assert factor["1x2:draw"] == pytest.approx(high)
    assert all(low - 1e-9 <= v <= high + 1e-9 for v in factor.values())
    # The cap is on the weights: exclusive outcomes still add up to one, the book keeps its margin.
    outcome = ("1x2:a", "1x2:draw", "1x2:b")
    assert sum(moved[s] for s in outcome) == pytest.approx(1, abs=0.01)
    assert sum(1 / after[s]["odds"] for s in outcome) == pytest.approx(
        sum(1 / before[s]["odds"] for s in outcome), abs=0.02
    )
    for over in (s for s in fair if ":over:" in s):
        under = over.replace(":over:", ":under:")
        assert moved[over] + moved[under] == pytest.approx(1, abs=0.02), over
        assert 1 / after[over]["odds"] + 1 / after[under]["odds"] > 1.03, over


def test_every_market_and_combination_moves_the_right_way(env, call, club):
    mid = club["match"]
    o, before = _line(call, mid)
    total = sorted(float(s.rsplit(":", 1)[1]) for s in before if s.startswith("total:over:"))
    over, under = (f"total:{side}:{total[len(total) // 2]:g}" for side in ("over", "under"))
    scorer = next(s for s in before if s.startswith("player:") and s.endswith(":over:0.5"))
    white = int(scorer.split(":")[1]) in club["field"][:8]

    def quoted(*selections):
        body = dict(odds_id=o["odds_id"], selections=list(selections))
        return call("POST", f"/matches/{mid}/odds/quote", body, role="player")["odds"]

    combos = {
        name: quoted(*legs)
        for name, legs in dict(
            with_it=("1x2:b", over), against=("1x2:a", under), half=("1x2:b", under)
        ).items()
    }
    _grant(env, "player", 1000)
    _bet(call, mid, ["1x2:b", over], 300)  # one combination: Black to win a high-scoring match
    _, after = _line(call, mid)

    def moved(sid):
        return after[sid]["odds"] - before[sid]["odds"]

    # Both selections of the combination get cheaper as singles, their opposites dearer.
    assert moved("1x2:b") < 0 < moved("1x2:a") and moved("1x2:draw") > 0
    assert moved(over) < 0 < moved(under)
    # Correlated score markets follow: Black's handicaps and totals down, White's handicaps up.
    for sid in before:
        kind, team, *rest = sid.split(":")
        if kind == "handicap":
            assert moved(sid) <= 0 if team == "b" else moved(sid) >= 0, sid
        if kind == "team" and team == "b":
            assert moved(sid) <= 0 if rest[0] == "over" else moved(sid) >= 0, sid
    # A scorer follows his team.
    assert moved(scorer) >= 0 if white else moved(scorer) <= 0
    # Ladders stay ordered: a higher line pays more on over, less on under.
    for prefix, sign in (("total:over:", 1), ("total:under:", -1)):
        ladder = [
            after[s]["odds"]
            for s in sorted(
                (s for s in after if s.startswith(prefix)), key=lambda s: float(s.rsplit(":", 1)[1])
            )
        ]
        assert all((b - a) * sign >= 0 for a, b in zip(ladder, ladder[1:], strict=False)), prefix
    # The same combination gets cheaper, the opposite one dearer, and it moves more than a
    # combination sharing only one selection with the bet.
    assert quoted("1x2:b", over) < combos["with_it"]
    assert quoted("1x2:a", under) > combos["against"]
    assert quoted("1x2:b", over) / combos["with_it"] < quoted("1x2:b", under) / combos["half"]


def test_pool_counts_balances_and_unclaimed_freebets(env, call, club):
    from fczhk import wallet

    _, factory, _, _, _ = env
    with factory() as db:
        assert wallet.pool(db) == 0  # nobody holds points yet
    _freebet(call)
    _grant(env, "admin", 50)
    with factory() as db:
        # The player's freebet is claimed; the admin holds 50 and may still claim 100.
        assert wallet.pool(db) == 100 + 50 + 100
        assert wallet.pool(db, now() + timedelta(days=7)) == 100 + 50 + 2 * 100


def test_a_price_that_went_up_is_taken_one_that_went_down_is_refused(env, call, club):
    mid = club["match"]
    _grant(env, "player", 1000)
    _bet(call, mid, ["1x2:b"], 500)
    o, line = _line(call, mid)
    up, down = line["1x2:a"], line["1x2:b"]
    assert up["odds"] > up["base"] and down["odds"] < down["base"]
    placed = call(
        "POST",
        f"/matches/{mid}/bets",
        dict(odds_id=o["odds_id"], selections=["1x2:a"], stake=10, odds=up["base"]),
        role="player",
        expected=201,
    )
    assert placed["bet"]["odds"] == up["odds"]  # the better price now
    refused = call(
        "POST",
        f"/matches/{mid}/bets",
        dict(odds_id=o["odds_id"], selections=["1x2:b"], stake=10, odds=down["base"]),
        role="player",
        expected=409,
    )
    assert "Коэффициент изменился" in refused["detail"]
