import argparse
import asyncio
import json
import signal
from datetime import datetime, timedelta

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from .config import Settings
from .db import Base, database, now
from .models import GameTemplate, Match, Player, RatingState, Registration
from .services import MOSCOW


def demo_settings() -> Settings:
    return Settings(
        _env_file=None,
        env="demo",
        database_url="sqlite:///./.local/demo.db",
        owner_id=1001,
        admin_ids="",
        bot_token="",
        community_chat_id="",
        publication_chat_id="",
        public_url="http://localhost:8000",
    )


def seed_demo(cfg):
    engine, factory = database(cfg.database_url)
    Base.metadata.create_all(engine)
    with factory() as db, db.begin():
        if db.get(RatingState, 1) is None:
            db.add(RatingState(id=1))
        if db.get(GameTemplate, 1) is None:
            db.add(GameTemplate(id=1, location="Манеж «Север» · демонстрация", cost=80000))
        if db.scalar(select(Player.id)):
            return
        names = [
            "Алексей",
            "Михаил",
            "Артём",
            "Даниил",
            "Никита",
            "Сергей",
            "Илья",
            "Максим",
            "Андрей",
            "Дмитрий",
            "Роман",
            "Павел",
            "Кирилл",
            "Антон",
            "Владимир",
            "Денис",
            "Евгений",
            "Игорь",
            "Олег",
            "Виктор",
            "Глеб",
        ]
        players = [Player(alias=n, telegram_id=1001 + i) for i, n in enumerate(names)]
        db.add_all(players)
        db.flush()
        local = now().astimezone(MOSCOW)
        friday = local.date() + timedelta(days=(4 - local.weekday()) % 7 or 7)
        m = Match(
            game_day=friday.isoformat(),
            starts_at=datetime.combine(friday, datetime.min.time(), MOSCOW).replace(hour=20),
            location="Манеж «Север»",
            description="Пятничный футбол. Берите белую и черную футболки.\nДемонстрационные данные — реальная запись не ведется.",
            cost=80000,
            payment_details="Демо: переводить деньги не нужно",
            status="open",
        )
        db.add(m)
        db.flush()
        for i, p in enumerate(players):
            if i == 1:  # Demo player starts unregistered so the join path can be tried.
                continue
            db.add(
                Registration(
                    match_id=m.id,
                    player_id=p.id,
                    position="keeper" if i >= 18 else "field",
                    paid=(i % 5 != 0),
                    registered_at=now() - timedelta(hours=5, minutes=30 - i),
                )
            )


def migrate(url):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    _, factory = database(url)
    with factory() as db, db.begin():
        if not db.get(GameTemplate, 1):
            db.add(GameTemplate(id=1))


def main():
    parser = argparse.ArgumentParser(
        description="ФКЖК: сервер, Telegram-бот, worker и эксплуатационные команды"
    )
    parser.add_argument(
        "command",
        choices=[
            "demo",
            "serve",
            "migrate",
            "worker",
            "demo-worker",
            "bot",
            "configure-bot",
            "worker-health",
            "check-bot",
        ],
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    cfg = demo_settings() if args.command in ("demo", "demo-worker") else Settings()
    if args.command == "migrate":
        migrate(cfg.database_url)
    elif args.command in ("worker", "demo-worker"):
        from .worker import run_worker

        async def worker_main():
            loop = asyncio.get_running_loop()
            task = asyncio.current_task()
            loop.add_signal_handler(signal.SIGTERM, task.cancel)
            try:
                await run_worker(cfg, once=args.once)
            except asyncio.CancelledError:
                pass

        asyncio.run(worker_main())
    elif args.command == "worker-health":
        from .operations import status

        _, factory = database(cfg.database_url)
        with factory() as db:
            healthy = status(db, cfg)["worker"]["healthy"]
        raise SystemExit(0 if healthy else 1)
    elif args.command == "check-bot":
        from aiogram import Bot

        async def check_bot():
            async with Bot(cfg.bot_token) as bot:
                info = await bot.get_webhook_info()
                # Do not print a URL or Telegram error text: these can contain secrets.
                expected = cfg.public_url.rstrip("/") + "/api/telegram/webhook"
                recent_error = info.last_error_date and now() - info.last_error_date < timedelta(
                    minutes=5
                )
                healthy = info.url == expected and not recent_error
                print(
                    json.dumps(
                        dict(
                            configured=info.url == expected,
                            pending=info.pending_update_count,
                            last_error_at=info.last_error_date.isoformat()
                            if info.last_error_date
                            else None,
                        )
                    )
                )
                return healthy

        raise SystemExit(0 if asyncio.run(check_bot()) else 1)
    elif args.command == "bot":
        from .bot import poll

        asyncio.run(poll(cfg))
    elif args.command == "configure-bot":
        from .bot import configure_bot

        asyncio.run(configure_bot(cfg))
    else:
        if args.command == "demo":
            seed_demo(cfg)
        from .api import create_app

        uvicorn.run(
            create_app(cfg),
            host="127.0.0.1" if cfg.env == "demo" else "0.0.0.0",
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips=cfg.forwarded_allow_ips,
        )
