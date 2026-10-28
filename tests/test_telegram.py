from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramMigrateToChat
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    GetChatMember,
    SendMessage,
    SetMyCommands,
)
from sqlalchemy import func, select

from fczhk.auth import check_member
from fczhk.bot import configure_bot, handle_update
from fczhk.models import (
    GameTemplate,
    Match,
    MatchResult,
    Player,
    Registration,
    ResultGoal,
    ResultParticipant,
)
from fczhk.services import MOSCOW, DomainError


async def command_replies(env, monkeypatch, command, user_id=102, username=None):
    cfg, factory, *_ = env
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sender)
    await handle_update(
        cfg,
        factory,
        {
            "update_id": 126,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": user_id, "type": "private"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Имя из Telegram",
                    "username": username,
                },
                "text": command,
                "entities": [{"offset": 0, "length": len(command), "type": "bot_command"}],
            },
        },
    )
    return [
        call.args[0] for call in sender.await_args_list if isinstance(call.args[0], SendMessage)
    ]


async def callback_replies(env, monkeypatch, data, *, user_id=102, callback_id=None):
    cfg, factory, *_ = env
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sender)
    await handle_update(
        cfg,
        factory,
        {
            "update_id": 127,
            "callback_query": {
                "id": callback_id or str(uuid4()),
                "from": {"id": user_id, "is_bot": False, "first_name": "Игрок"},
                "chat_instance": "abc",
                "message": {
                    "message_id": 1,
                    "date": 1700000000,
                    "chat": {"id": user_id, "type": "private"},
                    "text": "Игра",
                },
                "data": data,
            },
        },
    )
    return [call.args[0] for call in sender.await_args_list]


def payment_button(markup):
    return next(
        b
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data and b.callback_data.startswith("paid:")
    )


def future_game(call, days=2):
    from fczhk.db import now

    game = call(
        "POST",
        "/matches",
        {"starts_at": (now() + timedelta(days=days)).isoformat(), "location": "Поле оплаты"},
        expected=201,
    )
    return call("POST", f"/matches/{game['id']}/actions/open", {"version": game["version"]})


async def test_profile_shows_linked_all_time_and_current_season_statistics(env, call, monkeypatch):
    monkeypatch.setattr("fczhk.bot.now", lambda: datetime(2026, 10, 20, 12, tzinfo=UTC))
    factory, ids = env[1], env[4]
    guest = call("POST", "/players/guests", {"alias": "Игрок из истории"}, expected=201)
    with factory() as db, db.begin():
        for day, season, team, events in [
            (
                "2025-01-24",
                "2024-2025",
                "white",
                [
                    ("white", guest["id"], None),
                    ("white", None, guest["id"]),
                    ("black", ids["admin"], None),
                ],
            ),
            ("2025-01-31", "2024-2025", "white", []),
            ("2026-06-05", "2026", "black", [("white", ids["admin"], None)]),
        ]:
            match = Match(
                game_day=day,
                season=season,
                starts_at=datetime.fromisoformat(day).replace(tzinfo=MOSCOW),
                location="Поле",
                status="completed",
            )
            db.add(match)
            db.flush()
            db.add(MatchResult(match_id=match.id, completed=True))
            db.flush()
            db.add_all(
                [
                    ResultParticipant(
                        match_id=match.id, player_id=guest["id"], team=team, position="field"
                    ),
                    ResultParticipant(
                        match_id=match.id,
                        player_id=ids["admin"],
                        team="black" if team == "white" else "white",
                        position="field",
                    ),
                ]
            )
            db.add_all(
                [
                    ResultGoal(
                        id=str(uuid4()),
                        match_id=match.id,
                        team=side,
                        kind="goal",
                        author_id=author,
                        assist_id=assist,
                    )
                    for side, author, assist in events
                ]
            )
    call("POST", f"/players/{guest['id']}/link", {"target_id": ids["player"]})
    replies = await command_replies(env, monkeypatch, "/profile")
    assert len(replies) == 1
    message = replies[0]
    assert message.text.startswith("👤 Игрок из истории\nTelegram ID: 102\n\nОбщая статистика\n")
    total, current = message.text.split("\n\nСезон 2026\n")
    assert "Игры: 3\nПобеды: 1 · Ничьи: 1 · Поражения: 1" in total
    assert "Голы: 1 · Ассисты: 1\nГол + пас: 2" in total
    assert (
        current
        == "Игры: 1\nПобеды: 0 · Ничьи: 0 · Поражения: 1\nГолы: 0 · Ассисты: 0\nГол + пас: 0"
    )
    assert message.reply_markup.inline_keyboard[0][0].text == "⚽ Открыть приложение"
    assert message.parse_mode is None


