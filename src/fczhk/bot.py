import asyncio

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from sqlalchemy import select

from .auth import check_member, player_for_telegram
from .db import database, now
from .models import BotCallbackReceipt, GameTemplate, Match, MatchResult, Registration
from .results import player_stats, result_data, result_text
from .scheduling import schedule_description
from .services import MOSCOW, DomainError, cancel, get_match, match_data, register, report_payment
from .worker import app_link, chunks


def dispatcher(cfg, factory):
    dp = Dispatcher()
    router = Router()

    def menu(match_id=None, *, registration_open=False, payment=None):
        rows = [[InlineKeyboardButton(text="⚽ Открыть приложение", url=app_link(cfg, match_id))]]
        if registration_open:
            rows.extend(
                [
                    [
                        InlineKeyboardButton(
                            text="Записаться полевым", callback_data=f"join:{match_id}:field"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Записаться вратарем", callback_data=f"join:{match_id}:keeper"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="Отменить запись", callback_data=f"leave:{match_id}"
                        )
                    ],
                ]
            )
        if payment:
            rows.append([payment])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def registration_stamp(registration):
        # The row is reused on rejoining; bind the button to this enrollment too.
        return registration.registered_at.strftime("%Y%m%d%H%M%S%f")

    def game_menu(db, match, pid):
        registration = db.scalar(
            select(Registration).where(
                Registration.match_id == match.id,
                Registration.player_id == pid,
                Registration.active.is_(True),
            )
        )
        payment = None
        if (
            match.status in ("open", "finalized", "approved")
            and registration
            and not registration.paid
        ):
            payment = InlineKeyboardButton(
                text="Оплачен" if registration.payment_reported else "Я оплатил",
                callback_data=(
                    f"paid:{match.id}:{registration.id}:{registration_stamp(registration)}"
                ),
            )
        return menu(match.id, registration_open=match.status == "open", payment=payment)

    async def update_menu(query, markup):
        if isinstance(query.message, Message):
            try:
                await query.message.edit_reply_markup(reply_markup=markup)
            except (TelegramBadRequest, TelegramForbiddenError):
                # A removed/unchanged message must not undo a successful registration or mark.
                pass

    async def identify(user):
        await check_member(cfg, user.id)

        def save():
            with factory() as db, db.begin():
                return player_for_telegram(db, user.id, user.first_name, user.username).id

        return await asyncio.to_thread(save)

    @router.message(Command("start", "admin"))
    async def start(message: Message):
        if not message.from_user:
            return
        try:
            await identify(message.from_user)

            def read_schedule():
                with factory() as db:
                    return schedule_description(db.get(GameTemplate, 1))

            description = await asyncio.to_thread(read_schedule)
            await message.answer(
                "ФКЖК · футбольное сообщество\n\n"
                f"{description}\nПриоритет — время записи среди оплативших.\n"
                "В приложении: alias, текущая игра, оценки игроков и подбор составов.\n\n"
                "/game — текущая игра\n/lastgame — результат последней игры\n"
                "/profile — моя статистика\n/help — команды бота",
                reply_markup=menu(),
            )
        except DomainError as exc:
            await message.answer(exc.message)

    @router.message(Command("help"))
    async def help_command(message: Message):
        if not message.from_user:
            return
        try:
            await identify(message.from_user)
            await message.answer(
                "/start — открыть клуб\n"
                "/game — ближайшая игра и запись\n"
                "/lastgame — последний результат, голы, ассисты и составы\n"
                "/profile — моя статистика\n"
                "/help — команды бота\n\n"
                "После перевода нажмите «Я оплатил» в /game. Оплату подтверждает администратор.",
                reply_markup=menu(),
                parse_mode=None,
            )
        except DomainError as exc:
            await message.answer(exc.message)

    @router.message(Command("game"))
    async def game(message: Message):
        if not message.from_user:
            return
        try:
            pid = await identify(message.from_user)

            def read_game():
                with factory() as db:
                    m = db.scalar(
                        select(Match)
                        .where(
                            Match.status.in_(["open", "finalized", "approved"]),
                            Match.starts_at > now(),
                        )
                        .order_by(Match.starts_at, Match.id)
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
                                    f"{r['queue']}. {r['alias']} · "
                                    + ("🟢 Оплачен" if r["payment_reported"] else "🔴 Не оплачен")
                                    + " · "
                                    + ("🟢 Подтверждено" if r["paid"] else "🔴 Не подтверждено")
                                    + f" · {date} · "
                                    + ("основной список" if r["in_main"] else "резерв")
                                )
                    return lines, game_menu(db, m, pid)

            result = await asyncio.to_thread(read_game)
            if result is None:
                await message.answer("Ближайшая игра еще не опубликована.", reply_markup=menu())
                return
            lines, markup = result
            parts = chunks("\n".join(lines), utf16=True)
            for i, part in enumerate(parts):
                await message.answer(
                    part,
                    reply_markup=markup if i == len(parts) - 1 else None,
                    parse_mode=None,
                )
        except DomainError as exc:
            await message.answer(exc.message)

    @router.message(Command("lastgame"))
    async def last_game(message: Message):
        if not message.from_user:
            return
        try:
            await identify(message.from_user)

            def read_result():
                with factory() as db:
                    m = db.scalar(
                        select(Match)
                        .join(MatchResult, MatchResult.match_id == Match.id)
                        .where(
                            Match.status == "completed",
                            MatchResult.completed.is_(True),
                            Match.starts_at <= now(),
                        )
                        .order_by(Match.starts_at.desc(), Match.id.desc())
                        .limit(1)
                    )
                    if not m:
                        return None
                    return m.id, result_text(m, result_data(db, m))

            result = await asyncio.to_thread(read_result)
            if result is None:
                await message.answer("Пока нет завершённых игр с результатом.", reply_markup=menu())
                return
            match_id, text = result
            parts = chunks(text, utf16=True)
            for i, part in enumerate(parts):
                await message.answer(
                    part,
                    reply_markup=menu(match_id) if i == len(parts) - 1 else None,
                    parse_mode=None,
                )
        except DomainError as exc:
            await message.answer(exc.message)

    @router.message(Command("profile"))
    async def profile(message: Message):
        if not message.from_user:
            return
        try:
            pid = await identify(message.from_user)

            def read_profile():
                season = str(now().astimezone(MOSCOW).year)
                with factory() as db:
                    return season, player_stats(db, pid), player_stats(db, pid, season=season)

            season, total, current = await asyncio.to_thread(read_profile)
            lines = [f"👤 {total['alias']}"]
            lines.append(
                f"Telegram: @{total['telegram_username']}"
                if total["telegram_username"]
                else f"Telegram ID: {total['telegram_id']}"
            )
            for title, stats in (("Общая статистика", total), (f"Сезон {season}", current)):
                lines.extend(
                    [
                        "",
                        title,
                        f"Игры: {stats['games']}",
                        f"Победы: {stats['wins']} · Ничьи: {stats['draws']} · Поражения: {stats['losses']}",
                        f"Голы: {stats['goals']} · Ассисты: {stats['assists']}",
                        f"Гол + пас: {stats['goals'] + stats['assists']}",
                    ]
                )
            await message.answer("\n".join(lines), reply_markup=menu(), parse_mode=None)
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
                    return game_menu(db, match, pid)

            markup = await asyncio.to_thread(save_join)
            await query.answer("Вы записаны. Оплату подтверждает администратор.", show_alert=True)
            await update_menu(query, markup)
        except (DomainError, ValueError) as exc:
            await query.answer(
                exc.message if isinstance(exc, DomainError) else "Неизвестная игра", show_alert=True
            )

    @router.callback_query(F.data.startswith("paid:"))
    async def paid(query: CallbackQuery):
        try:
            _, mid, rid, stamp = query.data.split(":")
            mid, rid = int(mid), int(rid)
            pid = await identify(query.from_user)

            def save_paid():
                with factory() as db, db.begin():
                    match = get_match(db, mid, lock=True)
                    if db.get(BotCallbackReceipt, query.id):
                        return "Уже обработано. Откройте /game для обновления.", game_menu(
                            db, match, pid
                        )
                    registration = db.get(Registration, rid)
                    if (
                        not registration
                        or registration.match_id != mid
                        or registration.player_id != pid
                        or not registration.active
                        or registration_stamp(registration) != stamp
                    ):
                        raise DomainError(
                            "Кнопка устарела или принадлежит другому игроку. Откройте /game заново."
                        )
                    if match.status not in ("open", "finalized", "approved"):
                        raise DomainError("Отметка оплаты недоступна для этой игры.")
                    if registration.paid:
                        text = "Оплата уже подтверждена администратором."
                    else:
                        report_payment(db, pid, match, registration, True)
                        text = "Вы сообщили об оплате. Администратор проверит и подтвердит перевод."
                    db.add(BotCallbackReceipt(id=query.id, player_id=pid, match_id=mid))
                    return text, game_menu(db, match, pid)

            text, markup = await asyncio.to_thread(save_paid)
            await query.answer(text, show_alert=True)
            await update_menu(query, markup)
        except (DomainError, ValueError) as exc:
            await query.answer(
                exc.message if isinstance(exc, DomainError) else "Неизвестная игра", show_alert=True
            )

    @router.callback_query(F.data.startswith("leave:"))
    async def leave(query: CallbackQuery):
        try:
            _, mid = query.data.split(":")
            pid = await identify(query.from_user)

            def save_leave():
                with factory() as db, db.begin():
                    match = get_match(db, int(mid), lock=True)
                    if db.get(BotCallbackReceipt, query.id):
                        return
                    registration = db.scalar(
                        select(Registration).where(
                            Registration.match_id == match.id,
                            Registration.player_id == pid,
                        )
                    )
                    if registration:
                        cancel(db, pid, match, registration)
                    db.add(BotCallbackReceipt(id=query.id, player_id=pid, match_id=match.id))

            await asyncio.to_thread(save_leave)
            await query.answer("Вы не записаны на эту игру.", show_alert=True)
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
                BotCommand(command="lastgame", description="Последний результат, голы и составы"),
                BotCommand(command="profile", description="Профиль и статистика"),
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
