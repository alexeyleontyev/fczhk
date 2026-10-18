from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramMigrateToChat
from aiogram.methods import GetChatMember, SendMessage

from fczhk.auth import check_member
from fczhk.bot import handle_update
from fczhk.models import GameTemplate
from fczhk.services import DomainError


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
