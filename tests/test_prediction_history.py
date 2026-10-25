from datetime import timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from fczhk.db import Base, database, now
from fczhk.models import Match, MatchResult, Player, Prediction, PredictionBaseline, ResultGoal
from fczhk.predictions import standings
from fczhk.services import audit, merge_guest


def test_sheet_refresh_preserves_links_and_new_forecasts_and_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'history.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "5b4d82a731cf")
    engine, factory = database(url)
    with factory() as db, db.begin():
        source = db.scalar(select(Player).where(Player.alias == "Виталя пьяный"))
        target = Player(alias="Виталя Легенда 17", telegram_id=102)
        db.add(target)
        db.flush()
        mid_source, target_id = source.id, target.id
        merge_guest(db, target.id, source.id, target.id)
        target.alias = "Виталя Легенда 17"
        audit(
            db,
            target.id,
            "player.renamed",
            player_id=target.id,
            old="Виталя пьяный",
            new=target.alias,
        )
        renamed = db.scalar(select(Player).where(Player.alias == "Андреас"))
        renamed.alias = "Андреас новое имя"
        audit(db, renamed.id, "player.renamed", old="Андреас", new=renamed.alias)
        match = Match(game_day="2026-10-24", starts_at=now(), location="Поле", status="completed")
        db.add(match)
        db.flush()
        db.add(MatchResult(match_id=match.id, completed=True))
        db.flush()
        db.add(ResultGoal(match_id=match.id, id="goal", team="white", kind="goal"))
        db.add_all(
            [
                Prediction(
                    match_id=match.id,
                    player_id=target.id,
                    white_score=1,
                    black_score=0,
                    approved_version=1,
                    scoring_version=2,
                ),
                Prediction(
                    match_id=match.id,
                    player_id=renamed.id,
                    white_score=1,
                    black_score=0,
                    approved_version=1,
                    scoring_version=1,
                ),
            ]
        )
        db.flush()
        forecasts = db.execute(text("SELECT * FROM predictions ORDER BY player_id")).all()
        people_count = db.scalar(select(func.count()).select_from(Player))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with factory() as db, db.begin():
        assert db.execute(text("SELECT * FROM predictions ORDER BY player_id")).all() == forecasts
        assert db.scalar(select(func.count()).select_from(Player)) == people_count
        assert db.get(Player, mid_source).merged_into == target_id
        assert db.get(Player, target_id).alias == "Виталя Легенда 17"
        assert db.scalar(select(func.sum(PredictionBaseline.points_half))) == 214
        assert db.scalar(select(func.sum(PredictionBaseline.predictions_count))) == 133
        table = standings(db, "2026")
        vitaly = next(r for r in table if r["player_id"] == target_id)
        assert (vitaly["baseline_points"], vitaly["baseline_predictions"]) == (5, 5)
        assert (vitaly["points"], vitaly["predictions"], vitaly["settled"]) == (7, 6, 6)
        assert vitaly["average_points"] == 7 / 6
        assert not any(r["player_id"] == mid_source for r in table)
        andreas = next(r for r in table if r["alias"] == "Андреас новое имя")
        assert (andreas["points"], andreas["predictions"]) == (4, 5)
        assert andreas["average_points"] == 0.8
        assert sum(r["points"] for r in table) == 109
        assert sum(r["predictions"] for r in table) == 134
        assert standings(db, "2025") == []
        assert compare_metadata(MigrationContext.configure(db.connection()), Base.metadata) == []
        baseline = db.get(PredictionBaseline, (mid_source, "2026"))
        for attribute in ("points_half", "predictions_count"):
            with pytest.raises(IntegrityError), db.begin_nested():
                setattr(baseline, attribute, -1)
                db.flush()
    engine.dispose()


def test_ambiguous_sheet_identity_is_rejected_before_schema_or_data_changes(tmp_path):
    url = f"sqlite:///{tmp_path / 'ambiguous.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "5b4d82a731cf")
    engine, factory = database(url)
    with factory() as db, db.begin():
        other = db.scalar(select(Player).where(Player.alias == "Чез"))
        audit(db, other.id, "player.renamed", old="Андреас", new=other.alias)
    with pytest.raises(ValueError, match="Неоднозначная"):
        command.upgrade(config, "head")
    with engine.connect() as conn:
        assert "predictions_count" not in {
            c["name"] for c in inspect(conn).get_columns("prediction_baselines")
        }
        assert conn.scalar(text("SELECT sum(points_half) FROM prediction_baselines")) == 182
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "5b4d82a731cf"
    engine.dispose()


def test_count_and_average_include_history_and_pending_predictions_without_recounting_legacy(
    env, call
):
    factory, ids = env[1], env[4]
    with factory() as db, db.begin():
        db.add(
            PredictionBaseline(
                player_id=ids["player"],
                season="2026",
                points_half=9,
                predictions_count=3,
                source="sheet",
            )
        )
        db.add(
            PredictionBaseline(
                player_id=ids["admin"],
                season="2026",
                points_half=0,
                predictions_count=0,
                source="sheet",
            )
        )
        match = Match(
            game_day="2026-10-30",
            starts_at=now() + timedelta(days=2),
            season="2026",
            location="Поле",
            status="approved",
        )
        db.add(match)
        db.flush()
        db.add(
            Prediction(
                match_id=match.id,
                player_id=ids["player"],
                white_score=1,
                black_score=0,
                scoring_version=2,
                approved_version=1,
            )
        )
        db.add(
            Prediction(
                match_id=match.id,
                player_id=ids["admin"],
                white_score=1,
                black_score=0,
                scoring_version=1,
                approved_version=1,
            )
        )
    rows = call("GET", "/predictions/standings?season=2026")
    mine = next(r for r in rows if r["player_id"] == ids["player"])
    assert (mine["points"], mine["predictions"], mine["settled"]) == (4.5, 4, 3)
    assert mine["average_points"] == 1.125
    admin = next(r for r in rows if r["player_id"] == ids["admin"])
    assert admin["predictions"] == 0 and admin["average_points"] is None
    assert call("GET", "/predictions/standings?season=absent") == []
