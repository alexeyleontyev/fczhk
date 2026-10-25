from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from fczhk.db import now
from fczhk.models import (
    Match,
    Player,
    Prediction,
    Publication,
    Registration,
    TeamRatingSnapshot,
    TeamSnapshot,
)
from fczhk.predictions import points


@pytest.fixture
def predicted_game(env):
    with env[1]() as db, db.begin():
        starts = now() + timedelta(days=2)
        m = Match(
            game_day=starts.date().isoformat(),
            starts_at=starts,
            location="Прогнозы",
            status="approved",
            approved_version=3,
            version=3,
        )
        guest = Player(alias="Футболист гость")
        db.add_all([m, guest])
        db.flush()
        db.add_all(
            [
                Registration(
                    match_id=m.id,
                    player_id=env[4]["admin"],
                    selected=True,
                    position="field",
                    team="white",
                ),
                Registration(
                    match_id=m.id,
                    player_id=guest.id,
                    selected=True,
                    position="field",
                    team="black",
                ),
            ]
        )
        return m.id, starts


def forecast(call, mid, white, black, role="player", expected=200, **override):
    view = call("GET", f"/matches/{mid}/predictions", role=role)
    body = dict(
        white_score=white,
        black_score=black,
        revision=view["mine"]["revision"] if view["mine"] else 0,
        approved_version=view["approved_version"],
    )
    body.update(override)
    return call("PUT", f"/matches/{mid}/prediction", body, role=role, expected=expected)


def result(call, mid, white, black, completed=True):
    data = call("GET", f"/matches/{mid}/result")
    return call(
        "PUT",
        f"/matches/{mid}/result",
        dict(
            version=data["version"],
            completed=completed,
            participants=[
                {k: p[k] for k in ("player_id", "team", "position")} for p in data["participants"]
            ],
            goals=[
                dict(id=str(uuid4()), team=team) for team in ["white"] * white + ["black"] * black
            ],
        ),
    )


@pytest.mark.parametrize(
    "predicted,actual,value",
    [
        ((3, 1), (2, 0), 2),
        ((1, 3), (0, 2), 2),
        ((4, 1), (2, 0), 2),
        ((1, 4), (0, 2), 2),
        ((3, 1), (0, 2), 0),
        ((1, 3), (2, 0), 0),
        ((0, 0), (2, 2), 3),
        ((4, 4), (0, 0), 3),
        ((1, 1), (1, 1), 3),
        ((1, 1), (3, 1), 0.5),
        ((2, 1), (0, 0), 0.5),
        ((2, 0), (2, 0), 2),
    ],
)
def test_scoring_rules(predicted, actual, value):
    assert points(*predicted, *actual) == value


def test_every_registered_player_can_predict_and_revise_before_kickoff(env, call, predicted_game):
    mid, starts = predicted_game
    m = call("GET", f"/matches/{mid}")
    assert env[4]["player"] not in [r["player_id"] for r in m["registrations"]]
    first = forecast(call, mid, 3, 1)
    assert first["mine"]["white_score"] == 3 and first["mine"]["revision"] == 1
    second = forecast(call, mid, 4, 2)
    assert second["mine"]["revision"] == 2 and second["count"] == 1
    forecast(call, mid, 6, 1, revision=1, expected=409)
    with env[1]() as db:
        assert len(list(db.scalars(select(Prediction)))) == 1
    assert call("GET", f"/matches/{mid}/predictions")["mine"] is None
    assert call("GET", f"/matches/{mid}/predictions")["forecasts"] == []
    history = call("GET", f"/matches/{mid}/history")["audit"]
    assert all("white_score" not in a["data"] for a in history)
    standings = call("GET", "/predictions/standings")
    assert standings[0]["points"] == 0 and standings[0]["settled"] == 0
    call("GET", "/predictions/standings", role=None, expected=401)
    call(
        "PUT",
        f"/matches/{mid}/prediction",
        dict(
            white_score=1, black_score=0, revision=2, approved_version=3, player_id=env[4]["admin"]
        ),
        role="player",
        expected=422,
    )