@pytest.mark.parametrize(
    "at,season",
    [
        (datetime(2026, 10, 20, tzinfo=UTC), "2026"),
        (datetime(2026, 12, 31, 22, tzinfo=UTC), "2027"),
    ],
)
async def test_empty_profile_and_moscow_season_boundary(env, monkeypatch, at, season):
    monkeypatch.setattr("fczhk.bot.now", lambda: at)
    replies = await command_replies(env, monkeypatch, "/profile")
    assert len(replies) == 1
    assert "Общая статистика" in replies[0].text and f"Сезон {season}" in replies[0].text
    assert replies[0].text.count("Игры: 0") == 2
    assert replies[0].text.count("Голы: 0 · Ассисты: 0") == 2


async def test_profile_checks_membership_before_reading_or_creating_account(env, monkeypatch):
    checker = AsyncMock(side_effect=DomainError("Нет доступа к сообществу", 403))
    monkeypatch.setattr("fczhk.bot.check_member", checker)
    replies = await command_replies(env, monkeypatch, "/profile", user_id=999)
    assert [m.text for m in replies] == ["Нет доступа к сообществу"]
    checker.assert_awaited_once_with(env[0], 999)
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Player)) == 2


async def test_players_command_is_removed(env, monkeypatch):
    assert await command_replies(env, monkeypatch, "/players", user_id=999) == []
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Player)) == 2


async def test_bot_profile_refreshes_username_and_falls_back_to_id(env, monkeypatch):
    for username in ("test_username", "changed_username", None):
        replies = await command_replies(env, monkeypatch, "/profile", username=username)
        text = replies[0].text
        assert text.startswith("👤 Игрок\n")
        if username:
            assert f"Telegram: @{username}\n" in text and "Telegram ID:" not in text
        else:
            assert "Telegram ID: 102\n" in text and "@" not in text
        with env[1]() as db:
            assert db.get(Player, env[4]["player"]).telegram_username == username


async def test_configured_commands_include_lastgame_and_exclude_paid(env, monkeypatch):
    cfg = env[0]
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sender)
    await configure_bot(cfg)
    commands = next(
        call.args[0] for call in sender.await_args_list if isinstance(call.args[0], SetMyCommands)
    )
    assert [c.command for c in commands.commands] == [
        "start",
        "game",
        "lastgame",
        "profile",
        "help",
    ]


@pytest.mark.parametrize("enabled", [True, False])
async def test_start_uses_saved_schedule_instead_of_fixed_days(env, monkeypatch, enabled):
    cfg, factory, *_ = env
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    with factory() as db, db.begin():
        template = db.get(GameTemplate, 1)
        template.enabled = enabled
        template.opening_weekday, template.opening_time = 6, "23:45"
        template.game_weekday, template.start_time = 0, "00:15"
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sender)
    await handle_update(
        cfg,
        factory,
        {
            "update_id": 124,
            "message": {
                "message_id": 1,
                "date": 1700000000,
                "chat": {"id": 102, "type": "private"},
                "from": {"id": 102, "is_bot": False, "first_name": "Игрок"},
                "text": "/start",
                "entities": [{"offset": 0, "length": 6, "type": "bot_command"}],
            },
        },
    )
    message = next(
        call.args[0] for call in sender.await_args_list if isinstance(call.args[0], SendMessage)
    )
    assert "Игра: понедельник, 00:15 МСК" in message.text
    assert "вторник" not in message.text
    assert "/profile — моя статистика" in message.text and "/players" not in message.text
    assert (
        "Сбор: воскресенье, 23:45 МСК" if enabled else "Автоматическое открытие сбора выключено"
    ) in message.text


