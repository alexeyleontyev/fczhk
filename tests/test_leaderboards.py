from datetime import timedelta

import pytest
from test_results import event, payload

from fczhk.db import now
from fczhk.models import Match, MatchResult, Player, Registration, ResultGoal, ResultParticipant


@pytest.fixture
def played_game(env):
    with env[1]() as db, db.begin():
        match = Match(
            game_day="2020-01-03",
            starts_at=now() - timedelta(days=1),
            location="Поле",
            status="approved",
        )
        guest = Player(alias="Гость бомбардир")
        keeper = Player(alias="Вратарь партнёр", telegram_id=555)
        db.add_all([match, guest, keeper])
        db.flush()
        for pid, team, position in (
            (env[4]["admin"], "white", "field"),
            (keeper.id, "white", "keeper"),
            (guest.id, "black", "field"),
        ):
            db.add(
                Registration(
                    match_id=match.id, player_id=pid, team=team, position=position, selected=True
                )
            )
        return match.id, guest.id, keeper.id


def test_result_leaderboards_include_keepers_revisions_and_goal_events(env, call, played_game):
    mid, guest, keeper = played_game
    admin = env[4]["admin"]
    assert call("GET", "/leaderboards", role=None, expected=401)["detail"]
    empty = call("GET", "/leaderboards", role="player")["results"]
    assert empty["matches"] == 0 and empty["boards"]["points"] == []

    body = payload(call, mid, completed=True)
    body["goals"] = [
        event("white", admin, keeper),
        event("white", guest, kind="own_goal"),
        event("black", guest),
    ]
    completed = call("PUT", f"/matches/{mid}/result", body)

    # A draft with statistics must not leak into any public total.
    with env[1]() as db, db.begin():
        draft = Match(
            game_day="2020-01-04",
            starts_at=now() - timedelta(days=1),
            location="Поле",
            status="approved",
        )
        db.add(draft)
        db.flush()
        db.add(MatchResult(match_id=draft.id, completed=False))
        db.add(
            ResultParticipant(match_id=draft.id, player_id=admin, team="white", position="field")
        )
        db.add(
            ResultGoal(
                match_id=draft.id, id="draft-goal", team="white", kind="goal", author_id=admin
            )
        )

    table = call("GET", "/leaderboards", role="player")["results"]
    assert table["matches"] == 1
    points = {row["player_id"]: row for row in table["boards"]["points"]}
    assert (points[admin]["points"], points[admin]["win_rate"]) == (3, 100)
    assert (points[keeper]["points"], points[keeper]["assists"]) == (3, 1)
    assert (points[guest]["points"], points[guest]["goals"]) == (0, 1)
    assert [r["player_id"] for r in table["boards"]["goals"]][:2] == [admin, guest]
    assert table["boards"]["goal_assist"][0]["goal_assist"] == 1

    # A result correction is reflected immediately without accumulating the old version.
    body["version"] = completed["version"]
    body["goals"].append(event("black", guest))
    call("PUT", f"/matches/{mid}/result", body)
    corrected = call("GET", "/leaderboards", role="player")["results"]
    points = {row["player_id"]: row for row in corrected["boards"]["points"]}
    assert all(row["points"] == 1 for row in points.values())
    assert all(row["win_rate"] == 50 for row in points.values())
    assert points[guest]["goals"] == 2


def test_win_rate_uses_each_players_games_and_merged_identity(env, call, played_game):
    mid, guest, keeper = played_game
    admin, target = env[4]["admin"], env[4]["player"]
    body = payload(call, mid, completed=True)
    body["goals"] = [event("white", admin)]
    call("PUT", f"/matches/{mid}/result", body)

    with env[1]() as db, db.begin():
        other = Match(
            game_day="2020-01-04",
            starts_at=now() - timedelta(days=1),
            location="Поле",
            status="completed",
        )
        db.add(other)
        db.flush()
        db.add(MatchResult(match_id=other.id, completed=True))
        db.add_all(
            [
                ResultParticipant(
                    match_id=other.id, player_id=admin, team="black", position="field"
                ),
                ResultParticipant(
                    match_id=other.id, player_id=guest, team="white", position="field"
                ),
                ResultGoal(
                    match_id=other.id, id="second-goal", team="white", kind="goal", author_id=guest
                ),
            ]
        )
    board = call("GET", "/leaderboards", role="player")["results"]["boards"]
    assert board["win_rate"][0]["player_id"] == keeper
    assert board["win_rate"][0]["win_rate"] == 100
    assert {r["player_id"]: r["win_rate"] for r in board["points"]}[admin] == 50
    assert board["goals"][0]["player_id"] == admin  # Same total; more games wins the tie.

    call("POST", f"/players/{guest}/link", {"target_id": target})
    merged = call("GET", "/leaderboards", role="player")["results"]["boards"]
    ids = {row["player_id"] for row in merged["points"]}
    assert guest not in ids and target in ids
    assert next(row for row in merged["goals"] if row["player_id"] == target)["goals"] == 1


def test_community_leaderboards_filters_and_public_access(env, call):
    admin, player = env[4]["admin"], env[4]["player"]
    call(
        "PUT", f"/players/{player}/ratings", dict(position="field", attack=4, defense=2, revision=0)
    )
    call(
        "PUT",
        f"/players/{admin}/ratings",
        dict(position="field", attack=3, defense=5, revision=0),
        role="player",
    )
    call(
        "PUT",
        f"/players/{admin}/ratings",
        dict(position="keeper", attack=None, defense=4, revision=0),
        role="player",
    )

    boards = call("GET", "/leaderboards", role="player")["community"]["boards"]
    assert [(r["player_id"], r["score"]) for r in boards["field_total"]] == [
        (admin, 8),
        (player, 6),
    ]
    assert [r["player_id"] for r in boards["field_attack"]] == [player, admin]
    assert [r["player_id"] for r in boards["field_defense"]] == [admin, player]
    assert [(r["player_id"], r["score"]) for r in boards["keeper_defense"]] == [(admin, 4)]
    assert all(
        "count" not in row and "reviews" not in row for rows in boards.values() for row in rows
    )
