import copy

import pytest
from sqlalchemy import func, select

from fczhk.models import (
    Audit,
    BalanceRun,
    Match,
    MatchResult,
    Player,
    ResultParticipant,
    TeamRatingSnapshot,
    TeamSnapshot,
)
from tests.test_ratings import add_guest, prepared, vote


def preview(call, m, method="community", **kwargs):
    return call(
        "POST",
        f"/matches/{m['id']}/lineup/preview",
        dict(version=m["version"], method=method),
        **kwargs,
    )


def payload(p):
    return {k: p[k] for k in ("version", "roster_version", "fingerprint")} | dict(
        assignments=p["result"]["variants"][0]["assignments"], source=p["method"], variant=0
    )


def counts(env):
    with env[1]() as db:
        return [
            db.scalar(select(func.count()).select_from(t))
            for t in (Audit, BalanceRun, TeamSnapshot, TeamRatingSnapshot)
        ]


@pytest.mark.parametrize("method", ["community", "game"])
def test_member_previews_are_private_and_read_only(env, call, game, method):
    m = prepared(call, game, keepers=2)
    before = counts(env)
    p = preview(call, m, method, role="player")
    assert len(p["result"]["variants"]) == 3
    for v in p["result"]["variants"]:
        assert set(v["assignments"]) == {str(r["id"]) for r in m["registrations"]}
        assert sorted(
            v["assignments"][str(r["id"])] for r in m["registrations"] if r["position"] == "keeper"
        ) == ["black", "white"]
    assert counts(env) == before
    assert call("GET", f"/matches/{m['id']}") == m
    assert p["auction"] is None
    call("POST", f"/matches/{m['id']}/lineup/confirm", payload(p), role="player", expected=403)
    call("GET", f"/matches/{m['id']}/lineup", role=None, expected=401)


def test_confirmation_is_atomic_and_freezes_positions_and_scores(env, call, game):
    m = prepared(call, game, keepers=2)
    path = f"/matches/{m['id']}"
    p = preview(call, m)
    body = payload(p)
    rid = next(k for k, t in body["assignments"].items() if t == "white")
    body["placements"] = {rid: dict(x=0.3, y=0.7)}
    approved = call("POST", path + "/lineup/confirm", body)
    assert approved["status"] == "approved" and approved["team_ratings"]["frozen"]
    assert approved["publications"] == m["publications"]
    official = call("GET", path + "/lineup", role="player")
    assert official["placements"] == body["placements"]
    assert official["official_players"] == p["players"]
    assert len(call("GET", path + "/balance")) == 1
    before = counts(env)
    call("POST", path + "/lineup/confirm", body, expected=409)
    assert counts(env) == before
    field = next(r for r in m["registrations"] if r["position"] == "field")
    vote(call, field["player_id"], attack=0, defense=0)
    changed = call("GET", path + "/lineup")
    assert changed["official_players"] == official["official_players"]
    assert changed["fingerprint"] != official["fingerprint"]
    assert changed["placements"] == official["placements"]


@pytest.mark.parametrize(
    "bad",
    [
        "missing",
        "extra",
        "unequal",
        "keeper",
        "half",
        "point_id",
        "unassigned_point",
        "bounds",
        "nan",
    ],
)
def test_invalid_confirmation_rolls_back_all_writes(env, call, game, bad):
    m = prepared(call, game, keepers=2)
    p = preview(call, m)
    body = copy.deepcopy(payload(p))
    assignments = body["assignments"]
    rid = next(k for k, t in assignments.items() if t == "white")
    if bad == "missing":
        assignments.pop(rid)
    if bad == "extra":
        assignments[99999] = "black"
    if bad == "unequal":
        assignments.update({k: "white" for k in assignments})
    if bad == "keeper":
        for r in m["registrations"]:
            if r["position"] == "keeper":
                assignments[str(r["id"])] = "white"
    if bad == "half":
        body["placements"] = {rid: dict(x=0.3, y=0.2)}
    if bad == "point_id":
        body["placements"] = {99999: dict(x=0.3, y=0.2)}
    if bad == "unassigned_point":
        assignments[rid] = None
        body["placements"] = {rid: dict(x=0.3, y=0.7)}
    if bad == "bounds":
        body["placements"] = {rid: dict(x=2.0, y=0.7)}
    if bad == "nan":
        body["placements"] = {rid: dict(x="NaN", y=0.7)}
    before = counts(env)
    call(
        "POST",
        f"/matches/{m['id']}/lineup/confirm",
        body,
        expected=422 if bad in ("bounds", "nan") else 409 if bad in ("missing", "extra") else 400,
    )
    assert counts(env) == before
    assert call("GET", f"/matches/{m['id']}") == m