async def test_help_is_a_short_command_guide_and_paid_command_is_removed(env, monkeypatch):
    replies = await command_replies(env, monkeypatch, "/help")
    text = replies[0].text
    assert len(text) < 500
    assert all(f"/{name} —" in text for name in ("start", "game", "lastgame", "profile", "help"))
    assert "«Я оплатил» в /game" in text and "администратор" in text
    assert "/paid" not in text
    assert await command_replies(env, monkeypatch, "/paid") == []


async def test_game_payment_button_is_own_and_bound_to_the_shown_match(env, call, monkeypatch):
    game = future_game(call, days=3)
    path = f"/matches/{game['id']}"
    call("POST", path + "/join", {"position": "field"}, role="player")
    replies = await command_replies(env, monkeypatch, "/game")
    button = payment_button(replies[-1].reply_markup)
    assert button.text == "Я оплатил"
    assert len(button.callback_data.encode()) <= 64
    assert "Игрок · 🔴🔴 · " in replies[0].text
    earlier = future_game(call, days=1)
    call("POST", f"/matches/{earlier['id']}/join", {"position": "keeper"}, role="player")
    result = await callback_replies(env, monkeypatch, button.callback_data)
    assert "Администратор проверит" in next(
        r.text for r in result if isinstance(r, AnswerCallbackQuery)
    )
    updated = next(r for r in result if isinstance(r, EditMessageReplyMarkup))
    assert payment_button(updated.reply_markup).text == "Оплачен"
    assert call("GET", path)["registrations"][0]["payment_reported"]
    assert not call("GET", f"/matches/{earlier['id']}")["registrations"][0]["payment_reported"]


async def test_payment_button_rejects_other_players_and_stale_enrollment(env, call, monkeypatch):
    game = future_game(call)
    path = f"/matches/{game['id']}"
    call("POST", path + "/join", {"position": "field"}, role="player")
    replies = await command_replies(env, monkeypatch, "/game")
    data = payment_button(replies[-1].reply_markup).callback_data
    for user_id, payload in [(101, data), (102, "paid:invalid")]:
        await callback_replies(env, monkeypatch, payload, user_id=user_id)
        assert not call("GET", path)["registrations"][0]["payment_reported"]
    await callback_replies(env, monkeypatch, data, callback_id="payment-once")
    call("DELETE", path + "/join", role="player")
    await callback_replies(env, monkeypatch, data)
    assert call("GET", path)["registrations"] == []
    rejoined = call("POST", path + "/join", {"position": "field"}, role="player")
    for callback_id in ("payment-once", "old-button-new-click"):
        await callback_replies(env, monkeypatch, data, callback_id=callback_id)
        after = call("GET", path)
        assert after["version"] == rejoined["version"]
        assert not after["registrations"][0]["payment_reported"]


async def test_game_button_after_join_and_after_admin_confirmation(env, call, monkeypatch):
    game = future_game(call)
    path = f"/matches/{game['id']}"
    before = (await command_replies(env, monkeypatch, "/game"))[-1].reply_markup
    assert not any(
        b.callback_data.startswith("paid:")
        for row in before.inline_keyboard
        for b in row
        if b.callback_data
    )
    joined = await callback_replies(env, monkeypatch, f"join:{game['id']}:field")
    markup = next(r.reply_markup for r in joined if isinstance(r, EditMessageReplyMarkup))
    data = payment_button(markup).callback_data
    current = call("GET", path)
    rid = current["registrations"][0]["id"]
    current = call(
        "PUT", path + f"/registrations/{rid}/payment", {"version": current["version"], "paid": True}
    )
    await callback_replies(env, monkeypatch, data)
    assert call("GET", path)["version"] == current["version"]
    assert not call("GET", path)["registrations"][0]["payment_reported"]
    replies = await command_replies(env, monkeypatch, "/game")
    assert "Игрок · 🔴🟢 · " in replies[0].text
    assert not any(
        b.callback_data.startswith("paid:")
        for row in replies[-1].reply_markup.inline_keyboard
        for b in row
        if b.callback_data
    )


