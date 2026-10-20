from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from fczhk.models import Match, Publication, SkippedGameDay
from fczhk.notifications import delivery_allowed, next_collection
from fczhk.scheduling import MOSCOW
from fczhk.services import schedule_tick
from fczhk.worker import deliver_one

OPENING = datetime(2032, 6, 1, 12, tzinfo=MOSCOW)


def configure(call, **changes):
    return call(
        "PUT",
        "/template",
        {
            **call("GET", "/template"),
            "enabled": True,
            "location": "Манеж",
            "announcements_chat_id": "-1001111111",
            "extended_chat_id": "-1002222222",
            "announcement_enabled": True,
            "announcement_minutes": 30,
            "payment_reminder_enabled": True,
            "payment_reminder_weekday": 3,
            "payment_reminder_time": "18:00",
            **changes,
        },
    )


def tick(env, at):
    with env[1]() as db, db.begin():
        return schedule_tick(db, env[0], at)


def notices(env, kind):
    with env[1]() as db:
        return list(
            db.scalars(select(Publication).where(Publication.kind == kind).order_by(Publication.id))
        )


def test_announcement_boundary_restart_and_no_early_match(env, call):
    configure(call)
    assert tick(env, OPENING - timedelta(minutes=30, seconds=1)) is None
    assert notices(env, "opening_notice") == []
    for _ in range(3):
        assert tick(env, OPENING - timedelta(minutes=30)) is None
    messages = notices(env, "opening_notice")
    assert len(messages) == 1
    post = messages[0]
    assert post.chat_id == "-1001111111" and post.match_id is None
    assert "через 30 мин." in post.text and "04.06.2032 · 20:00 МСК" in post.text
    assert post.expires_at == OPENING
    with env[1]() as db:
        assert not list(db.scalars(select(Match)))
    assert tick(env, OPENING)
    assert len(notices(env, "opening_notice")) == 1


def test_late_announcement_uses_remaining_minutes_and_preserves_retry(env, call):
    configure(call)
    tick(env, OPENING - timedelta(minutes=17))
    with env[1]() as db, db.begin():
        p = db.scalar(select(Publication).where(Publication.kind == "opening_notice"))
        assert "через 17 мин." in p.text
        p.attempts = 2
        p.next_attempt_at = OPENING - timedelta(minutes=5)
    tick(env, OPENING - timedelta(minutes=15))
    p = notices(env, "opening_notice")[0]
    assert p.attempts == 2 and p.next_attempt_at == OPENING - timedelta(minutes=5)


async def test_opening_notice_delivery_and_expiration(env, call, monkeypatch):
    configure(call)
    at = OPENING - timedelta(minutes=30)
    monkeypatch.setattr("fczhk.notifications.now", lambda: at)
    monkeypatch.setattr("fczhk.worker.now", lambda: at)
    tick(env, at)
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=10)))
    assert await deliver_one(env[0], env[1], bot)
    assert not await deliver_one(env[0], env[1], bot)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == "-1001111111"
    assert notices(env, "opening_notice")[0].status == "sent"


async def test_delayed_announcement_does_not_arrive_after_opening(env, call, monkeypatch):
    configure(call)
    tick(env, OPENING - timedelta(minutes=30))
    monkeypatch.setattr("fczhk.worker.now", lambda: OPENING)
    monkeypatch.setattr("fczhk.notifications.now", lambda: OPENING)
    bot = SimpleNamespace(send_message=AsyncMock())
    assert await deliver_one(env[0], env[1], bot)
    bot.send_message.assert_not_awaited()
    assert notices(env, "opening_notice")[0].status == "cancelled"


def test_skipped_or_manual_game_has_no_announcement_and_countdown_skips_it(env, call):
    configure(call)
    with env[1]() as db, db.begin():
        db.add(SkippedGameDay(game_day="2032-06-04", reason="Нет поля", actor_id=env[4]["admin"]))
    tick(env, OPENING - timedelta(minutes=30))
    assert notices(env, "opening_notice") == []
    with env[1]() as db:
        assert next_collection(db, OPENING - timedelta(minutes=30))[
            "opening_at"
        ] == OPENING + timedelta(weeks=1)
    with env[1]() as db, db.begin():
        db.delete(db.get(SkippedGameDay, "2032-06-04"))
        db.add(
            Match(
                game_day="2032-06-04",
                starts_at=OPENING + timedelta(days=3, hours=8),
                location="Ручная",
                status="draft",
            )
        )
    tick(env, OPENING - timedelta(minutes=30))
    assert notices(env, "opening_notice") == []
    assert tick(env, OPENING) is None


