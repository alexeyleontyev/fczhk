import secrets
from datetime import date

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import operations
from .. import schemas as S
from .. import services as svc
from ..db import now
from ..models import (
    GameTemplate,
    Player,
    Publication,
    SkippedGameDay,
)


def router(ctx):
    app = APIRouter()
    cfg = ctx.cfg
    factory = ctx.factory
    db_dep = ctx.db_dep
    admin = ctx.admin

    @app.get("/api/template")
    def template(p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")):
        t = db.get(GameTemplate, 1)
        return {key: getattr(t, key) for key in S.TemplateEdit.model_fields}

    @app.put("/api/template")
    def edit_template(
        body: S.TemplateEdit,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
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
    def retry(
        pub_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
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
        from ..bot import handle_update

        await handle_update(cfg, factory, await request.json())
        return {"ok": True}

    @app.get("/api/schedule/skipped")
    def skipped(p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")):
        return [
            dict(game_day=row.game_day, reason=row.reason)
            for row in db.scalars(
                select(SkippedGameDay).order_by(SkippedGameDay.game_day.desc()).limit(100)
            )
        ]

    @app.post("/api/schedule/skipped")
    def skip(
        body: S.SkipDay, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        svc.skip_day(db, p.id, body.game_day, body.reason)
        return {"ok": True}

    @app.delete("/api/schedule/skipped/{day}")
    def unskip(
        day: date, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
        row = db.get(SkippedGameDay, day.isoformat())
        if row:
            db.delete(row)
            svc.audit(db, p.id, "schedule.unskipped", game_day=day.isoformat())
        return {"ok": True}

    @app.get("/api/operations")
    def operational_status(
        p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        return {
            **operations.status(db, cfg),
            "errors": ctx.errors.copy(),
            "problems": operations.publication_problems(db),
        }

    @app.get("/api/health/ready")
    def ready(db: Session = Depends(db_dep, scope="function")):
        state = operations.status(db, cfg)
        return JSONResponse(
            {"status": state["status"], "worker": state["worker"]["healthy"]},
            status_code=200 if state["status"] == "ok" else 503,
        )

    @app.get("/api/metrics", response_class=PlainTextResponse)
    def metrics(
        authorization: str = Header(default=""), db: Session = Depends(db_dep, scope="function")
    ):
        if not cfg.metrics_token or not secrets.compare_digest(
            authorization, f"Bearer {cfg.metrics_token}"
        ):
            raise svc.DomainError("Недоступно", 403)
        state = operations.status(db, cfg)
        values = {
            "worker_healthy": int(state["worker"]["healthy"]),
            "queue_age_seconds": state["queue_age_seconds"],
            "publications_failed": state["publications"].get("failed", 0),
            "publications_uncertain": state["publications"].get("uncertain", 0),
            "http_5xx_total": ctx.errors["http_5xx"],
            "webhook_errors_total": ctx.errors["webhook_errors"],
            "stuck_sending": state["stuck_sending"],
            "stale_mark_errors": state["stale_mark_errors"],
        }
        return "".join(f"fczhk_{key} {value}\n" for key, value in values.items())

    @app.post("/api/publications/{pub_id}/retry-stale")
    def retry_stale(
        pub_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        pub = db.scalar(select(Publication).where(Publication.id == pub_id).with_for_update())
        if not pub or not pub.stale or pub.stale_marked or pub.status not in ("sent", "demo"):
            raise svc.DomainError("Пометка недоступна", 409)
        pub.error, pub.next_attempt_at = None, now()
        svc.audit(db, p.id, "publication.retry_stale", pub.match_id, publication_id=pub.id)
        return {"ok": True}

    return app
