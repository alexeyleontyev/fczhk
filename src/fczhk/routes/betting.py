from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import bets, odds, wallet
from .. import schemas as S
from .. import services as svc
from ..auth import has_admin_access
from ..models import Player


def router(ctx):
    app = APIRouter()
    cfg = ctx.cfg
    db_dep = ctx.db_dep
    current = ctx.current

    @app.get("/api/wallet")
    def wallet_detail(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        return wallet.wallet_data(db, p.id)

    @app.post("/api/wallet/freebet")
    def claim_freebet(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        wallet.claim_freebet(db, p.id)
        return wallet.wallet_data(db, p.id)

    @app.get("/api/wallet/grants")
    def wallet_grants(
        p: Player = Depends(ctx.admin), db: Session = Depends(db_dep, scope="function")
    ):
        return wallet.grants(db)

    @app.post("/api/wallet/grants", status_code=201)
    def wallet_grant(
        body: S.WalletGrant,
        p: Player = Depends(ctx.admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        wallet.grant(db, p.id, body.player_id, body.amount, body.reason)
        return wallet.grants(db)

    @app.get("/api/betting/leaderboard")
    def betting_leaderboard(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        return wallet.leaderboard(db)

    @app.get("/api/bets")
    def my_bets(p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")):
        return bets.my_bets(db, p.id)

    @app.get("/api/betting/archive")
    def betting_archive(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        return bets.archive(db)

    @app.get("/api/matches/{match_id}/bets")
    def match_bets(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id)
        if m.status == "draft" and not has_admin_access(p, cfg):
            raise svc.DomainError("Игра не найдена", 404)
        return bets.match_bets(db, m)

    @app.get("/api/matches/{match_id}/odds")
    def match_odds(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        # Locked: the first request after approval computes and stores the snapshot.
        m = svc.get_match(db, match_id, lock=True)
        if m.status == "draft" and not has_admin_access(p, cfg):
            raise svc.DomainError("Игра не найдена", 404)
        mine = bets.my_bets(db, p.id, match_id=m.id)
        try:
            snapshot = odds.snapshot(db, m)
        except svc.DomainError as exc:
            if exc.status not in (404, 409):
                raise
            return dict(available=False, reason=exc.message, bets=mine)
        return dict(
            available=True, **odds.view(db, m, snapshot, has_admin_access(p, cfg)), bets=mine
        )

    @app.post("/api/matches/{match_id}/odds/quote")
    def odds_quote(
        match_id: int,
        body: S.OddsQuote,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        snapshot = odds.snapshot(db, m)
        if body.odds_id != snapshot.id:
            raise svc.DomainError("Составы изменились, коэффициенты обновлены", 409)
        return odds.quote(db, snapshot, body.selections)

    @app.post("/api/matches/{match_id}/bets", status_code=201)
    def place_bet(
        match_id: int,
        body: S.BetPlace,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        bet = bets.place(db, p.id, m, body)
        return dict(bet=bets.serialize(bet), wallet=wallet.wallet_data(db, p.id))

    return app
