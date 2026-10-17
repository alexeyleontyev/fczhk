import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError
from sqlalchemy.orm import Session

from . import services as svc
from .config import Settings, settings
from .db import database
from .http_context import HttpContext
from .routes import administration, auth_routes, competitions, matches, players, ratings


def create_app(cfg: Settings | None = None, factory=None) -> FastAPI:
    cfg = cfg or settings()

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if cfg.env == "demo":
            from .worker import run_demo_worker

            task = asyncio.create_task(run_demo_worker(cfg, factory))
        try:
            yield
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(
        title="ФКЖК · API",
        description="Игры, составы, результаты, рейтинги и прогнозы футбольного сообщества.",
        version="0.5.0",
        docs_url="/api/docs" if cfg.env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if cfg.env != "production" else None,
        lifespan=lifespan,
    )
    if factory is None:
        _, factory = database(cfg.database_url)
    app.state.cfg, app.state.factory = cfg, factory
    ctx = HttpContext(cfg, factory)
    app.state.context = ctx
    db_dep = ctx.db_dep
    for module in (auth_routes, players, competitions, matches, ratings, administration):
        app.include_router(module.router(ctx))

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
        if request.url.path in (
            "/api/auth/telegram",
            "/api/auth/telegram/browser",
            "/api/auth/telegram/browser/challenge",
        ) and not ctx.limiter.allow(request.client.host if request.client else "unknown"):
            return JSONResponse(
                {"detail": "Слишком много попыток входа. Повторите через минуту."},
                status_code=429,
                headers={"Retry-After": "60", "Cache-Control": "no-store"},
            )
        try:
            response = await call_next(request)
        except Exception:
            ctx.errors["http_5xx"] += 1
            if request.url.path == "/api/telegram/webhook":
                ctx.errors["webhook_errors"] += 1
            raise
        if response.status_code >= 500:
            ctx.errors["http_5xx"] += 1
            if request.url.path == "/api/telegram/webhook":
                ctx.errors["webhook_errors"] += 1
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(OperationalError)
    @app.exception_handler(TimeoutError)
    async def database_busy(_, exc):
        return JSONResponse(
            {"detail": "База временно занята. Повторите действие."}, status_code=503
        )

    @app.get("/api/health")
    def health(db: Session = Depends(db_dep, scope="function")):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "demo": cfg.env == "demo"}

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def api_not_found(path: str):
        raise svc.DomainError("Не найдено", 404)

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    # Installed src layout and Docker's /app/frontend both resolve via cwd fallback.
    if not dist.exists():
        dist = Path("frontend/dist")
    if dist.exists():
        # A dev rebuild briefly replaces assets; don't couple API startup/tests to it.
        app.mount("/assets", StaticFiles(directory=dist / "assets", check_dir=False), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise svc.DomainError("Не найдено", 404)
            return FileResponse(dist / "index.html")

    return app
