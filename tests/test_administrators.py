import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from fczhk.api import create_app
from fczhk.config import Settings
from fczhk.models import Audit
from tests.helpers import signed_data


def test_owner_and_player_cannot_promote_themselves_or_change_owner(env, call):
    _, factory, _, _, ids = env
    assert call("GET", "/me")["is_owner"] is True
    assert call("GET", "/me", role="player")["is_owner"] is False
    call("GET", "/administrators", role=None, expected=401)
    call("GET", "/administrators", role="player", expected=403)
    call("PATCH", "/me", {"alias": "Самоназначение", "is_admin": True}, role="player", expected=422)
    for target in (ids["player"], ids["admin"]):
        call(
            "PUT",
            f"/administrators/{target}",
            {"is_admin": True, "revision": 0},
            role="player",
            expected=403,
        )
    for allowed in (True, False):
        call(
            "PUT",
            f"/administrators/{ids['admin']}",
            {"is_admin": allowed, "revision": 0},
            expected=409,
        )
    with factory() as db:
        assert list(db.scalars(select(Audit).where(Audit.action.like("administrator.%")))) == []


def test_grant_and_revoke_apply_to_existing_sessions_all_views_and_survive_restart(env, call):
    cfg, factory, _, tokens, ids = env
    draft = call(
        "POST",
        "/matches",
        {"starts_at": "2032-06-04T20:00:00+03:00", "location": "Поле"},
        expected=201,
    )
    assert call("GET", "/matches", role="player") == []
    path = f"/administrators/{ids['player']}"
    granted = call("PUT", path, {"is_admin": True, "revision": 0})
    assert (granted["role"], granted["revision"]) == ("admin", 1)
    assert call("GET", "/me", role="player")["is_admin"] is True
    assert call("GET", "/me", role="player")["is_owner"] is False
    assert call("GET", "/matches", role="player")[0]["id"] == draft["id"]
    call("GET", f"/matches/{draft['id']}", role="player")
    call("GET", "/template", role="player")
    call("GET", "/operations", role="player")
    # An administrator can operate games, but cannot manage any roles.
    call("GET", "/administrators", role="player", expected=403)
    call("PUT", path, {"is_admin": False, "revision": 1}, role="player", expected=403)
    call(
        "PUT",
        f"/administrators/{ids['admin']}",
        {"is_admin": False, "revision": 0},
        role="player",
        expected=403,
    )
    with TestClient(create_app(cfg, factory)) as restarted:
        headers = {"Authorization": f"Bearer {tokens['player']}"}
        assert restarted.get("/api/template", headers=headers).status_code == 200
    revoked = call("PUT", path, {"is_admin": False, "revision": 1})
    assert (revoked["role"], revoked["revision"]) == ("player", 2)
    assert call("GET", "/me", role="player")["is_admin"] is False
    for endpoint in ("/template", "/operations", "/profile-claims"):
        call("GET", endpoint, role="player", expected=403)
    assert call("GET", "/matches", role="player") == []
    for suffix in ("", "/auction", "/predictions"):
        call("GET", f"/matches/{draft['id']}{suffix}", role="player", expected=404)
    call("POST", "/players/guests", {"alias": "Не создавать"}, role="player", expected=403)
    # The same bearer session is still usable as a player after demotion.
    call("GET", "/players", role="player")
    with TestClient(create_app(cfg, factory)) as restarted:
        assert restarted.get("/api/template", headers=headers).status_code == 403
    with factory() as db:
        entries = list(
            db.scalars(select(Audit).where(Audit.action.like("administrator.%")).order_by(Audit.id))
        )
        assert [entry.action for entry in entries] == [
            "administrator.granted",
            "administrator.revoked",
        ]
        assert all(
            entry.actor_id == ids["admin"] and entry.data["player_id"] == ids["player"]
            for entry in entries
        )


def test_role_updates_reject_stale_revision_and_invalid_targets(env, call):
    ids = env[4]
    guest = call("POST", "/players/guests", {"alias": "Исторический гость"}, expected=201)
    assert guest["id"] not in {entry["id"] for entry in call("GET", "/administrators")}
    call("PUT", f"/administrators/{guest['id']}", {"is_admin": True, "revision": 0}, expected=409)
    call("PUT", "/administrators/999999", {"is_admin": True, "revision": 0}, expected=404)
    path = f"/administrators/{ids['player']}"
    for payload in (
        {"is_admin": True},
        {"is_admin": "true", "revision": 0},
        {"is_admin": True, "revision": -1},
        {"is_admin": True, "revision": 0, "is_owner": True},
    ):
        call("PUT", path, payload, expected=422)
    call("PUT", path, {"is_admin": True, "revision": 0})
    call("PUT", path, {"is_admin": False, "revision": 0}, expected=409)
    assert call("GET", "/me", role="player")["is_admin"]
    # An idempotent write does not manufacture a new revision/audit entry.
    assert call("PUT", path, {"is_admin": True, "revision": 1})["revision"] == 1


def test_legacy_admin_can_be_revoked_permanently_and_explicit_owner_takes_precedence(env, call):
    cfg, factory, _, tokens, ids = env
    cfg.admin_ids = "102,101"
    assert cfg.effective_owner_id == 101
    assert call("GET", "/me")["is_owner"]
    assert call("GET", "/me", role="player")["is_admin"]
    call("PUT", f"/administrators/{ids['player']}", {"is_admin": False, "revision": 0})
    assert not call("GET", "/me", role="player")["is_admin"]
    with TestClient(create_app(cfg, factory)) as restarted:
        response = restarted.get("/api/me", headers={"Authorization": f"Bearer {tokens['player']}"})
        assert not response.json()["is_admin"]


def test_both_telegram_login_and_current_user_return_database_roles(env, call):
    cfg, _, client, _, ids = env
    cfg.bot_token = "123:test"
    call("PUT", f"/administrators/{ids['player']}", {"is_admin": True, "revision": 0})
    for user_id, owner in ((101, True), (102, False)):
        response = client.post(
            "/api/auth/telegram", json={"init_data": signed_data(cfg.bot_token, user_id=user_id)}
        )
        assert response.status_code == 200
        assert response.json()["player"]["is_admin"] is True
        assert response.json()["player"]["is_owner"] is owner


def test_owner_configuration_and_legacy_fallback():
    assert Settings(_env_file=None, env="test", admin_ids="202,101").effective_owner_id == 202
    cfg = Settings(
        _env_file=None,
        env="production",
        owner_id=101,
        bot_token="test",
        community_chat_id="-100",
        database_url="postgresql+psycopg://test",
        public_url="https://example.test",
    )
    assert cfg.effective_owner_id == 101
    with pytest.raises(ValidationError, match="OWNER_ID"):
        Settings(_env_file=None, env="production", bot_token="test", community_chat_id="-100")
    for invalid in ("-101", "0", "username", str(2**52)):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, env="test", admin_ids=invalid)
