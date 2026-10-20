from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramMigrateToChat
from aiogram.methods import GetChatMember, SendMessage, SetMyCommands
from sqlalchemy import func, select

from fczhk.auth import check_member
from fczhk.bot import configure_bot, handle_update
from fczhk.models import GameTemplate, Match, MatchResult, Player, ResultGoal, ResultParticipant
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


async def test_configured_commands_exclude_players_and_include_profile(env, monkeypatch):
    cfg = env[0]
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sender)
    await configure_bot(cfg)
    commands = next(
        call.args[0] for call in sender.await_args_list if isinstance(call.args[0], SetMyCommands)
    )
    assert [c.command for c in commands.commands] == ["start", "game", "profile", "help"]


@pytest.mark.parametrize("enabled", [True, False])
async def test_help_uses_saved_schedule_instead_of_fixed_days(env, monkeypatch, enabled):
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
                "text": "/help",
                "entities": [{"offset": 0, "length": 5, "type": "bot_command"}],
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


async def test_bot_cancel_button_removes_own_registration_once(env, call, game, monkeypatch):
    cfg, factory, *_ = env
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    with factory() as db, db.begin():
        db.get(GameTemplate, 1).extended_chat_id = "-1002222222"
    call("POST", f"/matches/{game['id']}/join", {"position": "keeper"}, role="player")
    update = {
        "update_id": 125,
        "callback_query": {
            "id": "cancel-once",
            "from": {"id": 102, "is_bot": False, "first_name": "Игрок"},
            "chat_instance": "abc",
            "inline_message_id": "inline",
            "data": f"leave:{game['id']}",
        },
    }
    await handle_update(cfg, factory, update)
    assert call("GET", f"/matches/{game['id']}")["registrations"] == []
    call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    await handle_update(cfg, factory, update)
    assert len(call("GET", f"/matches/{game['id']}")["registrations"]) == 1
    from sqlalchemy import select

    from fczhk.models import Publication

    with factory() as db:
        assert (
            len(list(db.scalars(select(Publication).where(Publication.kind == "withdrawal")))) == 1
        )


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
