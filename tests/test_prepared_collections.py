from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from fczhk.models import Match, Publication, Registration
from fczhk.scheduling import MOSCOW
from fczhk.services import schedule_tick

OPENING = datetime(2032, 6, 1, 12, tzinfo=MOSCOW)


@pytest.fixture
def clock(call, monkeypatch):
    clock = [OPENING - timedelta(hours=2)]
    for path in (
        "fczhk.notifications.now",
        "fczhk.services.now",
        "fczhk.routes.administration.now",
    ):
        monkeypatch.setattr(path, lambda: clock[0])
    call(
        "PUT",
        "/template",
        {
            **call("GET", "/template"),
            "enabled": True,
            "location": "Манеж",
            "extended_chat_id": "-1001111111",
            "announcements_chat_id": "-1002222222",
            "announcement_enabled": True,
        },
    )
    return clock


def prepare(call):
    schedule = call("GET", "/schedule/next", role="player")
    return call(
        "POST", "/schedule/next/prepare", {k: schedule[k] for k in ("opening_at", "starts_at")}
    )


def include(call, match, pid, position="field"):
    return call(
        "POST",
        f"/matches/{match['id']}/participants",
        dict(version=match["version"], player_id=pid, position=position),
    )


def test_prepared_list_is_private_silent_idempotent_and_opens_with_queue(env, call, clock):
    cfg, factory, _, _, ids = env
    public_schedule = call("GET", "/schedule/next", role="player")
    m = prepare(call)
    assert prepare(call)["id"] == m["id"]
    assert m["status"] == "draft" and datetime.fromisoformat(m["scheduled_opening_at"]) == OPENING
    m = include(call, m, ids["admin"])
    first = m["registrations"][0]
    clock[0] += timedelta(minutes=1)
    keeper = call("POST", "/players/guests", {"alias": "Вратарь заранее"}, expected=201)
    m = include(call, m, keeper["id"], "keeper")
    assert include(call, m, keeper["id"], "keeper")["version"] == m["version"]
    assert all(not r["paid"] and not r["forced"] and not r["selected"] for r in m["registrations"])
    assert call("GET", "/matches/current", role="player") is None
    assert call("GET", "/matches", role="player") == []
    assert call("GET", "/matches/current")["id"] == m["id"]
    for suffix in ("", "/lineup", "/predictions", "/result", "/auction", "/auctions/history"):
        call("GET", f"/matches/{m['id']}" + suffix, role="player", expected=404)
    call("POST", f"/matches/{m['id']}/join", {"position": "field"}, role="player", expected=400)
    assert call("GET", "/schedule/next", role="player") == {
        **public_schedule,
        "server_now": clock[0].isoformat(),
    }
    with factory() as db:
        assert not list(db.scalars(select(Publication)))
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, OPENING - timedelta(seconds=1)) is None
    clock[0] = OPENING
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, clock[0]) == m["id"]
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, clock[0]) is None
    m = call("GET", "/matches/current", role="player")
    assert m["status"] == "open" and m["registrations"][0]["id"] == first["id"]
    clock[0] += timedelta(seconds=1)
    m = call("POST", f"/matches/{m['id']}/join", {"position": "field"}, role="player")
    assert [r["player_id"] for r in m["registrations"] if r["position"] == "field"] == [
        ids["admin"],
        ids["player"],
    ]
    assert m["registrations"][0]["registered_at"] == first["registered_at"]
    assert not any(r["forced"] for r in m["registrations"])
    with factory() as db:
        assert len(list(db.scalars(select(Match)))) == 1
        assert (
            len(list(db.scalars(select(Publication).where(Publication.kind == "collection")))) == 1
        )
    # Being recorded early does not bypass the administrator's payment confirmation.
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    assert not any(r["selected"] for r in m["registrations"])


def test_prepare_rejects_nonadmin_stale_schedule_and_opening_in_progress(call, clock):
    schedule = call("GET", "/schedule/next", role="player")
    body = {k: schedule[k] for k in ("opening_at", "starts_at")}
    call("POST", "/schedule/next/prepare", body, role="player", expected=403)
    call("POST", "/schedule/next/prepare", body, role=None, expected=401)
    changed = call("PUT", "/template", {**call("GET", "/template"), "opening_time": "13:00"})
    call("POST", "/schedule/next/prepare", body, expected=409)
    clock[0] = OPENING + timedelta(hours=1)
    call(
        "POST", "/schedule/next/prepare", {**body, "opening_at": clock[0].isoformat()}, expected=409
    )
    call("PUT", "/template", {**changed, "enabled": False})
    call("POST", "/schedule/next/prepare", body, expected=409)


def test_prepared_collection_keeps_saved_schedule_after_template_edit_and_manual_open(
    env, call, clock
):
    cfg, factory, _, _, ids = env
    m = include(call, prepare(call), ids["player"])
    call(
        "PUT",
        "/template",
        {
            **call("GET", "/template"),
            "opening_weekday": 2,
            "opening_time": "14:00",
            "game_weekday": 5,
        },
    )
    assert (
        datetime.fromisoformat(call("GET", "/schedule/next", role="player")["opening_at"])
        == OPENING
    )
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, OPENING) == m["id"]
    assert (
        call("GET", f"/matches/{m['id']}", role="player")["registrations"][0]["player_id"]
        == ids["player"]
    )


def test_manual_open_keeps_pre_entries_and_removal_is_silent(env, call, clock):
    m = include(call, prepare(call), env[4]["admin"])
    m = include(call, m, env[4]["player"])
    removed = m["registrations"][1]
    m = call(
        "POST",
        f"/matches/{m['id']}/registrations/{removed['id']}/remove",
        {"version": m["version"]},
    )
    with env[1]() as db:
        assert not list(db.scalars(select(Publication)))
    m = call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})
    assert m["status"] == "open"
    assert [r["player_id"] for r in m["registrations"]] == [env[4]["admin"]]
    assert not m["registrations"][0]["forced"]
    with env[1]() as db, db.begin():
        assert schedule_tick(db, env[0], OPENING) is None


def test_draft_pre_registration_allows_reserve_and_preserves_payment_confirmation(env, call, clock):
    m = prepare(call)
    with env[1]() as db, db.begin():
        db.get(Match, m["id"]).field_limit = 2
    for i in range(3):
        guest = call("POST", "/players/guests", {"alias": f"Ранний {i}"}, expected=201)
        m = include(call, m, guest["id"])
    assert [r["in_main"] for r in m["registrations"]] == [True, True, False]
    first = m["registrations"][0]
    m = call(
        "PUT",
        f"/matches/{m['id']}/registrations/{first['id']}/payment",
        {"version": m["version"], "paid": True},
    )
    m = call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    assert [r["selected"] for r in m["registrations"]] == [True, False, False]
    with env[1]() as db:
        assert db.get(Registration, first["id"]).paid
