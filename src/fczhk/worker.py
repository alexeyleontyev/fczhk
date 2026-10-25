import asyncio
import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import case, or_, select

from .db import database, now
from .models import Publication
from .notifications import SCHEDULED_KINDS, delivery_allowed
from .operations import cleanup_sessions, heartbeat
from .services import schedule_tick

log = logging.getLogger(__name__)


def chunks(value: str, size: int = 3500, *, utf16=False) -> list[str]:
    # Preserve legacy boundaries for retries/edits; new result posts also account for emoji.
    result = []
    while (len(value.encode("utf-16-le")) // 2 if utf16 else len(value)) > size:
        limit = size
        if utf16:
            units, limit = 0, 0
            for char in value:
                units += 2 if ord(char) > 0xFFFF else 1
                if units > size:
                    break
                limit += 1
        cut = value.rfind("\n", 0, limit + 1)
        cut = cut if cut > 0 else limit
        result.append(value[:cut])
        value = value[cut:].lstrip("\n")
    return result + ([value] if value else [])


def app_link(cfg, match_id=None, screen=None):
    if cfg.bot_username:
        return f"https://t.me/{cfg.bot_username}?startapp=" + (
            f"game_{match_id}" + (f"_{screen}" if screen else "") if match_id else "home"
        )
    if match_id:
        return (
            cfg.public_url.rstrip("/")
            + f"/?game={match_id}"
            + (f"&screen={screen}" if screen else "")
        )
    return cfg.public_url


def publication_parts(kind, content):
    # The bounded start notice contains two escaped captain links. Keep its HTML intact.
    return (
        [(content, "HTML")]
        if kind == "auction_start"
        else [(part, None) for part in chunks(content, utf16=kind in ("result", "lineup_share"))]
    )


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
            .order_by(case((Publication.kind.in_(SCHEDULED_KINDS), 0), else_=1), Publication.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not pub:
            return False
        if not delivery_allowed(db, pub):
            pub.status, pub.error = "cancelled", None
            return True
        pub.status, pub.claimed_at = "sending", now()
        pub.attempts += 1
        pub_id, chat, content, match_id, kind = (
            pub.id,
            pub.chat_id,
            pub.text,
            pub.match_id,
            pub.kind,
        )
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
        parts = publication_parts(kind, content)
        for i, (part, parse_mode) in enumerate(parts):
            if i < len(already_sent):
                continue
            markup = (
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Открыть игру", url=app_link(cfg, match_id))]
                        + (
                            [
                                InlineKeyboardButton(
                                    text="Сделать прогноз",
                                    url=app_link(cfg, match_id, "prediction"),
                                )
                            ]
                            if kind == "teams"
                            else []
                        )
                    ]
                )
                if i == len(parts) - 1
                else None
            )
            sent = await bot.send_message(chat, part, reply_markup=markup, parse_mode=parse_mode)
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
                Publication.next_attempt_at <= now(),
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
            prefix = (
                "⚠️ НЕАКТУАЛЬНО — результат исправлен\n\n"
                if pub.kind == "result"
                else "⚠️ НЕАКТУАЛЬНО — состав или параметры изменились\n\n"
            )
            for mid, (part, parse_mode) in zip(
                pub.message_ids, publication_parts(pub.kind, pub.text), strict=True
            ):
                try:
                    await bot.edit_message_text(
                        text=prefix + part,
                        chat_id=pub.chat_id,
                        message_id=mid,
                        parse_mode=parse_mode,
                    )
                except TelegramBadRequest as exc:
                    if "message is not modified" not in str(exc):
                        raise
            pub.stale_marked, pub.error = True, None
        except TelegramRetryAfter as exc:
            pub.next_attempt_at = now() + timedelta(seconds=exc.retry_after + 1)
            pub.error = "Telegram ограничил частоту редактирования"
        except TelegramBadRequest:
            pub.error = "Не удалось пометить старый пост. Проверьте сообщение и права бота."
        except Exception:
            pub.error = "Не удалось пометить старый пост. Сообщите участникам об изменении и повторите пометку."


async def run_worker(cfg, once=False):
    _, factory = database(cfg.database_url)
    bot = Bot(cfg.bot_token) if cfg.bot_token and cfg.env != "demo" else None
    cleaned_at = None
    try:
        while True:
            try:
                with factory() as db, db.begin():
                    schedule_tick(db, cfg)
                await deliver_one(cfg, factory, bot)
                await mark_stale(cfg, factory, bot)
                if cleaned_at is None or now() - cleaned_at > timedelta(hours=1):
                    cleanup_sessions(factory)
                    cleaned_at = now()
                heartbeat(factory)
            except Exception as exc:
                # Exception text from external libraries may contain credentials.
                code = type(exc).__name__
                log.error("Worker iteration failed (%s); retrying", code)
                try:
                    heartbeat(factory, code)
                except Exception:
                    log.error("Worker heartbeat unavailable")
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
        cleanup_sessions(factory)
        heartbeat(factory)

    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            log.error("Demo worker iteration failed; retrying.")
        await asyncio.sleep(3)
