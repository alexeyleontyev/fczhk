from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from sqlalchemy import func, select

from fczhk.api import create_app
from fczhk.db import now
from fczhk.models import LoginSession, Player
from fczhk.services import DomainError
from tests.helpers import signed_data


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def browser(env, monkeypatch, signing_key):
    cfg, factory, _, _, _ = env
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    cfg.telegram_login_client_id = 123456
    cfg.public_url = "http://testserver"
    cfg.bot_username = "football_test_bot"
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    jwk.update(kid="test-key", use="sig", alg="RS256")
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: {"keys": [jwk]})
    member = AsyncMock()
    monkeypatch.setattr("fczhk.auth.check_member", member)
    with TestClient(create_app(cfg, factory), headers={"Origin": cfg.public_url}) as client:
        yield client, member


def token(signing_key, challenge_nonce, **overrides):
    timestamp = int(now().timestamp())
    claims = {
        "iss": "https://oauth.telegram.org",
        "aud": "123456",
        # OIDC sub is not the Telegram user ID used by the Bot API.
        "sub": "998877665544332211",
        "iat": timestamp,
        "exp": timestamp + 300,
        "id": 102,
        "name": "Telegram name",
        "nonce": challenge_nonce,
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})


def start(client):
    response = client.post("/api/auth/telegram/browser/challenge")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()["nonce"]


def finish(client, signing_key, challenge_nonce, **overrides):
    return client.post(
        "/api/auth/telegram/browser",
        json={"id_token": token(signing_key, challenge_nonce, **overrides)},
    )


def test_browser_login_reuses_profile_and_clears_challenge(browser, env, signing_key):
    client, member = browser
    nonce = start(client)
    assert client.get("/api/auth/options").json() == {
        "browser_login": True,
        "bot_url": "https://t.me/football_test_bot",
    }
    result = finish(client, signing_key, nonce)
    assert result.status_code == 200, result.text
    assert result.json()["player"]["id"] == env[4]["player"]
    assert result.json()["player"]["alias"] == "Игрок"
    assert not result.json()["player"]["is_admin"]
    member.assert_awaited_once_with(env[0], 102)
    assert "fczhk-login" not in client.cookies
    me = client.get("/api/me", headers={"Authorization": f"Bearer {result.json()['token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == env[4]["player"]
    assert finish(client, signing_key, nonce).status_code == 401


def test_browser_login_registers_once_and_uses_numeric_admin_id(browser, env, signing_key):
    client, _ = browser
    for _ in range(2):
        response = finish(client, signing_key, start(client), id=777, name="Новый участник")
        assert response.status_code == 200
        assert not response.json()["player"]["is_admin"]
    with env[1]() as db:
        assert (
            db.scalar(select(func.count()).select_from(Player).where(Player.telegram_id == 777))
            == 1
        )
    response = finish(client, signing_key, start(client), id=101)
    assert response.json()["player"]["is_admin"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "other-bot"},
        {"aud": ["123456", "other-bot"]},
        {"iss": "https://attacker.example"},
        {"exp": 1},
        {"iat": 1},
        {"iat": 9999999999},
        {"nonce": "another-browser"},
        {"nonce": None},
        {"id": "102"},
        {"id": True},
        {"id": -1},
        {"name": " "},
        {"sub": None},
    ],
)
def test_browser_login_rejects_bad_claims(browser, env, signing_key, overrides):
    client, member = browser
    response = finish(client, signing_key, start(client), **overrides)
    assert response.status_code == 401, response.text
    member.assert_not_awaited()
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 2


def test_browser_login_rejects_forgery_and_missing_claims(browser, signing_key):
    client, member = browser
    nonce = start(client)
    valid = token(signing_key, nonce)
    claims = jwt.decode(valid, options={"verify_signature": False})
    del claims["nonce"]
    missing = jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})
    forged = jwt.encode(claims, "a" * 32, algorithm="HS256", headers={"kid": "test-key"})
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_signature = token(other_key, nonce)
    for value in (missing, forged, wrong_signature, "malformed.jwt"):
        response = client.post("/api/auth/telegram/browser", json={"id_token": value})
        assert response.status_code == 401
    member.assert_not_awaited()