def test_payment_notice_configured_time_one_per_game_and_no_autoschedule_required(env, call):
    configure(call)
    mid = tick(env, OPENING)
    at = OPENING + timedelta(days=2, hours=6)
    tick(env, at - timedelta(seconds=1))
    assert notices(env, "payment_notice") == []
    t = call("GET", "/template")
    call("PUT", "/template", {**t, "enabled": False})
    for _ in range(3):
        tick(env, at)
    posts = notices(env, "payment_notice")
    assert len(posts) == 1 and posts[0].match_id == mid
    assert posts[0].chat_id == "-1001111111"
    assert posts[0].text.startswith("Внимание, нужно оплатить футбол!")
    with env[1]() as db, db.begin():
        db.get(Match, mid).status = "cancelled"
    with env[1]() as db:
        assert not delivery_allowed(db, db.get(Publication, posts[0].id), at)


def test_countdown_endpoint_exposes_schedule_only_and_honours_disabled(env, call, monkeypatch):
    configure(call)
    monkeypatch.setattr("fczhk.notifications.now", lambda: OPENING - timedelta(minutes=10))
    result = call("GET", "/schedule/next", role="player")
    assert datetime.fromisoformat(result["opening_at"]) == OPENING
    assert set(result) == {"server_now", "opening_at", "starts_at", "location"}
    assert "-100" not in str(result)
    configure(call, enabled=False)
    assert call("GET", "/schedule/next", role="player")["opening_at"] is None
    call("GET", "/schedule/next", role=None, expected=401)


@pytest.mark.parametrize(
    "patch",
    [
        {"announcement_minutes": 0},
        {"announcement_minutes": True},
        {"announcements_chat_id": "https://t.me/club"},
        {"payment_reminder_weekday": 7},
        {"payment_reminder_time": "25:00"},
        {"payment_reminder_weekday": 1, "payment_reminder_time": "11:59"},
        {"payment_reminder_weekday": 4, "payment_reminder_time": "20:00"},
        {"announcements_chat_id": ""},
    ],
)
def test_invalid_notification_settings_do_not_change_schedule(env, call, patch):
    before = configure(call)
    call("PUT", "/template", {**before, **patch}, expected=422)
    assert call("GET", "/template") == before
    call("PUT", "/template", before, role="player", expected=403)


def test_registration_notices_are_transactional_deduplicated_and_individually_switchable(
    env, call, game
):
    configure(call)
    path = f"/matches/{game['id']}/join"
    call("POST", path, {"position": "field"}, role="player")
    call("POST", path, {"position": "field"}, role="player")
    posts = notices(env, "registration")
    assert len(posts) == 1 and posts[0].chat_id == "-1002222222"
    assert "Игрок записался полевым" in posts[0].text
    configure(call, extended_registration_enabled=False)
    call("POST", path, {"position": "keeper"}, role="player")
    assert len(notices(env, "registration")) == 1
    call("DELETE", path, role="player")
    call("DELETE", path, role="player")
    assert len(notices(env, "withdrawal")) == 1
    assert call("GET", f"/matches/{game['id']}")["registrations"] == []
    configure(call, extended_cancellation_enabled=False)
    call("POST", path, {"position": "field"}, role="player")
    call("DELETE", path, role="player")
    assert len(notices(env, "withdrawal")) == 1


async def test_disabling_type_also_cancels_queued_notifications(env, call, game):
    configure(call)
    call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    configure(call, extended_registration_enabled=False)
    # Remove the fixture's unrelated collection post from this isolated test queue.
    with env[1]() as db, db.begin():
        for p in db.scalars(select(Publication).where(Publication.kind == "collection")):
            p.status = "sent"
    bot = SimpleNamespace(send_message=AsyncMock())
    assert not await deliver_one(env[0], env[1], bot)
    bot.send_message.assert_not_awaited()
    assert notices(env, "registration")[0].status == "cancelled"
