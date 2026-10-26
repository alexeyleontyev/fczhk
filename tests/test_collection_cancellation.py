from datetime import datetime, timedelta

from sqlalchemy import select

from fczhk.models import Publication, SkippedGameDay
from fczhk.scheduling import MOSCOW
from fczhk.services import schedule_tick
from tests.test_prepared_collections import OPENING, include, prepare
from tests.test_prepared_collections import clock as clock


def opened(call, ids):
    m = include(call, prepare(call), ids["player"])
    entry = m["registrations"][0]
    m = call(
        "PUT",
        f"/matches/{m['id']}/registrations/{entry['id']}/payment",
        {"version": m["version"], "paid": True},
    )
    return call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})


def test_no_keeps_date_queue_and_payments_and_reopens_at_saved_time(env, call, clock):
    m = opened(call, env[4])
    original = m["registrations"][0]
    options = call("GET", f"/matches/{m['id']}/cancellation")
    assert datetime.fromisoformat(options["next_starts_at"]) == datetime(
        2032, 6, 11, 20, tzinfo=MOSCOW
    )
    call("GET", f"/matches/{m['id']}/cancellation", role="player", expected=403)
    closed = call(
        "POST",
        f"/matches/{m['id']}/cancel",
        {"version": m["version"], "reason": "Открыт по ошибке", "advance_schedule": False},
    )
    assert closed["status"] == "draft"
    assert closed["starts_at"] == m["starts_at"]
    assert closed["registrations"][0]["id"] == original["id"]
    assert closed["registrations"][0]["registered_at"] == original["registered_at"]
    assert closed["registrations"][0]["paid"]
    assert not closed["registrations"][0]["forced"]
    call("GET", f"/matches/{m['id']}", role="player", expected=404)
    schedule = call("GET", "/schedule/next", role="player")
    assert datetime.fromisoformat(schedule["opening_at"]) == OPENING
    with env[1]() as db, db.begin():
        assert schedule_tick(db, env[0], OPENING) == m["id"]
    assert call("GET", f"/matches/{m['id']}", role="player")["registrations"][0]["paid"]


def test_no_after_opening_stays_closed_until_manual_open(env, call, clock):
    m = opened(call, env[4])
    clock[0] = OPENING + timedelta(hours=1)
    closed = call(
        "POST",
        f"/matches/{m['id']}/cancel",
        {"version": m["version"], "reason": "Закрыть сбор", "advance_schedule": False},
    )
    assert closed["collection_paused"] and closed["scheduled_opening_at"] is None
    schedule = call("GET", "/schedule/next", role="player")
    assert schedule["opening_at"] is None
    assert datetime.fromisoformat(schedule["starts_at"]) == datetime.fromisoformat(m["starts_at"])
    with env[1]() as db, db.begin():
        assert schedule_tick(db, env[0], clock[0]) is None
    guest = call("POST", "/players/guests", {"alias": "После закрытия"}, expected=201)
    closed = include(call, closed, guest["id"])
    assert not any(r["forced"] for r in closed["registrations"])
    opened_again = call("POST", f"/matches/{m['id']}/actions/open", {"version": closed["version"]})
    assert opened_again["status"] == "open"


def test_yes_preview_skips_unavailable_dates_and_rejects_changed_schedule(env, call, clock):
    m = opened(call, env[4])
    before = call("GET", f"/matches/{m['id']}/cancellation")
    with env[1]() as db, db.begin():
        db.add(
            SkippedGameDay(game_day="2032-06-11", reason="Поле закрыто", actor_id=env[4]["admin"])
        )
    body = {
        "version": m["version"],
        "reason": "Отмена игры",
        "advance_schedule": True,
        "expected_next_starts_at": before["next_starts_at"],
    }
    call("POST", f"/matches/{m['id']}/cancel", body, expected=409)
    assert call("GET", f"/matches/{m['id']}")["status"] == "open"
    after = call("GET", f"/matches/{m['id']}/cancellation")
    assert datetime.fromisoformat(after["next_starts_at"]) == datetime(
        2032, 6, 18, 20, tzinfo=MOSCOW
    )
    cancelled = call(
        "POST",
        f"/matches/{m['id']}/cancel",
        {**body, "expected_next_starts_at": after["next_starts_at"]},
    )
    assert cancelled["status"] == "cancelled"
    assert datetime.fromisoformat(
        call("GET", "/schedule/next", role="player")["starts_at"]
    ) == datetime.fromisoformat(after["next_starts_at"])
    with env[1]() as db:
        publication = db.scalar(
            select(Publication).where(
                Publication.match_id == m["id"], Publication.kind == "cancellation"
            )
        )
        assert "Игра отменена" in publication.text
