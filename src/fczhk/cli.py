import argparse
import asyncio
from datetime import datetime, timedelta

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from .config import Settings
from .db import Base, database, now
from .models import GameTemplate, Match, Player, Registration
from .services import MOSCOW


def demo_settings() -> Settings:
    return Settings(
        _env_file=None,
        env="demo",
        database_url="sqlite:///./.local/demo.db",
        admin_ids="1001",
        bot_token="",
        community_chat_id="",
        publication_chat_id="",
        public_url="http://localhost:8000",
    )


def seed_demo(cfg):
    engine, factory = database(cfg.database_url)
    Base.metadata.create_all(engine)
    with factory() as db, db.begin():
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
    parser = argparse.ArgumentParser(description="FCZHK")
    parser.add_argument(
        "command",
        choices=["demo", "serve", "migrate", "worker", "demo-worker", "bot", "configure-bot"],
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    cfg = demo_settings() if args.command in ("demo", "demo-worker") else Settings()
    if args.command == "migrate":
        migrate(cfg.database_url)
    elif args.command in ("worker", "demo-worker"):
        from .worker import run_worker

        asyncio.run(run_worker(cfg, once=args.once))
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
            create_app(cfg), host="127.0.0.1" if cfg.env == "demo" else "0.0.0.0", port=args.port
        )
