import asyncio

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from sqlalchemy import select

from .auth import check_member, player_for_telegram
from .db import database, now
from .models import BotCallbackReceipt, Match, Player
from .ratings import public_averages
from .services import MOSCOW, DomainError, get_match, match_data, register
from .worker import app_link, chunks


def dispatcher(cfg, factory):
    dp = Dispatcher()
    router = Router()

    def menu(match_id=None):
        rows = [[InlineKeyboardButton(text="⚽ Открыть приложение", url=app_link(cfg, match_id))]]
        if match_id:
            rows.append(
                [
                    InlineKeyboardButton(text="Полевой", callback_data=f"join:{match_id}:field"),
                    InlineKeyboardButton(text="Вратарь", callback_data=f"join:{match_id}:keeper"),
                ]
            )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def identify(user):
        await check_member(cfg, user.id)

        def save():
            with factory() as db, db.begin():
                return player_for_telegram(db, user.id, user.first_name).id

        return await asyncio.to_thread(save)

    @router.message(Command("start", "help", "profile", "admin"))
    async def start(message: Message):
        if not message.from_user:
            return
        try:
            await identify(message.from_user)
            await message.answer(
                "ФКЖК · футбол по пятницам\n\n"
                "Запись открывается во вторник в 12:00 МСК. Приоритет — время записи среди оплативших.\n"
                "В приложении: alias, текущая игра, оценки игроков и подбор составов.\n\n"
                "/game — текущая игра\n/players — игроки",
                reply_markup=menu(),
            )
        except DomainError as exc:
            await message.answer(exc.message)

    @router.message(Command("game"))
    async def game(message: Message):
        if not message.from_user:
            return
        try:
            await identify(message.from_user)

            def read_game():
                with factory() as db:
                    m = db.scalar(
                        select(Match)
                        .where(Match.status.not_in(["draft", "cancelled"]), Match.starts_at > now())
                        .order_by(Match.starts_at)
                        .limit(1)
                    )
                    if not m:
                        return None
                    data = match_data(db, m)
                    lines = [
                        f"⚽ {m.starts_at.astimezone(MOSCOW):%d.%m · %H:%M} МСК",
                        m.location,
                        "",
                    ]
                    for position, label in (("field", "Полевые"), ("keeper", "Вратари")):
                        lines.append(label)
                        for r in data["registrations"]:
                            if r["position"] == position:
                                date = (
                                    r["registered_at"].astimezone(MOSCOW).strftime("%d.%m %H:%M:%S")
                                )
                                lines.append(
                                    f"{r['queue']}. {r['alias']} · {'оплачен' if r['paid'] else 'без оплаты'} · {date}"
                                    + (" · в составе" if r["selected"] else "")
                                )
                    match_id, is_open = m.id, m.status == "open"
                return lines, match_id, is_open

            result = await asyncio.to_thread(read_game)
            if result is None:
                await message.answer("Ближайшая игра еще не опубликована.", reply_markup=menu())
                return
            lines, match_id, is_open = result
            parts = chunks("\n".join(lines))
            for i, part in enumerate(parts):
                await message.answer(
                    part,
                    reply_markup=menu(match_id if is_open else None)
                    if i == len(parts) - 1
                    else None,
                )
        except DomainError as exc:
            await message.answer(exc.message)

    @router.message(Command("players"))
    async def players(message: Message):
        if not message.from_user:
            return
        try:
            await identify(message.from_user)

            def read_players():
                with factory() as db:
                    people = list(
                        db.scalars(
                            select(Player)
                            .where(Player.merged_into.is_(None), Player.telegram_id.is_not(None))
                            .order_by(Player.alias)
                        )
                    )
                    averages = public_averages(db, [p.id for p in people])

                    def score(value):
                        return "—" if value is None else f"{value:.2f}".rstrip("0").rstrip(".")

                    names = []
                    for p in people:
                        r = averages[p.id]
                        names.append(
                            f"{p.alias} · А {score(r['field']['attack'])} / З {score(r['field']['defense'])} · вратарь З {score(r['keeper']['defense'])}"
                        )
                return names

            names = await asyncio.to_thread(read_players)
            for part in chunks("Игроки · средние оценки\n\n" + "\n".join(names)):
                await message.answer(part)
        except DomainError as exc:
            await message.answer(exc.message)

    @router.callback_query(F.data.startswith("join:"))
    async def join(query: CallbackQuery):
        try:
            _, mid, position = query.data.split(":")
            if position not in ("field", "keeper"):
                raise DomainError("Неизвестное амплуа")
            pid = await identify(query.from_user)

            def save_join():
                with factory() as db, db.begin():
                    match = get_match(db, int(mid), lock=True)
                    if not db.get(BotCallbackReceipt, query.id):
                        register(db, pid, match, position)
                        db.add(BotCallbackReceipt(id=query.id, player_id=pid, match_id=match.id))

            await asyncio.to_thread(save_join)
            await query.answer("Вы записаны. Оплату подтверждает администратор.", show_alert=True)
        except (DomainError, ValueError) as exc:
            await query.answer(
                exc.message if isinstance(exc, DomainError) else "Неизвестная игра", show_alert=True
            )

    dp.include_router(router)
    return dp


async def handle_update(cfg, factory, data):
    async with Bot(cfg.bot_token) as bot:
        await dispatcher(cfg, factory).feed_update(
            bot, Update.model_validate(data, context={"bot": bot})
        )


async def poll(cfg):
    _, factory = database(cfg.database_url)
    async with Bot(cfg.bot_token) as bot:
        await dispatcher(cfg, factory).start_polling(bot)


async def configure_bot(cfg):
    """Explicit operator command; never run automatically at application startup."""
    from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

    async with Bot(cfg.bot_token) as bot:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Вход в клуб"),
                BotCommand(command="game", description="Текущая игра и участники"),
                BotCommand(command="players", description="Игроки клуба"),
                BotCommand(command="profile", description="Мой профиль"),
                BotCommand(command="help", description="Помощь"),
            ]
        )
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Открыть клуб", web_app=WebAppInfo(url=cfg.public_url)
            )
        )
        if cfg.webhook_secret:
            await bot.set_webhook(
                url=cfg.public_url.rstrip("/") + "/api/telegram/webhook",
                secret_token=cfg.webhook_secret,
                allowed_updates=["message", "callback_query"],
            )
            print("Webhook и меню настроены. Отдельный polling-процесс не нужен.")
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            print("Меню настроено. Запустите polling: uv run fczhk bot")
