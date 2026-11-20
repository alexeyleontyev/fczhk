from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select

from fczhk.models import Player, PointRequest, Publication, WalletEntry
from fczhk.worker import deliver_one
from tests.test_telegram import callback_replies


def test_point_request_api_is_removed(call):
    call("POST", "/wallet/requests", {"amount": 50}, role="player", expected=404)
    call("POST", "/wallet/requests/cancel", role="player", expected=404)
    call("GET", "/wallet/requests", expected=404)
    call("POST", "/wallet/requests/1/decision", {"approve": True}, expected=404)
    wallet = call("GET", "/wallet", role="player")
    assert wallet["balance"] == 0
    assert {"request", "request_available", "next_request_at"}.isdisjoint(wallet)


def test_only_the_owner_can_adjust_a_wallet_without_notifications(env, call):
    _, factory, _, _, ids = env
    call("PUT", f"/administrators/{ids['player']}", {"is_admin": True, "revision": 0})
    assert call("GET", "/me", role="player")["is_admin"] is True
    call("GET", "/wallet/grants", role="player", expected=403)
    call(
        "POST",
        "/wallet/grants",
        {"player_id": ids["admin"], "amount": 50, "reason": "Приз"},
        role="player",
        expected=403,
    )
    call(
        "POST",
        "/wallet/grants",
        {"player_id": ids["player"], "amount": 50, "reason": "Приз"},
        expected=201,
    )
    assert call("GET", "/wallet", role="player")["balance"] == 50
    with factory() as db:
        assert not list(db.scalars(select(Publication)))


async def test_old_telegram_button_cannot_change_balance(env, call, monkeypatch):
    assert await callback_replies(env, monkeypatch, "pts:1:a", user_id=101) == []
    assert call("GET", "/wallet", role="player")["balance"] == 0


@pytest.mark.parametrize("kind", ["points_request", "points_decided"])
async def test_retired_publications_cannot_be_retried_or_sent(env, call, kind):
    cfg, factory, *_ = env
    with factory() as db, db.begin():
        failed = Publication(kind=kind, version=1, text="Сообщение", status="failed")
        pending = Publication(kind=kind, version=1, text="Сообщение", chat_id="123")
        db.add_all([failed, pending])
        db.flush()
        failed_id, pending_id = failed.id, pending.id
    call("POST", f"/publications/{failed_id}/retry", expected=409)
    bot = AsyncMock()
    assert await deliver_one(cfg, factory, bot)
    bot.send_message.assert_not_awaited()
    with factory() as db:
        assert db.get(Publication, pending_id).status == "cancelled"


def test_migration_closes_requests_and_preserves_wallet_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/wallet.db")
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "e1b5c7a93f20")
        conn.execute(Player.__table__.insert(), {"id": 9001, "alias": "Игрок"})
        conn.execute(
            PointRequest.__table__.insert(),
            [
                {"id": 1, "player_id": 9001, "amount": 5000, "status": "pending"},
                {"id": 2, "player_id": 9001, "amount": 8000, "status": "approved"},
            ],
        )
        conn.execute(
            WalletEntry.__table__.insert(),
            {"player_id": 9001, "kind": "freebet", "amount": 10000, "freebet_week": "2026-W46"},
        )
        conn.execute(
            Publication.__table__.insert(),
            [
                {
                    "id": 1,
                    "kind": "points_request",
                    "version": 1,
                    "text": "x",
                    "status": "pending",
                    "error": None,
                },
                {
                    "id": 2,
                    "kind": "points_request",
                    "version": 1,
                    "text": "x",
                    "status": "sending",
                    "error": None,
                },
                {
                    "id": 3,
                    "kind": "points_decided",
                    "version": 1,
                    "text": "x",
                    "status": "failed",
                    "error": "x",
                },
                {
                    "id": 4,
                    "kind": "points_decided",
                    "version": 1,
                    "text": "x",
                    "status": "uncertain",
                    "error": "x",
                },
                {
                    "id": 5,
                    "kind": "points_decided",
                    "version": 1,
                    "text": "x",
                    "status": "sent",
                    "error": None,
                },
                {
                    "id": 6,
                    "kind": "collection",
                    "version": 1,
                    "text": "x",
                    "status": "failed",
                    "error": "x",
                },
            ],
        )
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "e1b5c7a93f20")
        command.upgrade(cfg, "head")
        requests = conn.execute(
            select(PointRequest.status, PointRequest.decided_at).order_by(PointRequest.id)
        ).all()
        assert requests[0].status == "cancelled" and requests[0].decided_at is not None
        assert requests[1].status == "approved"
        assert conn.execute(
            select(Publication.status, Publication.error).order_by(Publication.id)
        ).all() == [("cancelled", None)] * 4 + [("sent", None), ("failed", "x")]
        assert conn.scalar(select(WalletEntry.amount)) == 10000
