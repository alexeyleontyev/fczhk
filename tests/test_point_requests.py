import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from sqlalchemy import select

from fczhk.models import Player, PointRequest, Publication
from fczhk.worker import points_markup
from tests.test_telegram import callback_replies


def _admin_messages(factory):
    with factory() as db:
        return list(db.scalars(select(Publication).where(Publication.kind == "points_request")))


def test_player_requests_points_and_administrators_are_asked(env, call):
    cfg, factory, _, _, ids = env
    wallet = call("POST", "/wallet/requests", dict(amount=100), role="player", expected=201)
    assert wallet["request"]["status"] == "pending" and wallet["request"]["amount"] == 100
    assert wallet["balance"] == 0  # nothing until an administrator decides
    again = call("POST", "/wallet/requests", dict(amount=50), role="player", expected=409)
    assert "уже отправлен" in again["detail"]
    messages = _admin_messages(factory)
    assert [m.chat_id for m in messages] == ["101"]  # the one administrator, by Telegram ID
    assert "Игрок просит 100 очков" in messages[0].text
    markup = points_markup(cfg, "points_request", messages[0].dedupe_key)
    request_id = wallet["request"]["id"]
    assert [b.callback_data for b in markup.inline_keyboard[0]] == [
        f"pts:{request_id}:a",
        f"pts:{request_id}:d",
    ]
    queue = call("GET", "/wallet/requests")
    assert queue[0]["alias"] == "Игрок" and queue[0]["amount"] == 100
    call("GET", "/wallet/requests", role="player", expected=403)
    call("POST", "/wallet/requests", dict(amount=5000), role="player", expected=422)


def test_approval_grants_the_points_and_tells_the_player(env, call):
    _, factory, _, _, ids = env
    request_id = call("POST", "/wallet/requests", dict(amount=100), role="player", expected=201)[
        "request"
    ]["id"]
    assert call("POST", f"/wallet/requests/{request_id}/decision", dict(approve=True)) == []
    wallet = call("GET", "/wallet", role="player")
    assert wallet["balance"] == 100 and wallet["grants"] == 100 and wallet["profit"] == 0
    assert (
        wallet["entries"][0]["kind"] == "grant"
        and wallet["entries"][0]["note"] == "По запросу игрока"
    )
    assert wallet["request"]["status"] == "approved"
    late = call(
        "POST", f"/wallet/requests/{request_id}/decision", dict(approve=False), expected=409
    )
    assert "уже одобрен" in late["detail"]
    with factory() as db:
        told = db.scalar(select(Publication).where(Publication.kind == "points_decided"))
        assert told.chat_id == "102" and "Начислено 100" in told.text
    # one request a week: the next one waits for Monday
    again = call("POST", "/wallet/requests", dict(amount=30), role="player", expected=409)
    assert "раз в неделю" in again["detail"]
    assert call("GET", "/wallet", role="player")["balance"] == 100


def test_a_player_can_cancel_and_an_administrator_cannot_approve_his_own(env, call):
    call("POST", "/wallet/requests/cancel", role="player", expected=404)
    call("POST", "/wallet/requests", dict(amount=10), role="player", expected=201)
    assert (
        call("POST", "/wallet/requests/cancel", role="player")["request"]["status"] == "cancelled"
    )
    own = call("POST", "/wallet/requests", dict(amount=10), expected=201)["request"]["id"]
    assert (
        "другой администратор"
        in call("POST", f"/wallet/requests/{own}/decision", dict(approve=True), expected=422)[
            "detail"
        ]
    )


async def test_bot_buttons_approve_a_request(env, call, monkeypatch):
    _, factory, _, _, ids = env
    request_id = call("POST", "/wallet/requests", dict(amount=40), role="player", expected=201)[
        "request"
    ]["id"]
    # a player pressing the button (e.g. a forwarded message) is refused
    replies = await callback_replies(env, monkeypatch, f"pts:{request_id}:a", user_id=102)
    answer = next(r for r in replies if isinstance(r, AnswerCallbackQuery))
    assert "администратор" in answer.text
    replies = await callback_replies(env, monkeypatch, f"pts:{request_id}:a", user_id=101)
    answer = next(r for r in replies if isinstance(r, AnswerCallbackQuery))
    assert answer.text == "Одобрено: +40 очков — Игрок"
    edited = next(r for r in replies if isinstance(r, EditMessageText))
    assert edited.reply_markup is None and edited.text.endswith("Одобрено: +40 очков — Игрок")
    assert call("GET", "/wallet", role="player")["balance"] == 40
    replies = await callback_replies(env, monkeypatch, f"pts:{request_id}:d", user_id=101)
    assert "уже одобрен" in next(r for r in replies if isinstance(r, AnswerCallbackQuery)).text
    with factory() as db:
        assert db.get(PointRequest, request_id).decided_by == ids["admin"]
        assert db.get(Player, ids["player"]).alias == "Игрок"


@pytest.mark.parametrize("data", ["pts:1:x", "pts:abc:a"])
async def test_bot_rejects_malformed_point_buttons(env, monkeypatch, data):
    replies = await callback_replies(env, monkeypatch, data, user_id=101)
    assert (
        "Неизвестный запрос" in next(r for r in replies if isinstance(r, AnswerCallbackQuery)).text
    )


def test_points_can_be_requested_once_a_moscow_week(env, call):
    from datetime import datetime

    from fczhk import wallet
    from fczhk.scheduling import MOSCOW

    cfg, factory, _, _, ids = env
    pid = ids["player"]
    sunday = datetime(2026, 11, 15, 23, 0, tzinfo=MOSCOW)
    monday = datetime(2026, 11, 16, 0, 5, tzinfo=MOSCOW)
    with factory() as db, db.begin():
        first = wallet.request_points(
            db, pid, 100, cfg, at=datetime(2026, 11, 10, 12, tzinfo=MOSCOW)
        )
        wallet.decide_request(db, ids["admin"], first.id, approve=False)
        # declined still counts for the week
        with pytest.raises(wallet.DomainError, match="раз в неделю"):
            wallet.request_points(db, pid, 50, cfg, at=sunday)
        view = wallet.wallet_data(db, pid, at=sunday)
        assert view["request_available"] is False and view["next_request_at"] == monday.replace(
            minute=0
        )
        # a new week, a new request; a cancelled one does not use up the week
        second = wallet.request_points(db, pid, 50, cfg, at=monday)
        second.status = "cancelled"
        db.flush()
        assert wallet.wallet_data(db, pid, at=monday)["request_available"] is True
        wallet.request_points(db, pid, 50, cfg, at=monday)
    late = call("POST", "/wallet/requests", dict(amount=10), role="admin", expected=201)
    assert late["request_available"] is False