def test_changed_ratings_block_old_draft_even_without_version_change(env, call, game):
    m = prepared(call, game)
    p = preview(call, m)
    vote(call, m["registrations"][0]["player_id"], attack=5, defense=1)
    before = counts(env)
    call("POST", f"/matches/{m['id']}/lineup/confirm", payload(p), expected=409)
    assert counts(env) == before
    assert call("GET", f"/matches/{m['id']}")["version"] == m["version"]


def test_missing_ratings_are_not_zero_but_openskill_still_available(call, game):
    m, _ = add_guest(call, game, "Без оценки", defense=None)
    m, _ = add_guest(call, m, "Настоящий ноль", attack=0, defense=0)
    m = call("POST", f"/matches/{m['id']}/actions/finalize", dict(version=m["version"]))
    preview(call, m, expected=400)
    p = preview(call, m, "game", role="player")
    assert p["players"][0]["attack"] is None
    assert p["players"][1]["attack"] == 0
    assert all(r["game_mu"] == 25 for r in p["players"])
    assert call("POST", f"/matches/{m['id']}/lineup/confirm", payload(p))["status"] == "approved"


def test_open_preview_uses_provisional_selected_roster_and_draft_is_hidden(call, game):
    m, _ = add_guest(call, game, "Первый")
    m, _ = add_guest(call, m, "Второй")
    p = preview(call, m, role="player")
    assert len(p["players"]) == 2
    call("POST", f"/matches/{m['id']}/lineup/confirm", payload(p), expected=409)
    draft = call(
        "POST",
        "/matches",
        dict(starts_at="2026-10-09T20:00:00+03:00", location="Черновик"),
        expected=201,
    )
    call("GET", f"/matches/{draft['id']}/lineup", role="player", expected=404)


def test_historical_board_falls_back_to_current_community_ratings(env, call, game):
    ids = env[4]
    # Imported games have results but no registrations or frozen rating inputs.
    with env[1]() as db, db.begin():
        db.add(MatchResult(match_id=game["id"], completed=True))
        db.flush()
        db.add_all(
            [
                ResultParticipant(match_id=game["id"], player_id=pid, team=team, position="field")
                for pid, team in ((ids["admin"], "white"), (ids["player"], "black"))
            ]
        )
    vote(call, ids["player"], attack=5, defense=5)
    p = call("GET", f"/matches/{game['id']}/lineup", role="player")
    assert not p["editable"]
    assert {r["registration_id"] for r in p["players"]} == {-ids["admin"], -ids["player"]}
    rated = next(r for r in p["players"] if r["player_id"] == ids["player"])
    assert (rated["attack"], rated["defense"], rated["source"]) == (5, 5, "community")
    missing = next(r for r in p["players"] if r["player_id"] == ids["admin"])
    assert (
        missing["attack"] is None and missing["defense"] is None and missing["source"] == "missing"
    )
    preview(call, game, "game", expected=400)


