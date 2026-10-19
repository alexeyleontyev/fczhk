from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import lineups
from .. import ratings as rt
from .. import schemas as S
from .. import services as svc
from ..auth import has_admin_access
from ..models import (
    BalanceRun,
    Player,
)
from ..services import registration


def router(ctx):
    app = APIRouter()
    db_dep = ctx.db_dep
    admin = ctx.admin
    current = ctx.current

    def visible(db, match_id, player, version=None, lock=False):
        match = svc.get_match(db, match_id, version, lock=lock)
        if match.status == "draft" and not has_admin_access(player, ctx.cfg):
            raise svc.DomainError("Игра не найдена", 404)
        return match

    @app.get("/api/matches/{match_id}/lineup")
    def lineup_data(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        return lineups.data(db, visible(db, match_id, p), ctx.cfg)

    @app.post("/api/matches/{match_id}/lineup/preview")
    def lineup_preview(
        match_id: int,
        body: S.LineupPreview,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = visible(db, match_id, p, body.version, lock=True)
        return lineups.preview(db, m, ctx.cfg, body.method)

    @app.post("/api/matches/{match_id}/lineup/confirm")
    def lineup_confirm(
        match_id: int,
        body: S.LineupConfirm,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = visible(db, match_id, p, body.version, lock=True)
        return lineups.confirm(db, p.id, m, body, ctx.cfg)

    @app.put("/api/matches/{match_id}/registrations/{reg_id}/rating")
    def temporary_rating(
        match_id: int,
        reg_id: int,
        body: S.MatchRatingEdit,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        rt.set_temporary(db, p.id, m, registration(db, match_id, reg_id), body)
        return svc.match_data(db, m)

    @app.get("/api/balance/settings")
    def balance_settings(p: Player = Depends(admin)):
        return S.BalanceSettings().model_dump(mode="json")

    @app.post("/api/matches/{match_id}/balance", status_code=201)
    def generate_balance(
        match_id: int,
        body: S.BalanceGenerate,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        run = rt.create_run(db, p.id, m, body.settings)
        return rt.run_data(db, m, run)

    @app.get("/api/matches/{match_id}/balance")
    def balance_history(
        match_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id)
        runs = db.scalars(
            select(BalanceRun)
            .where(BalanceRun.match_id == m.id)
            .order_by(BalanceRun.id.desc())
            .limit(10)
        )
        return [rt.run_data(db, m, run) for run in runs]

    @app.post("/api/matches/{match_id}/balance/{run_id}/apply")
    def apply_balance(
        match_id: int,
        run_id: int,
        body: S.BalanceApply,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        rt.apply_run(db, p.id, m, run_id, body.variant)
        return svc.match_data(db, m)

    return app
