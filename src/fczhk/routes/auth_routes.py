from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import auth
from .. import results as res
from .. import schemas as S
from .. import services as svc
from ..auth import create_session, parse_telegram, public_player
from ..models import (
    LoginSession,
    Player,
)


def router(ctx):
    app = APIRouter()
    cfg = ctx.cfg
    browser_auth = ctx.browser_auth
    db_dep = ctx.db_dep

    @app.post("/api/auth/telegram")
    async def login(body: S.Login):
        user = parse_telegram(cfg, body.init_data)
        await auth.check_member(cfg, user.id)
        return await run_in_threadpool(ctx.finish_login, user)

    @app.get("/api/auth/options")
    def auth_options():
        return {
            "browser_login": browser_auth.enabled,
            "bot_url": f"https://t.me/{cfg.bot_username.lstrip('@')}" if cfg.bot_username else None,
        }

    @app.post("/api/auth/telegram/browser/challenge")
    def browser_challenge(request: Request, response: Response):
        browser_auth.check_request(request)
        return browser_auth.challenge(response)

    @app.post("/api/auth/telegram/browser")
    async def browser_login(
        body: S.BrowserLogin,
        request: Request,
        response: Response,
    ):
        browser_auth.check_request(request)
        user = await browser_auth.verify(
            body.id_token, request.cookies.get(browser_auth.cookie_name)
        )
        await auth.check_member(cfg, user.id)
        result = await run_in_threadpool(ctx.finish_login, user)
        browser_auth.clear(response)
        return result

    @app.post("/api/auth/logout")
    def logout(
        authorization: str = Header(default=""), db: Session = Depends(db_dep, scope="function")
    ):
        session = db.get(LoginSession, ctx.digest(authorization))
        if session:
            db.delete(session)
        return {"ok": True}

    if cfg.env == "demo":

        @app.post("/api/auth/demo/{role}")
        def demo_login(
            role: str, request: Request, db: Session = Depends(db_dep, scope="function")
        ):
            if request.client.host not in ("127.0.0.1", "::1", "testclient") or role not in (
                "admin",
                "player",
            ):
                raise svc.DomainError("Демо доступно только локально", 403)
            p = db.scalar(
                select(Player).where(Player.telegram_id == (1001 if role == "admin" else 1002))
            )
            if not p:
                # A history-only demo contains source players, not seeded demo users.
                # Bind local demo identities to two of those records on first login.
                p = db.scalar(
                    select(Player)
                    .join(res.ResultParticipant, res.ResultParticipant.player_id == Player.id)
                    .where(Player.merged_into.is_(None))
                    .where(res.ResultParticipant.position == "field")
                    .distinct()
                    .order_by(Player.id)
                    .offset(0 if role == "admin" else 1)
                    .limit(1)
                )
                if not p or p.telegram_id not in (None, 1001 if role == "admin" else 1002):
                    raise svc.DomainError("Сначала запустите uv run fczhk demo", 503)
                p.telegram_id = 1001 if role == "admin" else 1002
            return dict(token=create_session(db, cfg, p), player=public_player(p, cfg, own=True))

    return app