def test_exact_deadline_blocks_both_new_and_updated_predictions(
    env, call, predicted_game, monkeypatch
):
    mid, starts = predicted_game
    monkeypatch.setattr("fczhk.predictions.now", lambda: starts - timedelta(microseconds=1))
    forecast(call, mid, 1, 0)
    monkeypatch.setattr("fczhk.predictions.now", lambda: starts)
    forecast(call, mid, 2, 0, expected=409)
    forecast(call, mid, 0, 0, role="admin", expected=409)
    view = call("GET", f"/matches/{mid}/predictions")
    assert view["closed"] and not view["available"]
    assert view["forecasts"][0]["white_score"] == 1
    monkeypatch.setattr("fczhk.predictions.now", lambda: starts + timedelta(microseconds=1))
    forecast(call, mid, 5, 0, expected=409)


def test_approval_gate_roster_changes_and_existing_forecasts(env, call, predicted_game):
    mid, _ = predicted_game
    forecast(call, mid, 2, 0)
    m = call("GET", f"/matches/{mid}")
    assignments = {
        str(r["id"]): ("black" if r["team"] == "white" else "white") for r in m["registrations"]
    }
    m = call("PUT", f"/matches/{mid}/teams", {"version": m["version"], "assignments": assignments})
    view = call("GET", f"/matches/{mid}/predictions", role="player")
    assert not view["available"] and view["mine"]["teams_changed"]
    forecast(call, mid, 1, 1, approved_version=3, expected=409)
    m = call("POST", f"/matches/{mid}/actions/approve", {"version": m["version"]})
    forecast(call, mid, 1, 1, approved_version=3, expected=409)
    view = forecast(call, mid, 1, 1)
    assert not view["mine"]["teams_changed"]
    assert view["mine"]["approved_version"] != 3


def test_admin_swaps_only_team_colors_before_game(env, call, predicted_game, monkeypatch):
    mid, starts = predicted_game
    path = f"/matches/{mid}"
    with env[1]() as db, db.begin():
        snapshot = TeamSnapshot(
            match_id=mid,
            version=3,
            teams=[
                dict(
                    player_id=r.player_id,
                    position=r.position,
                    team=r.team,
                    alias=db.get(Player, r.player_id).alias,
                )
                for r in db.scalars(select(Registration).where(Registration.match_id == mid))
            ],
        )
        db.add(snapshot)
        db.flush()
        db.add(
            TeamRatingSnapshot(
                snapshot_id=snapshot.id,
                data=dict(
                    method="manual",
                    game_summary=dict(white_mu=22, black_mu=28, white_total=1400, black_total=1600),
                    summary=dict(
                        white=dict(count=1, attack=4),
                        black=dict(count=1, attack=2),
                        attack_gap=2,
                        cost=2,
                    ),
                ),
            )
        )
    forecast(call, mid, 2, 0)
    before = call("GET", path)
    call(
        "POST",
        path + "/teams/swap-colors",
        {"version": before["version"]},
        role="player",
        expected=403,
    )
    call("POST", path + "/actions/publish", {"version": before["version"]})
    changed = call("POST", path + "/teams/swap-colors", {"version": before["version"]})
    assert changed["status"] == "approved"
    assert changed["version"] == before["version"] + 1
    assert changed["roster_version"] == before["roster_version"]
    assert changed["team_ratings"]["frozen"]
    assert changed["team_ratings"]["summary"]["white"]["attack"] == 2
    assert changed["team_ratings"]["summary"]["black"]["attack"] == 4
    assert changed["team_ratings"]["game_summary"] == dict(
        white_mu=28, black_mu=22, white_total=1600, black_total=1400
    )
    assert all(
        after["team"] == ("black" if old["team"] == "white" else "white")
        for old, after in zip(before["registrations"], changed["registrations"])
    )
    assert any(p["kind"] == "teams" and p["stale"] for p in changed["publications"])
    call("POST", path + "/actions/publish", {"version": changed["version"]})
    with env[1]() as db:
        posts = list(
            db.scalars(
                select(Publication).where(Publication.match_id == mid).order_by(Publication.version)
            )
        )
        assert posts[0].stale and posts[0].status == "cancelled"
        assert not posts[1].stale and posts[1].version == changed["version"]
        assert f"⚪ Белые\n{changed['registrations'][1]['alias']}" in posts[1].text
        assert f"⚫ Черные\n{changed['registrations'][0]['alias']}" in posts[1].text
    history = call("GET", path + "/history")
    assert history["teams"][0]["teams"] == [
        {**r, "team": "black" if r["team"] == "white" else "white"}
        for r in history["teams"][1]["teams"]
    ]
    assert call("GET", path + "/predictions", role="player")["mine"]["teams_changed"]
    call("POST", path + "/teams/swap-colors", {"version": before["version"]}, expected=409)
    monkeypatch.setattr("fczhk.services.now", lambda: starts)
    call("POST", path + "/teams/swap-colors", {"version": changed["version"]}, expected=409)
    assert call("GET", path)["registrations"] == changed["registrations"]


