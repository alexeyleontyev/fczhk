import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import or_, select

from .db import database, now
from .models import Publication
from .services import schedule_tick

log = logging.getLogger(__name__)


def chunks(value: str, size: int = 3500) -> list[str]:
    # Reserve room for a future "obsolete" prefix, split without parse_mode entities.
    result = []
    while len(value) > size:
        cut = value.rfind("\n", 0, size)
        cut = cut if cut > 0 else size
        result.append(value[:cut])
        value = value[cut:].lstrip("\n")
    return result + ([value] if value else [])


def app_link(cfg, match_id=None):
    if cfg.bot_username:
        return f"https://t.me/{cfg.bot_username}?startapp=" + (
            f"game_{match_id}" if match_id else "home"
        )
    return cfg.public_url


async def deliver_one(cfg, factory, bot=None) -> bool:
    with factory() as db, db.begin():
        # Never blindly resend after a crash between Telegram delivery and DB acknowledgement.
        for old in db.scalars(
            select(Publication)
            .where(
                Publication.status == "sending",
                Publication.claimed_at < now() - timedelta(minutes=5),
            )
            .with_for_update(skip_locked=True)
        ):
            old.status, old.error = (
                "uncertain",
                "Неизвестен результат отправки после сбоя. Проверьте чат перед повтором.",
            )
        pub = db.scalar(
            select(Publication)
            .where(
                Publication.status == "pending",
                Publication.stale.is_(False),
                Publication.next_attempt_at <= now(),
            )
            .order_by(Publication.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not pub:
            return False
        pub.status, pub.claimed_at = "sending", now()
        pub.attempts += 1
        pub_id, chat, content, match_id = pub.id, pub.chat_id, pub.text, pub.match_id
        already_sent = list(pub.message_ids)
    if cfg.env == "demo":
        with factory() as db, db.begin():
            p = db.get(Publication, pub_id)
            p.status = "demo"
        return True
    if not chat or not bot:
        with factory() as db, db.begin():
            p = db.get(Publication, pub_id)
            p.status, p.error = "failed", "Не настроен чат публикаций или бот"
        return True
    try:
        parts = chunks(content)
        for i, part in enumerate(parts):
            if i < len(already_sent):
                continue
            markup = (
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Открыть игру", url=app_link(cfg, match_id))]
                    ]
                )
                if i == len(parts) - 1
                else None
            )
            sent = await bot.send_message(chat, part, reply_markup=markup)
            already_sent.append(sent.message_id)
            with factory() as db, db.begin():
                db.get(Publication, pub_id).message_ids = list(already_sent)
        with factory() as db, db.begin():
            p = db.get(Publication, pub_id)
            p.status, p.error = "sent", None
    except TelegramRetryAfter as exc:
        with factory() as db, db.begin():
            p = db.get(Publication, pub_id)
            p.status = "pending" if p.attempts < 5 else "failed"
            p.error = "Telegram ограничил частоту отправки"
            p.next_attempt_at = now() + timedelta(seconds=exc.retry_after + 1)
    except (TelegramBadRequest, TelegramForbiddenError):
        with factory() as db, db.begin():
            p = db.get(Publication, pub_id)
            p.status, p.error = (
                "failed",
                "Telegram отклонил публикацию. Проверьте чат и права бота.",
            )
    except Exception:
        with factory() as db, db.begin():
            p = db.get(Publication, pub_id)
            p.status, p.error = (
                "uncertain",
                "Нет подтверждения доставки. Проверьте чат перед повтором.",
            )
    return True


async def mark_stale(cfg, factory, bot=None):
    with factory() as db, db.begin():
        pub = db.scalar(
            select(Publication)
            .where(
                Publication.stale.is_(True),
                Publication.stale_marked.is_(False),
                Publication.status.in_(["sent", "demo"]),
                or_(
                    Publication.error.is_(None),
                    ~Publication.error.startswith("Не удалось пометить"),
                ),
            )
            .order_by(Publication.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not pub:
            return
        if cfg.env == "demo":
            pub.stale_marked = True
            return
        try:
            for mid, part in zip(pub.message_ids, chunks(pub.text), strict=True):
                await bot.edit_message_text(
                    text="⚠️ НЕАКТУАЛЬНО — состав или параметры изменились\n\n" + part,
                    chat_id=pub.chat_id,
                    message_id=mid,
                )
            pub.stale_marked = True
        except Exception:
            pub.error = "Не удалось пометить старый пост. Сообщите участникам об изменении и опубликуйте новый."


async def run_worker(cfg, once=False):
    _, factory = database(cfg.database_url)
    bot = Bot(cfg.bot_token) if cfg.bot_token and cfg.env != "demo" else None
    try:
        while True:
            try:
                with factory() as db, db.begin():
                    schedule_tick(db, cfg)
                await deliver_one(cfg, factory, bot)
                await mark_stale(cfg, factory, bot)
            except Exception:
                log.error("Worker iteration failed; retrying. Check database availability.")
                if once:
                    raise
            if once:
                return
            await asyncio.sleep(3)
    finally:
        if bot:
            await bot.session.close()


async def run_demo_worker(cfg, factory):
    """SQLite lock waits must not block the API event loop or its transaction cleanup."""
    if cfg.env != "demo":
        raise ValueError("Demo worker requires demo settings")

    def tick():
        with factory() as db, db.begin():
            schedule_tick(db, cfg)
        asyncio.run(deliver_one(cfg, factory))
        asyncio.run(mark_stale(cfg, factory))

    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            log.error("Demo worker iteration failed; retrying.")
        await asyncio.sleep(3)
