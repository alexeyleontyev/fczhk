"""Telegram Login (OIDC) for browsers; Mini App initData has its own verifier."""

import asyncio
import hashlib
import secrets
from types import SimpleNamespace
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWTError

from .db import now
from .services import DomainError

ISSUER = "https://oauth.telegram.org"


class BrowserAuth:
    def __init__(self, cfg):
        self.cfg = cfg
        self.keys = PyJWKClient(f"{ISSUER}/.well-known/jwks.json", timeout=5, lifespan=300)
        self.cookie_key = hashlib.sha256(b"fczhk-browser-login:" + cfg.bot_token.encode()).digest()
        self.cookie_name = "__Host-fczhk-login" if cfg.env == "production" else "fczhk-login"

    @property
    def enabled(self):
        return bool(
            self.cfg.telegram_login_client_id and self.cfg.bot_token and self.cfg.env != "demo"
        )

    def check_request(self, request):
        if not self.enabled:
            raise DomainError("Вход через Telegram в браузере пока не настроен.", 503)
        public = urlsplit(self.cfg.public_url)
        if request.headers.get("origin") != f"{public.scheme}://{public.netloc}":
            raise DomainError("Откройте вход на сайте клуба.", 403)

    def challenge(self, response):
        nonce = secrets.token_urlsafe(32)
        timestamp = int(now().timestamp())
        cookie = jwt.encode(
            {"nonce": nonce, "iat": timestamp, "exp": timestamp + self.cfg.auth_max_age_seconds},
            self.cookie_key,
            algorithm="HS256",
        )
        response.set_cookie(
            self.cookie_name,
            cookie,
            max_age=self.cfg.auth_max_age_seconds,
            secure=self.cfg.env == "production",
            httponly=True,
            samesite="strict",
        )
        return {"client_id": self.cfg.telegram_login_client_id, "nonce": nonce}

    async def verify(self, id_token, cookie):
        try:
            challenge = jwt.decode(
                cookie or "",
                self.cookie_key,
                algorithms=["HS256"],
                options={"require": ["nonce", "iat", "exp"]},
            )
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise jwt.InvalidTokenError()
            key = await asyncio.to_thread(self.keys.get_signing_key_from_jwt, id_token)
            claims = jwt.decode(
                id_token,
                key.key,
                algorithms=["RS256"],
                audience=str(self.cfg.telegram_login_client_id),
                issuer=ISSUER,
                leeway=30,
                options={
                    "require": ["iss", "aud", "sub", "iat", "exp", "id", "name", "nonce"],
                    "strict_aud": True,
                },
            )
            nonce = claims["nonce"]
            age = now().timestamp() - claims["iat"]
            if (
                not isinstance(nonce, str)
                or not secrets.compare_digest(nonce.encode(), challenge["nonce"].encode())
                or not -30 <= age <= self.cfg.auth_max_age_seconds
                or type(claims["id"]) is not int
                or not 0 < claims["id"] < 2**52
                or not isinstance(claims["name"], str)
                or not claims["name"].strip()
            ):
                raise jwt.InvalidTokenError()
        except PyJWKClientConnectionError as exc:
            raise DomainError("Telegram временно недоступен. Попробуйте войти позже.", 503) from exc
        except (PyJWTError, PyJWKClientError, TypeError, ValueError, AttributeError) as exc:
            raise DomainError(
                "Не удалось подтвердить вход. Попробуйте войти через Telegram заново.", 401
            ) from exc
        return SimpleNamespace(id=claims["id"], first_name=claims["name"])

    def clear(self, response):
        response.delete_cookie(
            self.cookie_name, secure=self.cfg.env == "production", httponly=True, samesite="strict"
        )