def test_challenge_is_bound_to_browser_and_latest_attempt(browser, signing_key):
    client, _ = browser
    old = start(client)
    nonce = start(client)
    assert old != nonce
    assert finish(client, signing_key, old).status_code == 401
    client.cookies.clear()
    assert finish(client, signing_key, nonce).status_code == 401
    client.cookies.set("fczhk-login", "forged-cookie")
    assert finish(client, signing_key, nonce).status_code == 401


def test_server_rejects_expired_challenge_even_if_cookie_is_replayed(browser, signing_key):
    client, _ = browser
    nonce = start(client)
    # An actual old, correctly signed cookie: the browser's Max-Age is not the only check.
    from fczhk.browser_auth import BrowserAuth

    auth = BrowserAuth(client.app.state.cfg)
    cookie = jwt.encode({"nonce": nonce, "iat": 1, "exp": 2}, auth.cookie_key, algorithm="HS256")
    client.cookies.clear()
    client.cookies.set(auth.cookie_name, cookie)
    assert finish(client, signing_key, nonce).status_code == 401


@pytest.mark.parametrize("status", [403, 503])
def test_browser_login_requires_membership_before_creating_profile(
    browser, env, signing_key, status
):
    client, member = browser
    member.side_effect = DomainError("Нет доступа", status)
    response = finish(client, signing_key, start(client), id=777)
    assert response.status_code == status
    with env[1]() as db:
        assert db.scalar(select(Player).where(Player.telegram_id == 777)) is None
        assert db.scalar(select(func.count()).select_from(LoginSession)) == 2


def test_browser_login_rejects_other_origins_and_disabled_configuration(browser, env, signing_key):
    client, member = browser
    nonce = start(client)
    for origin in ("https://attacker.example", "null", ""):
        assert (
            client.post(
                "/api/auth/telegram/browser/challenge", headers={"Origin": origin}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/telegram/browser",
                headers={"Origin": origin},
                json={"id_token": token(signing_key, nonce)},
            ).status_code
            == 403
        )
    env[0].telegram_login_client_id = 0
    assert not client.get("/api/auth/options").json()["browser_login"]
    assert client.post("/api/auth/telegram/browser/challenge").status_code == 503
    assert finish(client, signing_key, nonce).status_code == 503
    member.assert_not_awaited()


def test_production_challenge_cookie_security(env):
    cfg = env[0]
    cfg.env = "production"
    cfg.bot_token = "123456:abcdefghijklmnopqrstuvwxyzABCDE"
    cfg.telegram_login_client_id = 123456
    cfg.public_url = "https://club.example"
    with TestClient(
        create_app(cfg, env[1]), base_url=cfg.public_url, headers={"Origin": cfg.public_url}
    ) as client:
        response = client.post("/api/auth/telegram/browser/challenge")
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert cookie.startswith("__Host-fczhk-login=")
        for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", "Max-Age=300"):
            assert flag in cookie
        assert "Domain=" not in cookie


def test_jwks_outage_fails_closed(browser, env, monkeypatch, signing_key):
    client, member = browser

    def unavailable(self):
        raise jwt.PyJWKClientConnectionError("offline")

    monkeypatch.setattr(PyJWKClient, "fetch_data", unavailable)
    response = finish(client, signing_key, start(client))
    assert response.status_code == 503
    member.assert_not_awaited()


def test_mini_app_login_still_uses_init_data(browser, env):
    client, member = browser
    response = client.post("/api/auth/telegram", json={"init_data": signed_data(env[0].bot_token)})
    assert response.status_code == 200
    assert response.json()["player"]["id"] == env[4]["player"]
    member.assert_awaited_once_with(env[0], 102)