async def test_game_tracks_current_roster_from_open_collection_to_approved_teams(
    env, call, monkeypatch
):
    game = future_game(call)
    path = f"/matches/{game['id']}"
    registered_at = datetime(2026, 10, 20, 12, tzinfo=UTC)
    with env[1]() as db, db.begin():
        match = db.get(Match, game["id"])
        match.field_limit, match.keeper_limit = 2, 1
        for i, (alias, position, paid) in enumerate(
            [
                ("Ранний полевой", "field", False),
                ("Оплативший полевой", "field", True),
                ("Резервный полевой", "field", True),
                ("Ранний вратарь", "keeper", False),
                ("Оплативший вратарь", "keeper", True),
            ]
        ):
            player = Player(alias=alias)
            db.add(player)
            db.flush()
            db.add(
                Registration(
                    match_id=match.id,
                    player_id=player.id,
                    position=position,
                    registered_at=registered_at + timedelta(seconds=i),
                    paid=paid,
                    payment_reported=paid,
                )
            )

    async def reply():
        return "\n".join(r.text for r in await command_replies(env, monkeypatch, "/game"))

    text = await reply()
    assert "Запись открыта" in text
    main, reserve = text.split("\nРезерв\n")
    assert "1. Ранний полевой · 🔴🔴 · 20.10 15:00:00" in main
    assert "2. Оплативший полевой · 🟢🟢" in main
    assert "1. Ранний вратарь · 🔴🔴" in main
    assert "Полевые\n3. Резервный полевой · 🟢🟢" in reserve
    assert "Вратари\n2. Оплативший вратарь · 🟢🟢" in reserve
    assert not any(
        label in text for label in ("Оплачен", "Не оплачен", "Подтверждено", "основной список")
    )

    game = call("POST", path + "/actions/finalize", {"version": game["version"]})
    text = await reply()
    assert "Сбор завершён" in text and "Запись открыта" not in text
    main, reserve = text.split("\nРезерв\n")
    assert "Оплативший полевой" in main and "Резервный полевой" in main
    assert "Оплативший вратарь" in main
    assert "Ранний полевой" not in main and "Ранний вратарь" not in main
    assert "Ранний полевой" in reserve and "Ранний вратарь" in reserve

    assignments = {
        str(r["id"]): "black" if r["alias"] == "Резервный полевой" else "white"
        for r in game["registrations"]
        if r["selected"]
    }
    game = call("PUT", path + "/teams", {"version": game["version"], "assignments": assignments})
    game = call("POST", path + "/actions/approve", {"version": game["version"]})
    text = await reply()
    assert "Составы утверждены" in text and "Сбор завершён" not in text
    white, black = text.split("⚪ Белые\n")[1].split("\n\n⚫ Чёрные\n")
    assert white == "1. 🧤 Оплативший вратарь · 🟢🟢\n2. Оплативший полевой · 🟢🟢"
    assert black == "1. Резервный полевой · 🟢🟢"
    assert "Ранний" not in text and "\nРезерв\n" not in text and "20.10 15:00:" not in text
    markup = (await command_replies(env, monkeypatch, "/game"))[-1].reply_markup
    assert not any(
        b.callback_data.startswith(("join:", "leave:"))
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data
    )

    game = call("POST", path + "/teams/swap-colors", {"version": game["version"]})
    text = await reply()
    white, black = text.split("⚪ Белые\n")[1].split("\n\n⚫ Чёрные\n")
    assert white == "1. Резервный полевой · 🟢🟢"
    assert black == "1. 🧤 Оплативший вратарь · 🟢🟢\n2. Оплативший полевой · 🟢🟢"

    # Editing an approved lineup revokes approval until the teams are confirmed again.
    call(
        "PUT",
        path + "/teams",
        {"version": game["version"], "assignments": dict.fromkeys(assignments)},
    )
    text = await reply()
    assert "Сбор завершён" in text and "Составы утверждены" not in text
    assert "⚪ Белые" not in text and "⚫ Чёрные" not in text
    assert "\nРезерв\n" in text


