from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auctions as auc
from .. import predictions as pred
from .. import results as res
from .. import schemas as S
from .. import services as svc
from ..auth import has_admin_access
from ..models import (
    Player,
)


def router(ctx):
    app = APIRouter()
    cfg = ctx.cfg
    db_dep = ctx.db_dep
    current = ctx.current
    admin = ctx.admin

    @app.get("/api/predictions/standings")
    def prediction_standings(
        season: str | None = Query(default=None, min_length=1, max_length=40),
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        return pred.standings(db, season=season)

    @app.get("/api/matches/{match_id}/predictions")
    def prediction_detail(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id, lock=True)
        if m.status == "draft" and not has_admin_access(p, cfg):
            raise svc.DomainError("Игра не найдена", 404)
        return pred.match_predictions(db, m, p.id)

    @app.put("/api/matches/{match_id}/prediction")
    def prediction_save(
        match_id: int,
        body: S.PredictionEdit,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        pred.save(db, p.id, m, body)
        return pred.match_predictions(db, m, p.id)

    @app.get("/api/matches/{match_id}/result")
    def result(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id)
        if m.status not in ("approved", "completed"):
            raise svc.DomainError("Результат доступен после утверждения команд", 404)
        return res.result_data(db, m)

    @app.put("/api/matches/{match_id}/result")
    def edit_result(
        match_id: int,
        body: S.ResultEdit,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        return res.save_result(db, p.id, m, body, cfg)

    @app.get("/api/matches/{match_id}/auction")
    def auction_detail(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id, lock=True)
        if m.status == "draft" and not has_admin_access(p, cfg):
            raise svc.DomainError("Игра не найдена", 404)
        return auc.data(db, auc.latest(db, m), p.id)

    @app.get("/api/matches/{match_id}/auctions/history")
    def auction_history(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id, lock=True)
        if m.status == "draft" and not has_admin_access(p, cfg):
            raise svc.DomainError("Игра не найдена", 404)
        return [
            auc.data(db, a, p.id)
            for a in db.scalars(
                select(auc.Auction)
                .where(auc.Auction.match_id == match_id)
                .order_by(auc.Auction.id.desc())
            )
        ]

    @app.post("/api/matches/{match_id}/auction", status_code=201)
    def auction_start(
        match_id: int,
        body: S.AuctionStart,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        return auc.data(db, auc.start(db, p.id, m, body, cfg), p.id)

    @app.post("/api/matches/{match_id}/auction/bids")
    def auction_bid(
        match_id: int,
        body: S.AuctionBid,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        return auc.data(db, auc.bid(db, p.id, m, body, cfg), p.id)

    @app.post("/api/matches/{match_id}/auction/control")
    def auction_control(
        match_id: int,
        body: S.AuctionControl,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        return auc.data(db, auc.control(db, p.id, m, body), p.id)

    return app
