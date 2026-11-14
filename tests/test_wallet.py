from datetime import UTC, datetime

import pytest

from fczhk import wallet
from fczhk.db import now
from fczhk.models import Bet, Match, MatchOdds, Player, PricingModel, WalletEntry
from fczhk.services import DomainError

MONDAY = datetime(2026, 11, 16, 0, 0, tzinfo=wallet.MOSCOW)
SUNDAY_LATE = datetime(2026, 11, 15, 23, 59, tzinfo=wallet.MOSCOW)


def _bet(db, player_id, stake=1000):
    """A bet row for journal entries that must point at a bet."""
    match = db.query(Match).filter_by(game_day="2026-01-01").one_or_none()
    if match is None:
        match = Match(game_day="2026-01-01", starts_at=now(), location="Поле")
        model = PricingModel(data={}, n_matches=0, source_updated_at=now())
        db.add_all([match, model])
        db.flush()
        db.add(
            MatchOdds(
                match_id=match.id, approved_version=1, model_id=model.id, inputs={}, markets=[]
            )
        )
        db.flush()
    odds = db.query(MatchOdds).filter_by(match_id=match.id).one()
    bet = Bet(
        player_id=player_id,
        match_id=match.id,
        odds_id=odds.id,
        approved_version=1,
        selections=["1x2:a"],
        labels=["x"],
        stake=stake,
        odds=200,
        status="won",
        credited=0,
    )
    db.add(bet)
    db.flush()
    return bet.id


def test_weeks_start_on_moscow_monday():
    assert wallet.week_key(SUNDAY_LATE) == "2026-W46"
    assert wallet.week_key(MONDAY) == "2026-W47"
    # 21:30 UTC on Sunday is already Monday in Moscow
    assert wallet.week_key(datetime(2026, 11, 15, 21, 30, tzinfo=UTC)) == "2026-W47"
    assert wallet.next_week_start(SUNDAY_LATE) == MONDAY
    assert wallet.next_week_start(MONDAY) == datetime(2026, 11, 23, tzinfo=wallet.MOSCOW)
    assert wallet.week_key(datetime(2027, 1, 1, 12, tzinfo=wallet.MOSCOW)) == "2026-W53"


def test_freebet_once_a_week_and_balance(call):
    empty = call("GET", "/wallet", role="player")
    assert (
        empty["balance"] == 0 and empty["freebet"]["available"] is True and empty["entries"] == []
    )
    assert empty["freebet"]["amount"] == 100
    claimed = call("POST", "/wallet/freebet", role="player")
    assert claimed["balance"] == 100 and claimed["freebets"] == 100 and claimed["profit"] == 0
    assert claimed["freebet"]["available"] is False
    assert claimed["entries"][0]["kind"] == "freebet" and claimed["entries"][0]["amount"] == 100
    again = call("POST", "/wallet/freebet", role="player", expected=409)
    assert "уже получен" in again["detail"]
    assert call("GET", "/wallet", role="player")["balance"] == 100
    # the other player's wallet is separate
    assert call("GET", "/wallet", role="admin")["balance"] == 0


def test_freebets_accumulate_week_by_week_and_unclaimed_weeks_are_lost(env):
    _, factory, _, _, ids = env
    pid = ids["player"]
    with factory() as db, db.begin():
        wallet.claim_freebet(db, pid, at=SUNDAY_LATE)
        with pytest.raises(DomainError):
            wallet.claim_freebet(db, pid, at=datetime(2026, 11, 10, 9, tzinfo=wallet.MOSCOW))
        wallet.claim_freebet(db, pid, at=MONDAY)
        # two weeks skipped: still a single freebet when the player comes back
        wallet.claim_freebet(db, pid, at=datetime(2026, 12, 9, 15, tzinfo=wallet.MOSCOW))
        data = wallet.wallet_data(db, pid, at=datetime(2026, 12, 9, 16, tzinfo=wallet.MOSCOW))
    assert data["balance"] == 300 and data["freebet"]["available"] is False
    assert data["freebet"]["next_at"] == datetime(2026, 12, 14, tzinfo=wallet.MOSCOW)
    assert [e["week"] for e in data["entries"]] == ["2026-W50", "2026-W47", "2026-W46"]


