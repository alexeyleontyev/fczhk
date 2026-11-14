"""Isolated real-API fixture for Playwright's betting-line project.

The ordinary demo has no training history. Keep these synthetic matches in a separate
temporary database so archive, leaderboard and freebet tests retain their own empty state.
"""

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import uvicorn
from sqlalchemy import select
from test_betting import _league, _upcoming

from fczhk import odds, wallet
from fczhk.api import create_app
from fczhk.cli import demo_settings, seed_demo
from fczhk.db import database, now
from fczhk.models import Player

if __name__ == "__main__":
    with TemporaryDirectory(prefix="fczhk-betting-e2e-") as directory:
        cfg = demo_settings()
        cfg.database_url = f"sqlite:///{Path(directory) / 'demo.db'}"
        seed_demo(cfg)
        engine, factory = database(cfg.database_url)
        with factory() as db, db.begin():
            field, keepers = _league(db, np.random.default_rng(7))
            odds.refit_if_needed(db)
            for index in range(4):
                match = _upcoming(db, field, keepers)
                match.starts_at = now() + timedelta(days=10 + index)
                match.game_day = match.starts_at.date().isoformat()
                match.location = f"Линия ставок · {index}"
                db.flush()
            player = db.scalar(select(Player).where(Player.telegram_id == 1002))
            wallet.claim_freebet(db, player.id)
        try:
            uvicorn.run(create_app(cfg, factory), host="127.0.0.1", port=8002, log_level="warning")
        finally:
            engine.dispose()