@pytest.mark.parametrize("position", ["field", "keeper"])
@pytest.mark.parametrize("score", [0, 5])
@pytest.mark.parametrize("saved", [False, True])
def test_imported_board_resolves_linked_profiles_without_rewriting_history(
    env, call, game, position, score, saved
):
    guest = call("POST", "/players/guests", {"alias": "Историческое имя"}, expected=201)
    ids = env[4]
    with env[1]() as db, db.begin():
        db.add(MatchResult(match_id=game["id"], completed=True))
        db.flush()
        db.add_all(
            [
                ResultParticipant(
                    match_id=game["id"], player_id=guest["id"], team="white", position=position
                ),
                ResultParticipant(
                    match_id=game["id"], player_id=ids["admin"], team="black", position="field"
                ),
            ]
        )
        if saved:
            db.get(Match, game["id"]).approved_version = 1
            snapshot = TeamSnapshot(match_id=game["id"], version=1, teams=[])
            db.add(snapshot)
            db.flush()
            db.add(
                TeamRatingSnapshot(
                    snapshot_id=snapshot.id,
                    data={
                        "inputs": [
                            dict(
                                player_id=guest["id"],
                                position=position,
                                attack=None if position == "keeper" else 1,
                                defense=2,
                            )
                        ]
                    },
                )
            )
    # Keep separate field and keeper ratings; the actual match position selects the fallback.
    vote(call, guest["id"], attack=score, defense=score)
    if position == "keeper":
        vote(call, guest["id"], attack=None, defense=score, position="keeper")
    before = call("GET", f"/matches/{game['id']}/lineup", role="player")
    call("POST", f"/players/{guest['id']}/link", {"target_id": ids["player"]})
    after = call("GET", f"/matches/{game['id']}/lineup", role="player")
    linked = next(p for p in after["players"] if p["registration_id"] == -guest["id"])
    assert linked["player_id"] == ids["player"] and linked["alias"] == guest["alias"]
    assert linked["position"] == position
    assert after["assignments"] == before["assignments"]
    assert after["players"] == after["official_players"]
    assert linked["attack"] == (None if position == "keeper" else 1 if saved else score)
    assert linked["defense"] == (2 if saved else score)
    assert linked["source"] == ("snapshot" if saved else "community")
    assert [(p["attack"], p["defense"]) for p in after["players"]] == [
        (p["attack"], p["defense"]) for p in before["players"]
    ]
    assert not after["editable"]
    with env[1]() as db:
        source = db.get(Player, guest["id"])
        assert source.merged_into == ids["player"] and source.alias.startswith("Архив ")
        assert db.get(ResultParticipant, (game["id"], guest["id"])).position == position


@pytest.mark.parametrize("position", ["field", "keeper"])
def test_completed_board_keeps_frozen_ratings_and_positions_after_profile_link(
    env, call, game, position
):
    m = prepared(call, game, keepers=2)
    path = f"/matches/{m['id']}"
    reg = next(r for r in m["registrations"] if r["position"] == position)
    m = call(
        "PUT",
        path + f"/registrations/{reg['id']}/rating",
        dict(
            version=m["version"],
            position=position,
            attack=None if position == "keeper" else 0,
            defense=0,
        ),
    )
    p = preview(call, m)
    body = payload(p)
    point = dict(x=0.32, y=0.7 if body["assignments"][str(reg["id"])] == "white" else 0.3)
    body["placements"] = {str(reg["id"]): point}
    call("POST", path + "/lineup/confirm", body)
    result = call("GET", path + "/result")
    call(
        "PUT",
        path + "/result",
        dict(
            version=result["version"],
            participants=[
                {k: row[k] for k in ("player_id", "team", "position")}
                for row in result["participants"]
            ],
            goals=[],
            completed=True,
        ),
    )
    before = call("GET", path + "/lineup", role="player")
    with env[1]() as db:
        snapshot = copy.deepcopy(db.scalar(select(TeamRatingSnapshot)).data)
    target = env[4]["player"]
    call("POST", f"/players/{reg['player_id']}/link", {"target_id": target})
    vote(call, target, attack=None if position == "keeper" else 5, defense=5, position=position)
    after = call("GET", path + "/lineup", role="player")
    expected = copy.deepcopy(before["players"])
    next(p for p in expected if p["player_id"] == reg["player_id"])["player_id"] = target
    assert after["players"] == after["official_players"] == expected
    linked = next(p for p in after["players"] if p["player_id"] == target)
    assert linked["defense"] == 0 and linked["source"] == "snapshot"
    assert after["assignments"] == before["assignments"]
    assert after["placements"] == before["placements"] == {str(-reg["player_id"]): point}
    with env[1]() as db:
        assert db.scalar(select(TeamRatingSnapshot)).data == snapshot
        assert db.get(ResultParticipant, (m["id"], reg["player_id"]))
