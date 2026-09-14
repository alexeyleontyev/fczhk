import asyncio
import hashlib
import secrets
from collections.abc import Generator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import schemas as S
from . import services as svc
from .auth import check_member, create_session, parse_telegram, player_for_telegram, public_player
from .config import Settings, settings
from .db import database, now
from .models import (
    Audit,
    GameTemplate,
    LoginSession,
    Match,
    Player,
    Publication,
    Registration,
    TeamSnapshot,
)


def create_app(cfg: Settings | None = None, factory=None) -> FastAPI:
    cfg = cfg or settings()

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if cfg.env == "demo":
            from .worker import run_worker

            task = asyncio.create_task(run_worker(cfg))
        try:
            yield
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(
        title="FCZHK · MVP 1",
        docs_url="/api/docs" if cfg.env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if cfg.env != "production" else None,
        lifespan=lifespan,
    )
    if factory is None:
        _, factory = database(cfg.database_url)
    app.state.cfg, app.state.factory = cfg, factory

    def db_dep() -> Generator[Session, None, None]:
        with factory() as db, db.begin():
            yield db

    async def current(
        db: Session = Depends(db_dep), authorization: str = Header(default="")
    ) -> Player:
        if not authorization.startswith("Bearer "):
            raise svc.DomainError("Войдите через Telegram", 401)
        digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
        session = db.get(LoginSession, digest)
        if not session or session.expires_at <= now():
            raise svc.DomainError("Сессия завершена. Войдите заново.", 401)
        p = db.get(Player, session.player_id)
        if not p or p.merged_into or not p.telegram_id:
            raise svc.DomainError("Профиль недоступен", 401)
        if (now() - session.checked_at).total_seconds() > cfg.membership_cache_seconds:
            await check_member(cfg, p.telegram_id)
            session.checked_at = now()
        return p

    def admin(p: Player = Depends(current)) -> Player:
        if p.telegram_id not in cfg.admins:
            raise svc.DomainError("Действие доступно администратору", 403)
        return p

    @app.exception_handler(svc.DomainError)
    async def domain_error(_, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_, exc):
        return JSONResponse(
            {"detail": "Данные изменились или уже существуют. Обновите страницу."}, status_code=409
        )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health(db: Session = Depends(db_dep)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "demo": cfg.env == "demo"}

    @app.post("/api/auth/telegram")
    async def login(body: S.Login, db: Session = Depends(db_dep)):
        user = parse_telegram(cfg, body.init_data)
        await check_member(cfg, user.id)
        p = player_for_telegram(db, user.id, user.first_name)
        return dict(token=create_session(db, cfg, p), player=public_player(p, cfg, own=True))

    if cfg.env == "demo":

        @app.post("/api/auth/demo/{role}")
        def demo_login(role: str, request: Request, db: Session = Depends(db_dep)):
            if request.client.host not in ("127.0.0.1", "::1", "testclient") or role not in (
                "admin",
                "player",
            ):
                raise svc.DomainError("Демо доступно только локально", 403)
            p = db.scalar(
                select(Player).where(Player.telegram_id == (1001 if role == "admin" else 1002))
            )
            if not p:
                raise svc.DomainError("Сначала запустите uv run fczhk demo", 503)
            return dict(token=create_session(db, cfg, p), player=public_player(p, cfg, own=True))

    @app.get("/api/me")
    def me(p: Player = Depends(current)):
        return public_player(p, cfg, own=True)

    @app.patch("/api/me")
    def update_me(body: S.Name, p: Player = Depends(current), db: Session = Depends(db_dep)):
        old = p.alias
        p.alias = body.alias
        svc.audit(db, p.id, "player.renamed", old=old, new=p.alias)
        return public_player(p, cfg, own=True)

    @app.get("/api/players")
    def players(p: Player = Depends(current), db: Session = Depends(db_dep)):
        return [
            public_player(x, cfg)
            for x in db.scalars(
                select(Player).where(Player.merged_into.is_(None)).order_by(Player.alias)
            )
        ]

    @app.post("/api/players/guests", status_code=201)
    def guest(body: S.Name, p: Player = Depends(admin), db: Session = Depends(db_dep)):
        new = Player(alias=body.alias)
        db.add(new)
        db.flush()
        svc.audit(db, p.id, "guest.created", player_id=new.id)
        return public_player(new, cfg)

    @app.post("/api/players/{guest_id}/link")
    def link(
        guest_id: int, body: S.LinkGuest, p: Player = Depends(admin), db: Session = Depends(db_dep)
    ):
        svc.merge_guest(db, p.id, guest_id, body.target_id)
        return {"ok": True}

    @app.get("/api/matches")
    def matches(p: Player = Depends(current), db: Session = Depends(db_dep)):
        query = select(Match).order_by(Match.starts_at.desc()).limit(200)
        if p.telegram_id not in cfg.admins:
            query = query.where(Match.status != "draft")
        return [svc.match_data(db, m) for m in db.scalars(query)]

    @app.get("/api/matches/{match_id}")
    def detail(match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep)):
        m = svc.get_match(db, match_id)
        if m.status == "draft" and p.telegram_id not in cfg.admins:
            raise svc.DomainError("Игра не найдена", 404)
        return svc.match_data(db, m)

    @app.post("/api/matches", status_code=201)
    def create(body: S.GameFields, p: Player = Depends(admin), db: Session = Depends(db_dep)):
        return svc.match_data(db, svc.create_match(db, p.id, body.model_dump()))

    @app.put("/api/matches/{match_id}")
    def edit(
        match_id: int, body: S.GameEdit, p: Player = Depends(admin), db: Session = Depends(db_dep)
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        before = {key: str(getattr(m, key)) for key in S.GameFields.model_fields}
        for key, value in body.model_dump(exclude={"version"}).items():
            setattr(m, key, value)
        m.game_day = m.starts_at.astimezone(svc.MOSCOW).date().isoformat()
        m.version += 1
        # Editing logistics invalidates published text; preserve manual assignments.
        for pub in db.scalars(
            select(Publication).where(Publication.match_id == m.id, Publication.stale.is_(False))
        ):
            pub.stale = True
            if pub.status == "pending":
                pub.status = "cancelled"
        if m.status == "open":
            svc.enqueue(db, m, "collection", cfg.publication_chat_id)
        svc.audit(
            db,
            p.id,
            "match.edited",
            m.id,
            old=before,
            new={key: str(getattr(m, key)) for key in S.GameFields.model_fields},
        )
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/actions/{action}")
    def action(
        match_id: int,
        action: str,
        body: S.Version,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        if action == "open":
            svc.open_match(db, p.id, m, cfg)
        elif action == "finalize":
            svc.finalize(db, p.id, m)
        elif action == "approve":
            svc.approve(db, p.id, m, cfg)
        elif action == "publish":
            svc.publish_teams(db, p.id, m, cfg)
        else:
            raise svc.DomainError("Неизвестное действие", 404)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/join")
    def join(
        match_id: int, body: S.Join, p: Player = Depends(current), db: Session = Depends(db_dep)
    ):
        m = svc.get_match(db, match_id, lock=True)
        svc.register(db, p.id, m, body.position)
        db.flush()
        return svc.match_data(db, m)

    @app.delete("/api/matches/{match_id}/join")
    def leave(match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep)):
        m = svc.get_match(db, match_id, lock=True)
        r = db.scalar(
            select(Registration).where(
                Registration.match_id == m.id, Registration.player_id == p.id
            )
        )
        if r:
            svc.cancel(db, p.id, m, r)
        db.flush()
        return svc.match_data(db, m)

    def registration(db, match_id, reg_id):
        r = db.get(Registration, reg_id)
        if not r or r.match_id != match_id:
            raise svc.DomainError("Заявка не найдена", 404)
        return r

    @app.put("/api/matches/{match_id}/registrations/{reg_id}/payment")
    def payment(
        match_id: int,
        reg_id: int,
        body: S.Payment,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.confirm_payment(db, p.id, m, registration(db, match_id, reg_id), body.paid)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/registrations/{reg_id}/remove")
    def remove(
        match_id: int,
        reg_id: int,
        body: S.Version,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.cancel(db, p.id, m, registration(db, match_id, reg_id), admin=True)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/participants")
    def include(
        match_id: int, body: S.Include, p: Player = Depends(admin), db: Session = Depends(db_dep)
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.add_participant(db, p.id, m, body.player_id, body.position, body.replace_id)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/promote")
    def promote(
        match_id: int, body: S.Promote, p: Player = Depends(admin), db: Session = Depends(db_dep)
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.promote(db, p.id, m, body.position)
        db.flush()
        return svc.match_data(db, m)

    @app.put("/api/matches/{match_id}/teams")
    def teams(
        match_id: int, body: S.Teams, p: Player = Depends(admin), db: Session = Depends(db_dep)
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.save_teams(db, p.id, m, body.assignments)
        db.flush()
        return svc.match_data(db, m)

    @app.get("/api/matches/{match_id}/history")
    def history(match_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep)):
        return dict(
            audit=[
                dict(id=a.id, actor_id=a.actor_id, action=a.action, data=a.data, at=a.created_at)
                for a in db.scalars(
                    select(Audit)
                    .where(Audit.match_id == match_id)
                    .order_by(Audit.id.desc())
                    .limit(200)
                )
            ],
            teams=[
                dict(version=t.version, teams=t.teams, at=t.created_at)
                for t in db.scalars(
                    select(TeamSnapshot)
                    .where(TeamSnapshot.match_id == match_id)
                    .order_by(TeamSnapshot.id.desc())
                )
            ],
        )

    @app.get("/api/template")
    def template(p: Player = Depends(admin), db: Session = Depends(db_dep)):
        t = db.get(GameTemplate, 1)
        return {key: getattr(t, key) for key in S.TemplateEdit.model_fields}

    @app.put("/api/template")
    def edit_template(
        body: S.TemplateEdit, p: Player = Depends(admin), db: Session = Depends(db_dep)
    ):
        t = db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
        if t.version != body.version:
            raise svc.DomainError("Шаблон изменился. Обновите страницу.", 409)
        before = {key: getattr(t, key) for key in S.TemplateEdit.model_fields}
        for key, value in body.model_dump(exclude={"version"}).items():
            setattr(t, key, value)
        t.version += 1
        svc.audit(db, p.id, "template.changed", old=before, new=body.model_dump())
        return {key: getattr(t, key) for key in S.TemplateEdit.model_fields}

    @app.post("/api/publications/{pub_id}/retry")
    def retry(pub_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep)):
        pub = db.scalar(select(Publication).where(Publication.id == pub_id).with_for_update())
        if not pub or pub.stale or pub.status not in ("failed", "uncertain"):
            raise svc.DomainError("Повторная публикация недоступна")
        pub.status, pub.error, pub.attempts = "pending", None, 0
        pub.next_attempt_at = now()
        svc.audit(db, p.id, "publication.retry", pub.match_id, publication_id=pub.id)
        return {"ok": True}

    @app.post("/api/telegram/webhook")
    async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(default="")):
        if not cfg.webhook_secret or not secrets.compare_digest(
            cfg.webhook_secret, x_telegram_bot_api_secret_token
        ):
            raise svc.DomainError("Недоступно", 403)
        from .bot import handle_update

        await handle_update(cfg, factory, await request.json())
        return {"ok": True}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def api_not_found(path: str):
        raise svc.DomainError("Не найдено", 404)

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    # Installed src layout and Docker's /app/frontend both resolve via cwd fallback.
    if not dist.exists():
        dist = Path("frontend/dist")
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            if path.startswith("api/"):
                raise svc.DomainError("Не найдено", 404)
            return FileResponse(dist / "index.html")

    return app