async def test_lastgame_without_results(env, monkeypatch):
    replies = await command_replies(env, monkeypatch, "/lastgame")
    assert [r.text for r in replies] == ["Пока нет завершённых игр с результатом."]


async def test_lastgame_uses_latest_finished_actual_roster_and_current_goals(env, monkeypatch):
    factory, ids = env[1], env[4]
    monkeypatch.setattr("fczhk.bot.now", lambda: datetime(2026, 10, 20, 12, tzinfo=UTC))
    with factory() as db, db.begin():
        for day, status, completed in [
            (1, "completed", True),
            (2, "completed", True),
            (3, "approved", False),
            (4, "cancelled", True),
            (5, "draft", False),
            (6, "completed", False),
            (25, "completed", True),
        ]:
            match = Match(
                game_day=f"2026-10-{day:02d}",
                starts_at=datetime(2026, 10, day, 17, tzinfo=UTC),
                location=f"Поле {day}",
                status=status,
            )
            db.add(match)
            db.flush()
            db.add(MatchResult(match_id=match.id, completed=completed))
            db.flush()
            if day != 2:
                continue
            mid = match.id
            db.add_all(
                [
                    ResultParticipant(
                        match_id=mid, player_id=ids["player"], team="white", position="field"
                    ),
                    ResultParticipant(
                        match_id=mid, player_id=ids["admin"], team="white", position="keeper"
                    ),
                ]
            )
            opponent = Player(alias="Соперник")
            db.add(opponent)
            db.flush()
            db.add(
                ResultParticipant(
                    match_id=mid, player_id=opponent.id, team="black", position="field"
                )
            )
            db.add_all(
                [
                    ResultGoal(
                        id="goal",
                        match_id=mid,
                        team="white",
                        kind="goal",
                        author_id=ids["player"],
                        assist_id=ids["admin"],
                    ),
                    ResultGoal(
                        id="own", match_id=mid, team="white", kind="own_goal", author_id=opponent.id
                    ),
                ]
            )
    replies = await command_replies(env, monkeypatch, "/lastgame")
    text = replies[0].text
    assert "02.10.2026 · 20:00 МСК" in text and "Поле 2" in text
    assert "Белые 2 : 0 Чёрные" in text
    assert "🧤 Администратор\nИгрок\nГолы и передачи:" in text
    assert "⚽ Игрок · передача: Администратор" in text
    assert "Автогол — Соперник" in text
    assert "⚫ Чёрные\nСоперник\nГолы и передачи:\nГолов нет" in text
    assert replies[-1].reply_markup and replies[0].parse_mode is None
    with factory() as db, db.begin():
        db.get(ResultGoal, (mid, "goal")).team = "black"
    updated = await command_replies(env, monkeypatch, "/lastgame")
    assert "Белые 1 : 1 Чёрные" in updated[0].text


@pytest.mark.parametrize("command", ["/game", "/lastgame", "/help"])
async def test_game_commands_require_membership(env, monkeypatch, command):
    checker = AsyncMock(side_effect=DomainError("Нет доступа к сообществу", 403))
    monkeypatch.setattr("fczhk.bot.check_member", checker)
    replies = await command_replies(env, monkeypatch, command, user_id=999)
    assert [r.text for r in replies] == ["Нет доступа к сообществу"]


async def test_duplicate_telegram_callback_cannot_rejoin_after_later_cancel(
    env, call, game, monkeypatch
):
    cfg, _, _, _, _ = env
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    update = {
        "update_id": 123,
        "callback_query": {
            "id": "callback-once",
            "from": {"id": 102, "is_bot": False, "first_name": "Игрок"},
            "chat_instance": "abc",
            "inline_message_id": "inline",
            "data": f"join:{game['id']}:field",
        },
    }
    await handle_update(cfg, env[1], update)
    assert len(call("GET", f"/matches/{game['id']}")["registrations"]) == 1
    call("DELETE", f"/matches/{game['id']}/join", role="player")
    await handle_update(cfg, env[1], update)
    assert call("GET", f"/matches/{game['id']}")["registrations"] == []