def test_leaderboard_and_bank(env, call):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        ghost = Player(alias="Старая карточка")
        db.add(ghost)
        db.flush()
        # A historical card merged into the player: its points belong to the player.
        ghost.merged_into = ids["player"]
        at = now()
        db.add_all(
            [
                WalletEntry(
                    player_id=ghost.id,
                    kind="freebet",
                    amount=10000,
                    freebet_week="2026-W01",
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["player"],
                    kind="freebet",
                    amount=10000,
                    freebet_week="2026-W02",
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["player"],
                    kind="stake",
                    amount=-5000,
                    bet_id=_bet(db, ids["player"]),
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["player"],
                    kind="payout",
                    amount=12550,
                    bet_id=_bet(db, ids["player"]),
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["admin"],
                    kind="freebet",
                    amount=10000,
                    freebet_week="2026-W02",
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["admin"],
                    kind="stake",
                    amount=-8000,
                    bet_id=_bet(db, ids["admin"]),
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["admin"],
                    kind="stake",
                    amount=-2000,
                    bet_id=_bet(db, ids["admin"]),
                    created_at=at,
                ),
                WalletEntry(
                    player_id=ids["admin"],
                    kind="refund",
                    amount=2000,
                    bet_id=_bet(db, ids["admin"]),
                    created_at=at,
                ),
            ]
        )
    board = call("GET", "/betting/leaderboard", role="player")
    rows = {r["alias"]: r for r in board["rows"]}
    assert [r["alias"] for r in board["rows"]] == ["Игрок", "Администратор"]
    assert rows["Игрок"] == dict(
        rank=1,
        player_id=ids["player"],
        alias="Игрок",
        balance=275.5,
        freebets=200,
        profit=75.5,
        staked=50,
    )
    assert rows["Администратор"]["balance"] == 20 and rows["Администратор"]["profit"] == -80
    # the bank took 150 in stakes, paid back 125.50 and refunded 20
    assert board["bank"] == dict(balance=4.5, in_play=0, staked=150, paid_out=125.5, refunded=20)
    assert board["freebets_issued"] == 300 and board["players"] == 2
    assert call("GET", "/wallet", role="player")["balance"] == 275.5


def test_ties_share_a_rank_and_the_bank_can_be_negative(env):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        at = now()
        for pid in (ids["player"], ids["admin"]):
            db.add(
                WalletEntry(
                    player_id=pid,
                    kind="freebet",
                    amount=10000,
                    freebet_week="2026-W02",
                    created_at=at,
                )
            )
            db.add(
                WalletEntry(
                    player_id=pid, kind="stake", amount=-10000, bet_id=_bet(db, pid), created_at=at
                )
            )
            db.add(
                WalletEntry(
                    player_id=pid, kind="payout", amount=30000, bet_id=_bet(db, pid), created_at=at
                )
            )
        board = wallet.leaderboard(db)
    assert [r["rank"] for r in board["rows"]] == [1, 1]
    assert board["bank"]["balance"] == -400


def test_wallet_needs_login(call):
    call("GET", "/wallet", role=None, expected=401)
    call("POST", "/wallet/freebet", role=None, expected=401)
    call("GET", "/betting/leaderboard", role=None, expected=401)


def test_wallet_migration_matches_models_and_guards_downgrade(tmp_path):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, text

    from fczhk.db import Base

    engine = create_engine(f"sqlite:///{tmp_path}/migration.db")
    cfg = Config("alembic.ini")
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
        conn.execute(
            text("INSERT INTO players (id, alias, created_at) VALUES (9001, 'Игрок', '2026-01-01')")
        )
        conn.execute(
            text(
                "INSERT INTO wallet_entries (player_id, kind, amount, freebet_week, created_at) "
                "VALUES (9001, 'freebet', 10000, '2026-W46', '2026-11-10')"
            )
        )
        with pytest.raises(Exception, match="UNIQUE"):
            conn.execute(
                text(
                    "INSERT INTO wallet_entries (player_id, kind, amount, freebet_week, created_at) "
                    "VALUES (9001, 'freebet', 10000, '2026-W46', '2026-11-11')"
                )
            )
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        with pytest.raises(RuntimeError, match="журнал ставок"):
            command.downgrade(cfg, "d7a4c2e910bf")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM wallet_entries"))
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "d7a4c2e910bf")
        assert (
            conn.execute(
                text("SELECT name FROM sqlite_master WHERE name = 'wallet_entries'")
            ).first()
            is None
        )
