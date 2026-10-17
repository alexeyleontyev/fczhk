"""Request dependencies; synchronous database work never runs on the event loop."""

import hashlib
from collections import OrderedDict
from collections.abc import Generator
from threading import Lock
from time import monotonic

from fastapi import Depends, Header
from starlette.concurrency import run_in_threadpool

from . import auth
from .browser_auth import BrowserAuth
from .db import now
from .models import LoginSession, Player
from .services import DomainError


class AuthLimiter:
    """Bounded per-process limiter; the deployment runs one API process.

    A global budget also bounds work if clients rotate addresses. Forwarded client
    addresses are trusted only from the proxy configured in Uvicorn.
    """

    def __init__(self, cfg):
        self.cfg, self.lock, self.windows = cfg, Lock(), OrderedDict()

    def allow(self, address):
        at = monotonic()
        with self.lock:
            for key, limit in (
                ("global", self.cfg.auth_global_limit),
                (address, self.cfg.auth_ip_limit),
            ):
                start, count = self.windows.get(key, (at, 0))
                if at - start >= 60:
                    start, count = at, 0
                if count >= limit:
                    return False
                self.windows[key] = (start, count + 1)
                self.windows.move_to_end(key)
            while len(self.windows) > 4096:
                self.windows.popitem(last=False)
            return True


class HttpContext:
    def __init__(self, cfg, factory):
        self.cfg, self.factory = cfg, factory
        self.browser_auth = BrowserAuth(cfg)
        self.limiter = AuthLimiter(cfg)
        self.errors = {"http_5xx": 0, "webhook_errors": 0}

        def db_dep() -> Generator:
            # The commit happens before HTTP success, including when it fails.
            with factory() as db, db.begin():
                yield db

        async def current(authorization: str = Header(default="")) -> Player:
            digest = self.digest(authorization)
            player, checked_at = await run_in_threadpool(self.load_identity, digest)
            if (now() - checked_at).total_seconds() > cfg.membership_cache_seconds:
                # No database connection is held while waiting for Telegram.
                await auth.check_member(cfg, player.telegram_id)
                await run_in_threadpool(self.mark_checked, digest)
            return player

        def admin(player: Player = Depends(current)) -> Player:
            if player.telegram_id not in cfg.admins:
                raise DomainError("Действие доступно администратору", 403)
            return player

        self.db_dep, self.current, self.admin = db_dep, current, admin

    @staticmethod
    def digest(authorization):
        if not authorization.startswith("Bearer "):
            raise DomainError("Войдите через Telegram", 401)
        return hashlib.sha256(authorization[7:].encode()).hexdigest()

    def load_identity(self, digest):
        with self.factory() as db, db.begin():
            session = db.get(LoginSession, digest)
            if not session or session.expires_at <= now():
                raise DomainError("Сессия завершена. Войдите заново.", 401)
            player = db.get(Player, session.player_id)
            if not player or player.merged_into or not player.telegram_id:
                raise DomainError("Профиль недоступен", 401)
            return player, session.checked_at

    def mark_checked(self, digest):
        with self.factory() as db, db.begin():
            session = db.get(LoginSession, digest)
            if not session or session.expires_at <= now():
                raise DomainError("Сессия завершена. Войдите заново.", 401)
            session.checked_at = now()

    def finish_login(self, user):
        with self.factory() as db, db.begin():
            player = auth.player_for_telegram(db, user.id, user.first_name)
            result = dict(
                token=auth.create_session(db, self.cfg, player),
                player=auth.public_player(player, self.cfg, own=True),
            )
        return result