def test_color_swap_in_unapproved_draft_requires_two_teams(env, call, predicted_game):
    mid, _ = predicted_game
    path = f"/matches/{mid}"
    with env[1]() as db, db.begin():
        match = db.get(Match, mid)
        match.status = "finalized"
        match.approved_version = None
        regs = list(db.scalars(select(Registration).where(Registration.match_id == mid)))
        regs[1].team = None
    call("POST", path + "/teams/swap-colors", {"version": 3}, expected=400)
    before = call("GET", path)
    assert before["registrations"][1]["team"] is None
    with env[1]() as db, db.begin():
        regs = list(db.scalars(select(Registration).where(Registration.match_id == mid)))
        regs[1].team = "black"
    changed = call("POST", path + "/teams/swap-colors", {"version": 3})
    assert changed["status"] == "finalized"
    assert changed["registrations"][0]["team"] == "black"
    assert changed["registrations"][1]["team"] == "white"


def test_reschedule_cannot_reopen_after_start_or_retroactively_close(
    env, call, predicted_game, monkeypatch
):
    mid, starts = predicted_game
    forecast(call, mid, 2, 0)
    m = call("GET", f"/matches/{mid}")

    def edit(start, expected=400):
        return call(
            "PUT",
            f"/matches/{mid}",
            dict(version=m["version"], starts_at=start.isoformat(), location=m["location"]),
            expected=expected,
        )

    edit(now() - timedelta(seconds=1))
    monkeypatch.setattr("fczhk.predictions.now", lambda: starts)
    edit(starts + timedelta(hours=1))
    assert call("GET", f"/matches/{mid}")["starts_at"] == m["starts_at"]
    monkeypatch.setattr("fczhk.predictions.now", lambda: starts - timedelta(hours=1))
    edit(starts + timedelta(hours=1), expected=200)
    assert call("GET", f"/matches/{mid}/predictions")["deadline"] != m["starts_at"]


def test_standings_only_finalized_results_recalculate_without_accumulation(
    env, call, predicted_game, monkeypatch
):
    mid, starts = predicted_game
    forecast(call, mid, 4, 2)
    forecast(call, mid, 0, 0, role="admin")
    monkeypatch.setattr("fczhk.predictions.now", lambda: starts)
    monkeypatch.setattr("fczhk.results.now", lambda: starts)
    result(call, mid, 2, 0, completed=False)
    assert all(row["settled"] == 0 for row in call("GET", "/predictions/standings"))
    result(call, mid, 2, 0)
    scores = call("GET", "/predictions/standings")
    assert scores[0]["player_id"] == env[4]["player"] and scores[0]["points"] == 2
    assert scores[0]["two_points"] == 1 and scores[0]["settled"] == 1
    assert call("GET", f"/matches/{mid}/predictions", role="player")["mine"]["points"] == 2
    result(call, mid, 2, 2)
    scores = call("GET", "/predictions/standings")
    assert scores[0]["player_id"] == env[4]["admin"] and scores[0]["points"] == 3
    assert scores[1]["points"] == 0.5 and scores[0]["three_points"] == 1
    result(call, mid, 2, 2)
    assert call("GET", "/predictions/standings") == scores
    assert call("GET", f"/players/{env[4]['player']}/stats")["games"] == 0


