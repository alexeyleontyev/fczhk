from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from fczhk.models import GameTemplate, Match, Publication
from fczhk.scheduling import MOSCOW, schedule_window
from fczhk.services import schedule_tick


@pytest.mark.parametrize(
    "opening_day,opening_time,game_day,start_time,at,expected_start",
    [
        (1, "12:00", 4, "20:00", "2026-09-15T12:00:00+03:00", "2026-09-18T20:00:00+03:00"),
        (6, "23:45", 0, "00:15", "2026-10-18T21:00:00+00:00", "2026-10-19T00:15:00+03:00"),
        (3, "18:10", 0, "09:40", "2026-12-31T18:10:00+03:00", "2027-01-04T09:40:00+03:00"),
        (1, "10:30", 1, "18:00", "2026-09-15T10:30:00+03:00", "2026-09-15T18:00:00+03:00"),
        (1, "12:00", 4, "20:00", "2026-09-18T19:59:59+03:00", "2026-09-18T20:00:00+03:00"),
        (3, "12:05", 5, "17:35", "2024-02-29T12:05:00+03:00", "2024-03-02T17:35:00+03:00"),
    ],
)
def test_configured_scheduler_dates_moscow_time_and_publication(
    env, call, opening_day, opening_time, game_day, start_time, at, expected_start
):
    cfg, factory, *_ = env
    template = call("GET", "/template")
    template.update(
        enabled=True,
        location="Настроенный манеж",
        opening_weekday=opening_day,
        opening_time=opening_time,
        game_weekday=game_day,
        start_time=start_time,
    )
    call("PUT", "/template", template)
    clock = datetime.fromisoformat(at)
    with factory() as db, db.begin():
        mid = schedule_tick(db, cfg, clock)
        assert mid
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, clock + timedelta(seconds=1)) is None
    with factory() as db:
        match = db.get(Match, mid)
        expected = datetime.fromisoformat(expected_start)
        assert match.starts_at == expected
        assert match.game_day == expected.date().isoformat()
        assert match.status == "open" and match.location == "Настроенный манеж"
        publication = db.scalar(select(Publication).where(Publication.match_id == mid))
        assert publication.kind == "collection" and publication.status == "pending"
        assert expected.astimezone(MOSCOW).strftime("%d.%m.%Y · %H:%M МСК") in publication.text
        assert len(list(db.scalars(select(Publication)))) == 1


@pytest.mark.parametrize("at", ["2026-10-18T20:44:59+00:00", "2026-10-18T21:15:00+00:00"])
def test_scheduler_does_not_open_early_or_after_game_start(env, at):
    cfg, factory, *_ = env
    with factory() as db, db.begin():
        template = db.get(GameTemplate, 1)
        template.enabled, template.location = True, "Манеж"
        template.opening_weekday, template.opening_time = 6, "23:45"
        template.game_weekday, template.start_time = 0, "00:15"
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, datetime.fromisoformat(at)) is None
    with factory() as db:
        assert list(db.scalars(select(Match))) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"opening_weekday": -1},
        {"game_weekday": 7},
        {"opening_weekday": True},
        {"opening_time": "24:00"},
        {"start_time": "19:60"},
        {"opening_weekday": 4, "opening_time": "20:00"},
        {"opening_weekday": 4, "opening_time": "21:00"},
    ],
)
def test_invalid_schedule_rejected_without_changes(call, patch):
    template = call("GET", "/template")
    call("PUT", "/template", {**template, **patch}, expected=422)
    assert call("GET", "/template") == template


def test_schedule_edits_keep_existing_games_and_reject_stale_revision(env, call):
    cfg, factory, *_ = env
    original = call("GET", "/template")
    assert (original["opening_weekday"], original["opening_time"], original["game_weekday"]) == (
        1,
        "12:00",
        4,
    )
    template = call("PUT", "/template", {**original, "enabled": True, "location": "Манеж"})
    at = datetime(2026, 9, 15, 12, tzinfo=MOSCOW)
    with factory() as db, db.begin():
        mid = schedule_tick(db, cfg, at)
    before = call("GET", f"/matches/{mid}")
    call(
        "PUT",
        "/template",
        {**template, "game_weekday": 5, "start_time": "11:25"},
        role="player",
        expected=403,
    )
    call("PUT", "/template", {**template, "game_weekday": 5, "start_time": "11:25"})
    call("PUT", "/template", original, expected=409)
    assert call("GET", f"/matches/{mid}")["starts_at"] == before["starts_at"]


def test_skipped_custom_game_day_is_not_created(env, call):
    cfg, factory, *_ = env
    template = call("GET", "/template")
    call(
        "PUT",
        "/template",
        {
            **template,
            "enabled": True,
            "location": "Манеж",
            "opening_weekday": 6,
            "opening_time": "23:45",
            "game_weekday": 0,
            "start_time": "00:15",
        },
    )
    call("POST", "/schedule/skipped", {"game_day": "2032-06-07", "reason": "Манеж закрыт"})
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, datetime(2032, 6, 6, 23, 45, tzinfo=MOSCOW)) is None


def test_next_window_includes_current_cross_week_collection(env):
    with env[1]() as db:
        template = db.get(GameTemplate, 1)
        template.opening_weekday, template.opening_time = 6, "23:45"
        template.game_weekday, template.start_time = 0, "00:15"
        opening, starts = schedule_window(
            template, datetime.fromisoformat("2026-10-18T21:00:00+00:00")
        )
        assert opening.isoformat() == "2026-10-18T23:45:00+03:00"
        assert starts.isoformat() == "2026-10-19T00:15:00+03:00"
