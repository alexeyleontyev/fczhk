from datetime import datetime
from uuid import uuid4

from fczhk import game_ratings
from fczhk.models import Match, MatchResult, Player, Prediction, ResultGoal, ResultParticipant
from fczhk.services import MOSCOW


def test_seasons_filter_statistics_but_keep_cumulative_skill_rating(env, call):
    factory, ids = env[1], env[4]
    with factory() as db, db.begin():
        guest = Player(alias="Партнёр прошлого сезона")
        db.add(guest)
        db.flush()
        mids = []
        for day, season, white_wins in (
            ("2025-01-24", "2024-2025", True),
            ("2026-06-05", "2026", False),
        ):
            match = Match(
                game_day=day,
                starts_at=datetime.fromisoformat(day).replace(tzinfo=MOSCOW),
                season=season,
                location="Поле",
                status="completed",
            )
            db.add(match)
            db.flush()
            mids.append(match.id)
            db.add(MatchResult(match_id=match.id, completed=True))
            for pid, team in (
                (ids["admin"], "white"),
                (ids["player"], "black"),
                (guest.id, "white"),
            ):
                db.add(
                    ResultParticipant(match_id=match.id, player_id=pid, team=team, position="field")
                )
            db.add(
                ResultGoal(
                    id=str(uuid4()),
                    match_id=match.id,
                    team="white" if white_wins else "black",
                    kind="goal",
                    author_id=ids["admin"] if white_wins else ids["player"],
                    assist_id=guest.id if white_wins else None,
                )
            )
            db.add(
                Prediction(
                    match_id=match.id,
                    player_id=ids["admin"],
                    white_score=1,
                    black_score=0,
                    approved_version=1,
                )
            )
        draft = Match(
            game_day="2027-01-01",
            starts_at=datetime(2027, 1, 1, tzinfo=MOSCOW),
            season="2027",
            location="Черновик",
        )
        db.add(draft)
    assert call("GET", "/seasons", role="player") == ["2026", "2024-2025"]
    assert call("GET", "/seasons") == ["2027", "2026", "2024-2025"]
    for season, wins, losses, goals, assists in [("2024-2025", 1, 0, 1, 1), ("2026", 0, 1, 0, 0)]:
        query = f"?season={season}"
        board = call("GET", "/leaderboards" + query, role="player")["results"]
        assert board["matches"] == 1
        rows = {r["player_id"]: r for r in board["boards"]["points"]}
        assert (
            rows[ids["admin"]]["wins"],
            rows[ids["admin"]]["losses"],
            rows[ids["admin"]]["goals"],
        ) == (wins, losses, goals)
        stats = call("GET", f"/players/{ids['admin']}/stats{query}")
        assert (stats["games"], stats["wins"], stats["losses"], stats["goals"]) == (
            1,
            wins,
            losses,
            goals,
        )
        assert len(stats["matches"]) == 1 and stats["partners"][0]["games"] == 1
        archive = call("GET", "/matches" + query, role="player")
        assert len(archive) == 1 and archive[0]["season"] == season
        rating = call("GET", "/game-ratings" + query)
        assert rating == call("GET", "/game-ratings")
        assert rating["matches"] == 2
        assert all(p["games"] == 2 for p in rating["players"])
        with factory() as db:
            predictions = game_ratings.forecast_history(db, season=season)
        assert len(predictions) == 1
        assert call("GET", "/predictions/standings" + query)[0]["points"] == (3 if wins else 0)
    total = call("GET", f"/players/{ids['admin']}/stats")
    assert (total["games"], total["wins"], total["losses"], total["goals"]) == (2, 1, 1, 1)
    assert total["partners"][0]["games"] == 2
    assert call("GET", "/game-ratings")["matches"] == 2
    assert call("GET", "/leaderboards")["results"]["matches"] == 2
    assert call("GET", "/leaderboards?season=absent")["results"]["matches"] == 0
    assert call("GET", "/game-ratings?season=absent") == call("GET", "/game-ratings")
    assert call("GET", "/predictions/standings?season=absent") == []
    assert call("GET", f"/players/{ids['admin']}/stats?season=absent")["games"] == 0
    call("GET", "/seasons", role=None, expected=401)


def test_game_season_defaults_to_local_year_and_edit_preserves_explicit_season(call):
    body = dict(
        starts_at="2025-12-31T23:30:00+00:00",
        location="Поле",
        cost=0,
        description="",
        payment_details="",
    )
    default = call("POST", "/matches", body, expected=201)
    assert default["season"] == "2026" and default["game_day"] == "2026-01-01"
    body["starts_at"] = "2025-01-24T20:30:00+03:00"
    body["season"] = "2024-2025"
    old = call("POST", "/matches", body, expected=201)
    assert old["season"] == "2024-2025"
    body.pop("season")
    body["version"] = old["version"]
    edited = call("PUT", f"/matches/{old['id']}", body)
    assert edited["season"] == "2024-2025"
    body["season"] = "2025"
    body["version"] = edited["version"]
    assert call("PUT", f"/matches/{old['id']}", body)["season"] == "2025"