def test_all_games_and_shared_ranks(env, call, predicted_game, monkeypatch):
    mid, starts = predicted_game
    forecast(call, mid, 2, 0)
    forecast(call, mid, 2, 0, role="admin")
    with env[1]() as db, db.begin():
        m = Match(
            game_day=(starts + timedelta(days=1)).date().isoformat(),
            starts_at=starts + timedelta(days=1),
            location="Ещё игра",
            status="approved",
            approved_version=1,
        )
        db.add(m)
        db.flush()
        for role, team in [("admin", "white"), ("player", "black")]:
            db.add(
                Registration(
                    match_id=m.id,
                    player_id=env[4][role],
                    position="field",
                    selected=True,
                    team=team,
                )
            )
        other_id = m.id
    forecast(call, other_id, 1, 1)
    forecast(call, other_id, 0, 0, role="admin")
    monkeypatch.setattr("fczhk.results.now", lambda: starts + timedelta(days=2))
    result(call, mid, 2, 0)
    result(call, other_id, 0, 0)
    table = call("GET", "/predictions/standings")
    assert [(row["rank"], row["points"], row["settled"], row["predictions"]) for row in table] == [
        (1, 5, 2, 2),
        (1, 5, 2, 2),
    ]


@pytest.mark.parametrize("value", [-1, 201, 1.5, True, "2"])
def test_score_validation(call, predicted_game, value):
    forecast(call, predicted_game[0], value, 0, expected=422)


def test_category_input_and_baseline_only_add_new_predictions(
    env, call, predicted_game, monkeypatch
):
    from fczhk.models import PredictionBaseline

    mid, starts = predicted_game
    with env[1]() as db, db.begin():
        db.add(
            PredictionBaseline(
                player_id=env[4]["player"], season="2026", points_half=9, source="sheet"
            )
        )
        db.add(
            Prediction(
                match_id=mid,
                player_id=env[4]["player"],
                white_score=9,
                black_score=0,
                scoring_version=1,
                approved_version=3,
            )
        )
    baseline = call("GET", "/predictions/standings?season=2026")
    assert baseline[0]["points"] == 4.5 and baseline[0]["predictions"] == 0
    call(
        "PUT",
        f"/matches/{mid}/prediction",
        {"category": "Б13", "revision": 1, "approved_version": 3},
        role="player",
    )
    assert call("GET", f"/matches/{mid}/predictions", role="player")["mine"]["category"] == "Б13"
    call(
        "PUT",
        f"/matches/{mid}/prediction",
        {
            "category": "Б4",
            "white_score": 1,
            "black_score": 0,
            "revision": 2,
            "approved_version": 3,
        },
        role="player",
        expected=422,
    )
    monkeypatch.setattr("fczhk.results.now", lambda: starts)
    result(call, mid, 4, 0)
    row = call("GET", "/predictions/standings?season=2026")[0]
    assert (row["baseline_points"], row["points"], row["half_points"], row["settled"]) == (
        4.5,
        5,
        1,
        1,
    )
    result(call, mid, 2, 0)
    row = call("GET", "/predictions/standings?season=2026")[0]
    assert (row["points"], row["two_points"]) == (6.5, 1)
    assert call("GET", "/predictions/standings?season=absent") == []
