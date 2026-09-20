from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from fczhk.db import now
from fczhk.models import Match, Player, Registration, ResultGoal


@pytest.fixture
def played(env, call):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        m = Match(
            game_day="2020-01-03",
            starts_at=now() - timedelta(days=1),
            location="Поле",
            status="approved",
            approved_version=1,
        )
        guest = Player(alias="Гость бомбардир")
        mate = Player(alias="Вратарь партнёр", telegram_id=555)
        db.add_all([m, guest, mate])
        db.flush()
        for pid, team, position in [
            (ids["admin"], "white", "field"),
            (mate.id, "white", "keeper"),
            (guest.id, "black", "field"),
        ]:
            db.add(
                Registration(
                    match_id=m.id, player_id=pid, team=team, position=position, selected=True
                )
            )
        mid, gid, mateid = m.id, guest.id, mate.id
    return mid, gid, mateid


def event(team, author=None, assist=None, kind="goal"):
    return dict(id=str(uuid4()), team=team, kind=kind, author_id=author, assist_id=assist)


def payload(call, mid, completed=False):
    result = call("GET", f"/matches/{mid}/result")
    return dict(
        version=result["version"],
        completed=completed,
        participants=[
            {k: p[k] for k in ("player_id", "team", "position")} for p in result["participants"]
        ],
        goals=result["goals"],
    )


def test_draft_completed_corrections_and_partners(env, call, played):
    mid, guest, mate = played
    admin = env[4]["admin"]
    body = payload(call, mid)
    body["goals"] = [
        event("white", admin, mate),
        event("white", guest, kind="own_goal"),
        event("black"),
    ]
    draft = call("PUT", f"/matches/{mid}/result", body)
    assert draft["score"] == {"white": 2, "black": 1}
    assert call("GET", f"/players/{admin}/stats")["games"] == 0
    body.update(version=draft["version"], completed=True)
    done = call("PUT", f"/matches/{mid}/result", body)
    stats = call("GET", f"/players/{admin}/stats", role="player")
    assert (stats["games"], stats["wins"], stats["goals"], stats["assists"]) == (1, 1, 1, 0)
    assert [p["player_id"] for p in stats["partners"]] == [mate]
    assert call("GET", f"/players/{mate}/stats")["assists"] == 1
    assert call("GET", f"/players/{guest}/stats")["goals"] == 0
    body.update(version=done["version"])
    body["goals"].append(event("black", guest))
    corrected = call("PUT", f"/matches/{mid}/result", body)
    stats = call("GET", f"/players/{admin}/stats")
    assert (stats["games"], stats["wins"], stats["draws"]) == (1, 0, 1)
    assert call("GET", f"/players/{guest}/stats")["goals"] == 1
    call("PUT", f"/matches/{mid}/result", body, expected=409)
    assert len(call("GET", f"/matches/{mid}/history")["audit"]) == 3
    assert call("GET", f"/matches/{mid}")["status"] == "completed"
    assert corrected["score"] == {"white": 2, "black": 2}
    body.update(version=corrected["version"], completed=False)
    call("PUT", f"/matches/{mid}/result", body, expected=400)


@pytest.mark.parametrize(
    "case",
    [
        "outsider",
        "self_assist",
        "opponent_assist",
        "wrong_team",
        "own_without_author",
        "own_assist",
        "duplicate",
        "remove_scorer",
        "move_scorer",
    ],
)
def test_invalid_events_are_atomic(env, call, played, case):
    mid, guest, mate = played
    admin, outsider = env[4]["admin"], env[4]["player"]
    body = payload(call, mid, True)
    goal = event("white", admin, mate)
    if case == "outsider":
        goal["author_id"] = outsider
    if case == "self_assist":
        goal["assist_id"] = admin
    if case == "opponent_assist":
        goal["assist_id"] = guest
    if case == "wrong_team":
        goal["author_id"] = guest
    if case == "own_without_author":
        goal.update(kind="own_goal", author_id=None, assist_id=None)
    if case == "own_assist":
        goal.update(kind="own_goal", author_id=guest)
    if case == "remove_scorer":
        body["participants"] = [p for p in body["participants"] if p["player_id"] != admin]
    if case == "move_scorer":
        next(p for p in body["participants"] if p["player_id"] == admin)["team"] = "black"
    body["goals"] = [goal, goal] if case == "duplicate" else [goal]
    call("PUT", f"/matches/{mid}/result", body, expected=400)
    assert call("GET", f"/matches/{mid}/result")["exists"] is False


def test_actual_replacement_guests_and_permissions(env, call, played):
    mid, guest, mate = played
    admin, target = env[4]["admin"], env[4]["player"]
    body = payload(call, mid, True)
    call("PUT", f"/matches/{mid}/result", body, role="player", expected=403)
    body["participants"] = [p for p in body["participants"] if p["player_id"] != mate]
    body["goals"] = [event("black", guest)]
    call("PUT", f"/matches/{mid}/result", body)
    assert call("GET", f"/players/{mate}/stats")["games"] == 0
    call("POST", f"/players/{guest}/link", {"target_id": target})
    stats = call("GET", f"/players/{target}/stats")
    assert (stats["games"], stats["wins"], stats["goals"]) == (1, 1, 1)
    old_stats = call("GET", f"/players/{guest}/stats")
    assert old_stats == stats
    body = payload(call, mid, True)
    assert body["goals"][0]["author_id"] == target
    call("PUT", f"/matches/{mid}/result", body)
    m = call("GET", f"/matches/{mid}")
    rid = next(r["id"] for r in m["registrations"] if r["player_id"] == admin)
    call(
        "POST",
        f"/matches/{mid}/registrations/{rid}/remove",
        {"version": m["version"]},
        expected=400,
    )
    call("PUT", f"/matches/{mid}/teams", {"version": m["version"], "assignments": {}}, expected=400)
    assert call("GET", f"/players/{target}/stats")["goals"] == 1
    with env[1]() as db:
        assert len(list(db.scalars(select(ResultGoal)))) == 1


def test_start_boundary_and_unapproved_results(env, call, played, monkeypatch):
    mid, _, _ = played
    with env[1]() as db:
        start = db.get(Match, mid).starts_at
    body = payload(call, mid, True)
    monkeypatch.setattr("fczhk.results.now", lambda: start - timedelta(microseconds=1))
    call("PUT", f"/matches/{mid}/result", body, expected=400)
    monkeypatch.setattr("fczhk.results.now", lambda: start)
    call("PUT", f"/matches/{mid}/result", body)


def test_link_overlap_in_actual_roster_rejected(env, call, played):
    mid, guest, _ = played
    target = env[4]["player"]
    body = payload(call, mid, True)
    body["participants"].append(dict(player_id=target, team="black", position="field"))
    call("PUT", f"/matches/{mid}/result", body)
    call("POST", f"/players/{guest}/link", {"target_id": target}, expected=409)
    assert call("GET", f"/players/{guest}/stats")["player_id"] == guest
