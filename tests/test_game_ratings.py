from datetime import datetime
from uuid import uuid4

from openskill.models import ThurstoneMostellerFull

from fczhk.game_balancing import generate
from fczhk.game_ratings import history, replay
from fczhk.models import Match, MatchResult, Player, Registration, ResultGoal, ResultParticipant
from fczhk.schemas import BalanceSettings


def test_score_margin_only_changes_updates_when_enabled():
    def update(margin: float, white_score: int) -> float:
        model = ThurstoneMostellerFull(margin=margin)
        white = model.rating(mu=30, sigma=5)
        black = model.rating(mu=25, sigma=5)
        return model.rate([[white], [black]], scores=[white_score, 0])[0][0].mu

    assert update(0, 2) == update(0, 10)
    assert update(1, 2) != update(1, 10)


def test_game_balance_counts_extra_player_in_odd_roster():
    rows = [
        {
            "registration_id": index,
            "game_mu": 25.0,
            "attack_fraction": None,
            "defense_fraction": None,
        }
        for index in range(3)
    ]
    result = generate(rows, BalanceSettings(method="game"))
    assert result["minimum_cost"] > 0


def test_replay_uses_only_past_completed_games_and_field_players(env, call):
    _, factory, _, _, _ = env
    assert call("GET", "/game-ratings")["players"] == []
    with factory() as db, db.begin():
        field = [Player(alias=f"Полевой {i}") for i in range(4)]
        keeper = Player(alias="Вратарь")
        db.add_all([*field, keeper])
        db.flush()
        for day, scorer, side in (("2026-06-05", field[0], "white"), ("2026-06-12", field[2], "black")):
            match = Match(
                game_day=day,
                starts_at=datetime.fromisoformat(day + "T20:00:00+03:00"),
                location="Тест",
                status="completed",
                field_limit=4,
                keeper_limit=1,
            )
            db.add(match)
            db.flush()
            db.add(MatchResult(match_id=match.id, completed=True))
            for index, player in enumerate(field):
                db.add(
                    ResultParticipant(
                        match_id=match.id,
                        player_id=player.id,
                        team="white" if index < 2 else "black",
                        position="field",
                    )
                )
            db.add(
                ResultParticipant(
                    match_id=match.id, player_id=keeper.id, team="white", position="keeper"
                )
            )
            db.add(
                ResultGoal(
                    match_id=match.id,
                    id=str(uuid4()),
                    team=side,
                    kind="goal",
                    author_id=scorer.id,
                )
            )
    with factory() as db:
        games = history(db)
        assert len(games) == 2
        prior = replay(db, before_day="2026-06-12")
        assert len(prior["predictions"]) == 1
        assert all(row["games"] == 1 for row in prior["players"].values())
        assert keeper.id not in prior["players"]
        assert prior["players"][field[0].id]["mu"] > prior["players"][field[2].id]["mu"]
        complete = replay(db)
        assert len(complete["predictions"]) == 2
        assert complete["predictions"][1]["p_white"] > 0.5
        with_keepers = replay(db, include_keepers=True)
        assert with_keepers["players"][(keeper.id, "keeper")]["games"] == 2
        assert (field[0].id, "field") in with_keepers["players"]
    board = call("GET", "/game-ratings")
    assert board["matches"] == 2
    assert len(board["players"]) == 4
    assert all(row["games"] == 2 for row in board["players"])


def test_game_balance_is_optional_and_historical_changes_stale_it(env, call):
    _, factory, _, _, _ = env
    match = call(
        "POST",
        "/matches",
        {"starts_at": "2026-10-02T20:00:00+03:00", "location": "Тест"},
        expected=201,
    )
    with factory() as db, db.begin():
        people = [Player(alias=f"Полевой {i}") for i in range(4)]
        db.add_all(people)
        db.flush()
        for person in people:
            db.add(
                Registration(
                    match_id=match["id"], player_id=person.id, position="field", selected=True
                )
            )
        db.get(Match, match["id"]).status = "finalized"
        player_ids = [person.id for person in people]
    path = f"/matches/{match['id']}"
    run = call(
        "POST",
        path + "/balance",
        {"version": match["version"], "settings": {"method": "game"}},
        expected=201,
    )
    assert run["settings"]["method"] == "game"
    assert not run["stale"]
    assert run["result"]["variants"][0]["game_rating"]["mu_gap"] == 0
    with factory() as db, db.begin():
        older = Match(
            game_day="2026-09-25",
            starts_at=datetime.fromisoformat("2026-09-25T20:00:00+03:00"),
            location="Тест",
            status="completed",
            field_limit=4,
            keeper_limit=0,
        )
        db.add(older)
        db.flush()
        db.add(MatchResult(match_id=older.id, completed=True))
        for index, player_id in enumerate(player_ids):
            db.add(
                ResultParticipant(
                    match_id=older.id,
                    player_id=player_id,
                    team="white" if index < 2 else "black",
                    position="field",
                )
            )
        db.add(
            ResultGoal(
                match_id=older.id,
                id=str(uuid4()),
                team="white",
                kind="goal",
                author_id=player_ids[0],
            )
        )
    assert call("GET", path + "/balance")[0]["stale"]
    call(
        "POST",
        path + f"/balance/{run['id']}/apply",
        {"version": match["version"], "variant": 0},
        expected=409,
    )
    fresh = call(
        "POST",
        path + "/balance",
        {"version": match["version"], "settings": {"method": "game"}},
        expected=201,
    )
    applied = call(
        "POST",
        path + f"/balance/{fresh['id']}/apply",
        {"version": match["version"], "variant": 0},
    )
    assert applied["team_ratings"]["method"] == "auto-game"
    assert applied["team_ratings"]["game_summary"]["mu_gap"] >= 0
    assert len({r["team"] for r in applied["registrations"]}) == 2
    approved = call(
        "POST",
        path + "/actions/approve",
        {"version": applied["version"]},
    )
    assert approved["team_ratings"]["frozen"]
    assert approved["team_ratings"]["game_summary"] == applied["team_ratings"]["game_summary"]
