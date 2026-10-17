import hashlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select

from fczhk.db import now
from fczhk.models import GameTemplate, LoginSession, Player, Publication, ServiceHeartbeat
from fczhk.operations import cleanup_sessions, heartbeat
from fczhk.services import MOSCOW, schedule_tick


def future_game(call, opened=True):
    match = call(
        "POST",
        "/matches",
        {"starts_at": "2032-06-04T20:00:00+03:00", "location": "Поле"},
        expected=201,
    )
    if opened:
        match = call("POST", f"/matches/{match['id']}/actions/open", {"version": match["version"]})
    return match


def test_logout_revokes_only_current_session_and_expiry_cleanup(env, call):
    _, factory, _, tokens, _ = env
    call("POST", "/auth/logout", role="player")
    call("GET", "/me", role="player", expected=401)
    assert call("GET", "/me")["is_admin"]
    with factory() as db, db.begin():
        db.get(LoginSession, hashlib.sha256(tokens["admin"].encode()).hexdigest()).expires_at = (
            now() - timedelta(seconds=1)
        )
    assert cleanup_sessions(factory) == 1
    assert cleanup_sessions(factory) == 0
    call("GET", "/me", expected=401)


def test_auth_limit_precedes_signature_and_telegram_call(env, monkeypatch):
    cfg, _, client, _, _ = env
    cfg.auth_ip_limit = 2
    checker = AsyncMock()
    monkeypatch.setattr("fczhk.auth.check_member", checker)
    for _ in range(2):
        assert client.post("/api/auth/telegram", json={"init_data": "invalid"}).status_code == 401
    response = client.post("/api/auth/telegram", json={"init_data": "invalid"})
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert checker.await_count == 0
    assert client.get("/api/health").status_code == 200


def test_ready_metrics_and_publication_failures(env, call):
    cfg, factory, client, _, _ = env
    call("GET", "/operations", role="player", expected=403)
    call("GET", "/health/ready", role=None, expected=503)
    heartbeat(factory)
    assert call("GET", "/health/ready", role=None)["worker"]
    cfg.metrics_token = "test-metrics-secret"
    assert client.get("/api/metrics").status_code == 403
    metrics = client.get("/api/metrics", headers={"Authorization": "Bearer test-metrics-secret"})
    assert metrics.status_code == 200 and "fczhk_worker_healthy 1" in metrics.text
    game = future_game(call)
    with factory() as db, db.begin():
        publication = db.scalar(select(Publication).where(Publication.match_id == game["id"]))
        publication.status = "uncertain"
        pid = publication.id
    status = call("GET", "/operations")
    assert status["status"] == "degraded" and status["problems"][0]["id"] == pid
    call("GET", "/health/ready", role=None, expected=503)
    call("POST", f"/publications/{pid}/retry", role="player", expected=403)
    call("POST", f"/publications/{pid}/retry")
    assert call("GET", "/health/ready", role=None)["status"] == "ok"
    with factory() as db, db.begin():
        db.get(ServiceHeartbeat, "worker").succeeded_at = now() - timedelta(minutes=3)
    call("GET", "/health/ready", role=None, expected=503)


def test_cancellation_preserves_payments_blocks_roster_and_sends_notice(env, call):
    game = future_game(call)
    path = f"/matches/{game['id']}"
    game = call("POST", path + "/join", {"position": "field"}, role="player")
    rid = game["registrations"][0]["id"]
    game = call(
        "PUT", f"{path}/registrations/{rid}/payment", {"version": game["version"], "paid": True}
    )
    body = {"version": game["version"], "reason": "Поле закрыто"}
    call("POST", path + "/cancel", body, role="player", expected=403)
    cancelled = call("POST", path + "/cancel", body)
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_reason"] == "Поле закрыто"
    assert cancelled["registrations"][0]["paid"]
    assert (
        next(p for p in cancelled["publications"] if p["kind"] == "cancellation")["status"]
        == "pending"
    )
    assert next(p for p in cancelled["publications"] if p["kind"] == "collection")["stale"]
    call("POST", path + "/join", {"position": "field"}, role="player", expected=400)
    call("POST", path + "/actions/finalize", {"version": cancelled["version"]}, expected=400)
    call(
        "PUT",
        f"{path}/registrations/{rid}/payment",
        {"version": cancelled["version"], "paid": False},
        expected=409,
    )
    assert call("GET", "/matches/current") is None
    assert call("GET", "/matches")[0]["status"] == "cancelled"


def test_draft_cancellation_does_not_publish_and_past_game_cannot_cancel(call, game):
    draft = future_game(call, opened=False)
    cancelled = call(
        "POST",
        f"/matches/{draft['id']}/cancel",
        {"version": draft["version"], "reason": "Черновик ошибочен"},
    )
    assert cancelled["publications"] == []
    call(
        "POST",
        f"/matches/{game['id']}/cancel",
        {"version": game["version"], "reason": "Поздняя отмена"},
        expected=409,
    )


def test_skipped_week_blocks_scheduler_and_manual_creation(env, call):
    cfg, factory, _, _, _ = env
    body = {"game_day": "2032-06-04", "reason": "Праздники"}
    call("POST", "/schedule/skipped", body, role="player", expected=403)
    call("POST", "/schedule/skipped", body)
    call("POST", "/schedule/skipped", body, expected=409)
    with factory() as db, db.begin():
        template = db.get(GameTemplate, 1)
        template.enabled, template.location = True, "Поле"
    at = datetime(2032, 6, 1, 12, tzinfo=MOSCOW)
    with factory() as db, db.begin():
        assert schedule_tick(db, cfg, at) is None
    call(
        "POST",
        "/matches",
        {"starts_at": "2032-06-04T20:00:00+03:00", "location": "Поле"},
        expected=409,
    )
    call("DELETE", "/schedule/skipped/2032-06-04")
    with factory() as db, db.begin():
        mid = schedule_tick(db, cfg, at)
        assert mid
    call("POST", "/schedule/skipped", body, expected=409)


def test_profile_claim_requires_admin_and_preserves_source(env, call):
    _, factory, _, _, ids = env
    guest = call("POST", "/players/guests", {"alias": "Старая карточка"}, expected=201)
    body = {"guest_id": guest["id"]}
    call("POST", "/me/profile-claim", body, role="player")
    call("POST", "/me/profile-claim", body)  # competing claim
    path = f"/profile-claims/{ids['player']}/resolve"
    call("POST", path, {**body, "accept": True}, role="player", expected=403)
    call("POST", path, {"guest_id": ids["admin"], "accept": True}, expected=409)
    accepted = call("POST", path, {**body, "accept": True})
    assert accepted["status"] == "accepted"
    assert call("GET", "/me/profile-claim")["status"] == "rejected"
    assert call("GET", "/profile-claims") == []
    with factory() as db:
        assert db.get(Player, guest["id"]).merged_into == ids["player"]
    call("POST", "/me/profile-claim", body, role="player", expected=409)


def test_direct_link_resolves_pending_claim(env, call):
    guest = call("POST", "/players/guests", {"alias": "Карточка гостя"}, expected=201)
    call("POST", "/me/profile-claim", {"guest_id": guest["id"]}, role="player")
    call("POST", f"/players/{guest['id']}/link", {"target_id": env[4]["player"]})
    assert call("GET", "/me/profile-claim", role="player")["status"] == "accepted"