def confirmation_buttons(replies):
    question = next(
        r
        for r in replies
        if isinstance(r, SendMessage)
        and r.reply_markup
        and any(
            b.callback_data and b.callback_data.startswith("reg:")
            for row in r.reply_markup.inline_keyboard
            for b in row
        )
    )
    buttons = {
        b.callback_data.split(":")[3]: b.callback_data
        for row in question.reply_markup.inline_keyboard
        for b in row
    }
    assert all(len(value.encode()) <= 64 for value in buttons.values())
    return question, buttons


def registration_state(env, game_id):
    from fczhk.models import Registration

    with env[1]() as db:
        r = db.scalar(
            select(Registration).where(
                Registration.match_id == game_id, Registration.player_id == env[4]["player"]
            )
        )
        return {c.key: getattr(r, c.key) for c in Registration.__table__.columns}


async def test_bot_cancel_button_removes_own_registration_once(env, call, game, monkeypatch):
    with env[1]() as db, db.begin():
        db.get(GameTemplate, 1).extended_chat_id = "-1002222222"
    m = call("POST", f"/matches/{game['id']}/join", {"position": "keeper"}, role="player")
    m = call(
        "PUT",
        f"/matches/{m['id']}/registrations/{m['registrations'][0]['id']}/payment",
        {"version": m["version"], "paid": True, "reported": True},
    )
    original = registration_state(env, m["id"])
    replies = await callback_replies(
        env, monkeypatch, f"leave:{m['id']}", callback_id="cancel-once"
    )
    question, buttons = confirmation_buttons(replies)
    assert "обе отметки оплаты сброшены" in question.text
    assert registration_state(env, m["id"]) == original
    for _ in range(2):
        await callback_replies(env, monkeypatch, buttons["l"], callback_id="confirm-cancel-once")
    assert call("GET", f"/matches/{m['id']}")["registrations"] == []
    cancelled = registration_state(env, m["id"])
    assert not cancelled["paid"] and not cancelled["payment_reported"]
    assert cancelled["paid_at"] is None and cancelled["payment_reported_at"] is None
    call("POST", f"/matches/{m['id']}/join", {"position": "field"}, role="player")
    rejoined = registration_state(env, m["id"])
    await callback_replies(env, monkeypatch, buttons["l"])
    await callback_replies(env, monkeypatch, f"leave:{m['id']}", callback_id="cancel-once")
    assert registration_state(env, m["id"]) == rejoined
    from fczhk.models import Publication

    with env[1]() as db:
        assert (
            len(list(db.scalars(select(Publication).where(Publication.kind == "withdrawal")))) == 1
        )


@pytest.mark.parametrize("position,action", [("field", "k"), ("keeper", "f")])
async def test_bot_role_confirmation_no_preserves_queue_and_yes_preserves_payments(
    env, call, game, monkeypatch, position, action
):
    target = "keeper" if position == "field" else "field"
    m = call("POST", f"/matches/{game['id']}/join", {"position": position}, role="player")
    m = call(
        "PUT",
        f"/matches/{m['id']}/registrations/{m['registrations'][0]['id']}/payment",
        {"version": m["version"], "paid": True, "reported": True},
    )
    original = registration_state(env, m["id"])
    question, buttons = confirmation_buttons(
        await callback_replies(env, monkeypatch, f"join:{m['id']}:{target}")
    )
    assert "Вы точно хотите сменить амплуа" in question.text
    assert registration_state(env, m["id"]) == original
    await callback_replies(env, monkeypatch, buttons["n"])
    await callback_replies(env, monkeypatch, buttons[action])
    assert registration_state(env, m["id"]) == original
    _, buttons = confirmation_buttons(
        await callback_replies(env, monkeypatch, f"join:{m['id']}:{target}")
    )
    await callback_replies(env, monkeypatch, buttons[action])
    changed = registration_state(env, m["id"])
    assert changed["position"] == target and changed["registered_at"] > original["registered_at"]
    assert {k: v for k, v in changed.items() if k not in ("position", "registered_at")} == {
        k: v for k, v in original.items() if k not in ("position", "registered_at")
    }
    version = call("GET", f"/matches/{m['id']}")["version"]
    await callback_replies(env, monkeypatch, buttons[action])
    assert registration_state(env, m["id"]) == changed
    assert call("GET", f"/matches/{m['id']}")["version"] == version


