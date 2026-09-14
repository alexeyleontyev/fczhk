from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from fczhk.models import GameTemplate, Match, Publication
from fczhk.services import MOSCOW, schedule_tick
from fczhk.worker import deliver_one


def test_scheduler_moscow_boundary_restart_and_manual_collision(env):
    cfg, factory, _, _, _ = env
    with factory() as db, db.begin():
        t = db.get(GameTemplate, 1)
        t.enabled = True
        t.location = "Стадион"
        t.start_time = "20:00"
    for at, expected in [
        (datetime(2026, 9, 15, 11, 59, tzinfo=MOSCOW), False),
        (datetime(2026, 9, 15, 12, 0, tzinfo=MOSCOW), True),
        (datetime(2026, 9, 15, 12, 1, tzinfo=MOSCOW), False),
    ]:
        with factory() as db, db.begin():
            assert bool(schedule_tick(db, cfg, at)) is expected
    with factory() as db:
        games = list(db.scalars(select(Match)))
        assert len(games) == 1
        assert games[0].starts_at.astimezone(MOSCOW).hour == 20
        assert len(list(db.scalars(select(Publication)))) == 1
    with factory() as db, db.begin():
        db.add(
            Match(
                game_day="2026-09-25",
                starts_at=datetime(2026, 9, 25, 20, tzinfo=MOSCOW),
                location="Вручную",
            )
        )
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, datetime(2026, 9, 22, 12, tzinfo=MOSCOW)) is None
        assert db.scalar(select(Match).where(Match.game_day == "2026-09-25")).status == "draft"


async def test_delivery_success_only_once(env, call, game):
    cfg, factory, _, _, _ = env
    cfg.bot_username = "example_bot"
    with factory() as db, db.begin():
        db.scalar(select(Publication)).chat_id = "123"

    class Bot:
        calls = 0

        async def send_message(self, *args, **kwargs):
            self.calls += 1
            return SimpleNamespace(message_id=42)

    bot = Bot()
    assert await deliver_one(cfg, factory, bot)
    assert not await deliver_one(cfg, factory, bot)
    assert bot.calls == 1
    with factory() as db:
        p = db.scalar(select(Publication))
        assert p.status == "sent" and p.message_ids == [42]


async def test_uncertain_delivery_needs_manual_retry(env, call, game):
    cfg, factory, _, _, _ = env
    with factory() as db, db.begin():
        db.scalar(select(Publication)).chat_id = "123"

    class Bot:
        async def send_message(self, *args, **kwargs):
            raise TimeoutError("secret token must not appear in logs or error")

    assert await deliver_one(cfg, factory, Bot())
    with factory() as db:
        p = db.scalar(select(Publication))
        assert p.status == "uncertain"
        assert "secret" not in p.error
        pid = p.id
    assert not await deliver_one(cfg, factory, Bot())
    call("POST", f"/publications/{pid}/retry")
    with factory() as db:
        assert db.get(Publication, pid).status == "pending"
