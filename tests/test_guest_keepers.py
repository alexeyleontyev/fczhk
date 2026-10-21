import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from fczhk.guest_keepers import GUEST_KEEPER_ALIAS, LEGACY_KEEPER_ALIASES
from fczhk.models import Match, MatchResult, Player, ResultGoal, ResultParticipant


@pytest.fixture
def historical_keepers(env):
    with env[1]() as db, db.begin():
        keepers = [Player(alias=alias) for alias in sorted(LEGACY_KEEPER_ALIASES)]
        real = Player(alias="Вратарь от Руса")
        db.add_all([*keepers, real])
        db.flush()
        by_alias = {p.alias: p.id for p in keepers}
        white = by_alias["Вратарь (смены, 26.06.2026, белые)"]
        black = by_alias["Вратарь (смены, 26.06.2026, чёрные)"]
        match = Match(
            game_day="2026-06-26",
            starts_at=datetime(2026, 6, 26, 17, tzinfo=UTC),
            location="Поле",
            status="completed",
        )
        db.add(match)
        db.flush()
        db.add(MatchResult(match_id=match.id, completed=True))
        db.flush()
        db.add_all(
            [
                ResultParticipant(match_id=match.id, player_id=pid, team=team, position=position)
                for pid, team, position in [
                    (white, "white", "keeper"),
                    (black, "black", "keeper"),
                    (env[4]["admin"], "white", "field"),
                    (env[4]["player"], "black", "field"),
                ]
            ]
        )
        db.add(
            ResultGoal(
                match_id=match.id,
                id=str(uuid4()),
                team="white",
                kind="goal",
                author_id=env[4]["admin"],
            )
        )
        return dict(ids=by_alias, white=white, black=black, real=real.id, match=match.id)


def test_one_catalog_card_preserves_both_historical_teams(env, call, historical_keepers):
    h = historical_keepers
    corrections = json.loads(Path("data/historical_import_corrections.json").read_text())
    assert set(corrections["placeholder_players"]) == LEGACY_KEEPER_ALIASES
    people = call("GET", "/players", role="player")
    shared = [p for p in people if p.get("shared_keeper")]
    assert len(shared) == 1
    assert shared[0]["alias"] == GUEST_KEEPER_ALIAS
    assert shared[0]["id"] == min(h["ids"].values())
    assert not any(p["alias"] in LEGACY_KEEPER_ALIASES for p in people)
    assert next(p for p in people if p["id"] == h["real"])["alias"] == "Вратарь от Руса"
    path = f"/matches/{h['match']}"
    result = call("GET", path + "/result")
    keepers = [p for p in result["participants"] if p["position"] == "keeper"]
    assert {(p["player_id"], p["team"]) for p in keepers} == {
        (h["white"], "white"),
        (h["black"], "black"),
    }
    assert {p["alias"] for p in keepers} == {GUEST_KEEPER_ALIAS}
    board = call("GET", path + "/lineup", role="player")
    assert {p["alias"] for p in board["players"] if p["position"] == "keeper"} == {
        GUEST_KEEPER_ALIAS
    }
    assert board["assignments"][str(-h["white"])] == "white"
    assert board["assignments"][str(-h["black"])] == "black"
    body = dict(
        version=result["version"],
        completed=True,
        goals=result["goals"],
        participants=[
            {k: p[k] for k in ("player_id", "team", "position")} for p in result["participants"]
        ],
    )
    saved = call("PUT", path + "/result", body)
    assert saved["participants"] == result["participants"]
    assert saved["score"] == {"white": 1, "black": 0}
    winner = call("GET", f"/players/{env[4]['admin']}/stats")
    loser = call("GET", f"/players/{env[4]['player']}/stats")
    assert (winner["games"], winner["wins"], winner["goals"]) == (1, 1, 1)
    assert (loser["games"], loser["losses"]) == (1, 1)
    assert winner["partners"] == loser["partners"] == []
    boards = call("GET", "/leaderboards")["results"]
    assert boards["matches"] == 1
    assert {p["player_id"] for p in boards["boards"]["points"]} == set(env[4].values())
    with env[1]() as db:
        assert {p.alias: p.id for p in db.scalars(select(Player)) if p.shared_keeper} == h["ids"]
        assert all(db.get(Player, pid).merged_into is None for pid in h["ids"].values())


def test_shared_role_cannot_be_rated_or_claimed_as_a_person(env, call, historical_keepers):
    for pid in historical_keepers["ids"].values():
        call("GET", f"/players/{pid}/stats", expected=400)
        call(
            "PUT",
            f"/players/{pid}/ratings",
            dict(position="keeper", defense=3, revision=0),
            expected=400,
        )
        call("POST", "/me/profile-claim", {"guest_id": pid}, role="player", expected=409)
        call("POST", f"/players/{pid}/link", {"target_id": env[4]["player"]}, expected=400)
    call("POST", "/players/guests", {"alias": GUEST_KEEPER_ALIAS}, expected=409)
    call("PATCH", "/me", {"alias": GUEST_KEEPER_ALIAS}, expected=409)
    call(
        "PUT",
        f"/players/{historical_keepers['real']}/ratings",
        dict(position="keeper", defense=3, revision=0),
    )


def test_common_card_can_be_added_only_as_keeper(call, game):
    guest = call("POST", "/players/guests", {"alias": GUEST_KEEPER_ALIAS}, expected=201)
    assert guest["shared_keeper"] is True
    path = f"/matches/{game['id']}/participants"
    body = dict(version=game["version"], player_id=guest["id"], position="field")
    call("POST", path, body, expected=400)
    added = call("POST", path, {**body, "position": "keeper"})
    assert added["registrations"][0]["alias"] == GUEST_KEEPER_ALIAS
    assert added["registrations"][0]["position"] == "keeper"