@pytest.mark.parametrize(
    "case", ["other_player", "tampered", "expired", "rejoined", "role_changed", "finalized"]
)
async def test_bot_confirmation_rejects_foreign_forged_and_stale_questions(
    env, call, game, monkeypatch, case
):
    from fczhk.db import now

    m = call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    _, buttons = confirmation_buttons(
        await callback_replies(env, monkeypatch, f"join:{m['id']}:keeper")
    )
    data = buttons["k"]
    if case == "tampered":
        data = data.replace(":k:", ":l:")
    elif case == "expired":
        later = now() + timedelta(minutes=6)
        monkeypatch.setattr("fczhk.bot.now", lambda: later)
    elif case == "rejoined":
        call("DELETE", f"/matches/{m['id']}/join", role="player")
        call("POST", f"/matches/{m['id']}/join", {"position": "field"}, role="player")
    elif case == "role_changed":
        call("POST", f"/matches/{m['id']}/join", {"position": "keeper"}, role="player")
    elif case == "finalized":
        m = call("GET", f"/matches/{m['id']}")
        call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    original = registration_state(env, m["id"])
    version = call("GET", f"/matches/{m['id']}")["version"]
    result = await callback_replies(
        env, monkeypatch, data, user_id=101 if case == "other_player" else 102
    )
    assert any(isinstance(r, AnswerCallbackQuery) and r.show_alert for r in result)
    assert registration_state(env, m["id"]) == original
    assert call("GET", f"/matches/{m['id']}")["version"] == version


async def test_membership_fails_closed_for_left_or_unavailable(env, monkeypatch):
    cfg = env[0]
    cfg.env = "production"

    class FakeBot:
        result = "left"

        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_chat_member(self, *args):
            if self.result == "error":
                raise ConnectionError("unavailable")
            return SimpleNamespace(status=self.result, is_member=False)

    monkeypatch.setattr("fczhk.auth.Bot", FakeBot)
    with pytest.raises(DomainError) as exc:
        await check_member(cfg, 102)
    assert exc.value.status == 403
    FakeBot.result = "error"
    with pytest.raises(DomainError) as exc:
        await check_member(cfg, 102)
    assert exc.value.status == 503
    FakeBot.result = "member"
    await check_member(cfg, 102)


@pytest.mark.parametrize("status,expected", [("member", None), ("left", 403), ("error", 503)])
async def test_membership_retries_migrated_group_without_bypassing_access(
    env, monkeypatch, status, expected
):
    cfg = env[0]
    cfg.env = "production"
    cfg.community_chat_id = "-1234"
    calls = []

    class FakeBot:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_chat_member(self, chat, user):
            calls.append((chat, user))
            if chat == "-1234":
                raise TelegramMigrateToChat(
                    method=GetChatMember(chat_id=chat, user_id=user),
                    message="Group upgraded",
                    migrate_to_chat_id=-1005678,
                )
            if status == "error":
                raise ConnectionError("unavailable")
            return SimpleNamespace(status=status, is_member=False)

    monkeypatch.setattr("fczhk.auth.Bot", FakeBot)
    if expected:
        with pytest.raises(DomainError) as error:
            await check_member(cfg, 102)
        assert error.value.status == expected
    else:
        await check_member(cfg, 102)
    assert calls == [("-1234", 102), (-1005678, 102)]
