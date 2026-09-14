from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot

from fczhk.auth import check_member
from fczhk.bot import handle_update
from fczhk.services import DomainError


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
