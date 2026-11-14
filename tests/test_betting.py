from datetime import timedelta
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
from fczhk.services import settle_bets


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
                db.add(
                    ResultGoal(
                        match_id=m.id, id=str(uuid4()), team=team, kind="goal", author_id=scorer
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
    """Move kick-off into the past and save a completed result with the given scorers."""
    _, factory, _, _, _ = env
    with factory() as db, db.begin():
        db.get(Match, mid).starts_at = now() - timedelta(hours=2)
    result = call("GET", f"/matches/{mid}/result")
    goals = [
        dict(id=str(uuid4()), team="white", kind="goal", author_id=a, assist_id=None)
        for a in white_goals
    ]
    goals += [
        dict(id=str(uuid4()), team="black", kind="goal", author_id=a, assist_id=None)
        for a in black_goals
    ]
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
