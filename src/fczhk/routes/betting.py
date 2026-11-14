from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import wallet
from ..models import Player


def router(ctx):
    app = APIRouter()
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

    @app.get("/api/betting/leaderboard")
    def betting_leaderboard(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        return wallet.leaderboard(db)

    return app
