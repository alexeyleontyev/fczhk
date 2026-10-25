"""Opt-in tests run in isolated schemas of the explicitly configured test database."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from fczhk.config import Settings
from fczhk.models import (
    GameTemplate,
    Match,
    Player,
    Rating,
    RatingHistory,
    RatingState,
    Registration,
)
from fczhk.services import MOSCOW, DomainError, finalize, get_match, register, schedule_tick

URL = os.environ.get("FCZHK_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not URL, reason="Set FCZHK_TEST_DATABASE_URL for isolated PostgreSQL checks"
)


def test_parallel_lineup_confirmation_creates_one_snapshot(pg):
    from fczhk import lineups
    from fczhk.models import TeamSnapshot
    from fczhk.schemas import LineupConfirm

    factory, pid = pg
    cfg = Settings(_env_file=None, env="test")
    with factory() as db, db.begin():
        m = Match(
            game_day="2026-10-02",
            starts_at=datetime(2026, 10, 2, 20, tzinfo=MOSCOW),
            location="Доска",
            status="finalized",
        )
        other = Player(alias="Соперник")
        db.add_all([m, other])
        db.flush()
        db.add_all(
            [
                Registration(match_id=m.id, player_id=p, position="field", selected=True)
                for p in (pid, other.id)
            ]
        )
        db.flush()
        current = lineups.data(db, m, cfg)
        regs = list(db.scalars(select(Registration)))
        body = LineupConfirm(
            version=m.version,
            roster_version=m.roster_version,
            fingerprint=current["fingerprint"],
            assignments={regs[0].id: "white", regs[1].id: "black"},
        )
        mid = m.id

    def confirm(_):
        try:
            with factory() as db, db.begin():
                lineups.confirm(db, pid, get_match(db, mid, body.version, lock=True), body, cfg)
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirm, range(2))) == ["conflict", "ok"]
    with factory() as db:
        assert len(list(db.scalars(select(TeamSnapshot)))) == 1


def test_parallel_lineup_sharing_queues_one_message(pg):
    from fczhk import lineups
    from fczhk.models import Audit, Publication
    from fczhk.schemas import LineupShare

    factory, pid = pg
    cfg = Settings(_env_file=None, env="test")
    with factory() as db, db.begin():
        db.get(GameTemplate, 1).extended_chat_id = "-1001247505259"
        match = Match(
            game_day="2026-10-02",
            starts_at=datetime(2026, 10, 2, 20, tzinfo=MOSCOW),
            location="Доска",
            status="open",
        )
        other = Player(alias="Соперник")
        db.add_all([match, other])
        db.flush()
        db.add_all(
            Registration(match_id=match.id, player_id=p, position="field", paid=True)
            for p in (pid, other.id)
        )
        db.flush()
        current = lineups.data(db, match, cfg)
        regs = sorted(current["players"], key=lambda p: p["registration_id"])
        body = LineupShare(
            version=match.version,
            roster_version=match.roster_version,
            fingerprint=current["fingerprint"],
            assignments={regs[0]["registration_id"]: "white", regs[1]["registration_id"]: "black"},
        )
        mid = match.id

    def share(_):
        with factory() as db, db.begin():
            match = get_match(db, mid, body.version, lock=True)
            return lineups.share(db, db.get(Player, pid), match, body, cfg)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(share, range(2)))
    assert first == second and first["status"] == "pending"
    with factory() as db:
        assert len(list(db.scalars(select(Publication)))) == 1
        assert len(list(db.scalars(select(Audit).where(Audit.action == "lineup.shared")))) == 1
        assert db.get(Match, mid).version == body.version
        assert all(r.team is None for r in db.scalars(select(Registration)))


def test_parallel_archive_edits_keep_one_correction_and_original_import(pg):
    from fczhk.archive import edit_details, metadata_flags
    from fczhk.models import Audit, MatchResult
    from fczhk.schemas import ArchiveDetailsEdit

    factory, actor = pg
    with factory() as db, db.begin():
        match = Match(
            game_day="2026-06-26",
            starts_at=datetime(2026, 6, 26, 12, tzinfo=MOSCOW),
            location="Не указано в историческом источнике",
            status="completed",
        )
        db.add(match)
        db.flush()
        db.add(MatchResult(match_id=match.id, completed=True))
        db.add(Audit(match_id=match.id, action="history.imported", data={"date_only": True}))
        mid, version = match.id, match.version
    body = ArchiveDetailsEdit(
        version=version, game_day="2026-06-26", start_time="20:30", location="Манеж", season="2026"
    )

    def edit(_):
        try:
            with factory() as db, db.begin():
                db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
                match = get_match(db, mid, version, lock=True)
                edit_details(db, actor, match, body)
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == ["conflict", "ok"]
    with factory() as db:
        assert metadata_flags(db, [mid])[mid] == {"historical": True, "time_known": True}
        edits = list(
            db.scalars(select(Audit).where(Audit.action == "match.archive_details_edited"))
        )
        assert len(edits) == 1 and edits[0].data["old"]["time_known"] is False
        assert db.scalar(select(Audit).where(Audit.action == "history.imported")).data == {
            "date_only": True
        }
        assert db.get(MatchResult, mid).completed


def test_parallel_scheduled_announcements_are_created_once(pg):
    from fczhk.models import Publication

    factory, _ = pg
    cfg = Settings(_env_file=None, env="test")
    with factory() as db, db.begin():
        template = db.get(GameTemplate, 1)
        template.enabled, template.location = True, "Поле"
        template.announcements_chat_id = "-1001111111"
        template.announcement_enabled, template.announcement_minutes = True, 30
    at = datetime(2032, 6, 1, 11, 30, tzinfo=MOSCOW)

    def announce(_):
        with factory() as db, db.begin():
            return schedule_tick(db, cfg, at)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(announce, range(4))) == [None] * 4
    with factory() as db:
        posts = list(db.scalars(select(Publication)))
        assert len(posts) == 1 and posts[0].kind == "opening_notice"
        assert posts[0].match_id is None
        assert not list(db.scalars(select(Match)))


@pytest.fixture
def pg(request):
    namespace = "test_mvp1_" + uuid4().hex
    control = create_engine(URL)
    with control.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{namespace}"'))
    engine = create_engine(
        URL,
        pool_timeout=1,
        connect_args={
            "options": f"-csearch_path={namespace} -clock_timeout=5000 -cstatement_timeout=10000"
        },
    )
    config = Config("alembic.ini")
    # Run the real migration on the test connection, not metadata.create_all.
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, getattr(request, "param", "head"))
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db, db.begin():
        db.execute(
            text(
                "INSERT INTO game_template (id, enabled, version, start_time, location, description, cost, payment_details) "
                "VALUES (1, true, 1, '20:00', 'Стадион', '', 0, '')"
            )
        )
        # Old-schema fixtures must not insert columns introduced by later models.
        pid = db.execute(
            text(
                "INSERT INTO players (alias, telegram_id, created_at) VALUES (:name, 5678, now()) RETURNING id"
            ),
            {"name": "Тестовый игрок"},
        ).scalar_one()
    yield factory, pid
    engine.dispose()
    # Only the schema generated by this fixture is removed; no user tables are touched.
    with control.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{namespace}" CASCADE'))
    control.dispose()


@pytest.mark.parametrize("pg", ["0b7c6d9e214f"], indirect=True)
def test_telegram_username_migration_preserves_identity_and_sessions(pg):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from fczhk.db import Base, now
    from fczhk.models import LoginSession

    factory, pid = pg
    with factory() as db, db.begin():
        db.add(LoginSession(token_hash="a" * 64, player_id=pid, expires_at=now()))
    config = Config("alembic.ini")
    with factory.kw["bind"].begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    with factory() as db, db.begin():
        player = db.get(Player, pid)
        assert player.telegram_id == 5678 and player.alias == "Тестовый игрок"
        assert player.telegram_username is None
        assert db.get(LoginSession, "a" * 64).player_id == pid
        player.telegram_username = "saved_username"
    with (
        pytest.raises(ValueError, match="downgrade потеряет данные"),
        factory.kw["bind"].begin() as connection,
    ):
        config.attributes["connection"] = connection
        command.downgrade(config, "0b7c6d9e214f")
    with factory() as db, db.begin():
        assert db.get(Player, pid).telegram_username == "saved_username"
        db.get(Player, pid).telegram_username = None
    with factory.kw["bind"].begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0b7c6d9e214f")
        command.upgrade(config, "head")
    with factory() as db:
        assert db.get(LoginSession, "a" * 64).player_id == pid
        assert db.get(Player, pid).telegram_id == 5678


@pytest.mark.parametrize("pg", ["5b4d82a731cf"], indirect=True)
def test_prediction_history_migration_preserves_merged_names_and_new_predictions(pg):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from fczhk.db import Base, now
    from fczhk.models import Prediction, PredictionBaseline
    from fczhk.predictions import standings
    from fczhk.services import audit, merge_guest

    factory, pid = pg
    with factory() as db, db.begin():
        source = db.scalar(select(Player).where(Player.alias == "Виталя пьяный"))
        source_id = source.id
        merge_guest(db, pid, source_id, pid)
        db.get(Player, pid).alias = "Виталя Легенда 17"
        audit(db, pid, "player.renamed", old="Виталя пьяный", new="Виталя Легенда 17")
        match = Match(
            game_day="2026-10-30",
            starts_at=now(),
            season="2026",
            location="Поле",
            status="approved",
        )
        db.add(match)
        db.flush()
        db.add(
            Prediction(
                match_id=match.id,
                player_id=pid,
                white_score=1,
                black_score=0,
                approved_version=1,
                scoring_version=2,
            )
        )
    config = Config("alembic.ini")
    with factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    with factory() as db:
        assert db.get(Player, pid).alias == "Виталя Легенда 17"
        assert db.get(Player, source_id).merged_into == pid
        assert db.scalar(select(Prediction.scoring_version)) == 2
        baseline = db.get(PredictionBaseline, (source_id, "2026"))
        assert (baseline.points_half, baseline.predictions_count) == (10, 5)
        row = next(r for r in standings(db, "2026") if r["player_id"] == pid)
        assert (row["points"], row["predictions"], row["settled"]) == (5, 6, 5)
        assert row["average_points"] == 5 / 6


@pytest.mark.parametrize("pg", ["f97c3e8d210a"], indirect=True)
def test_notification_migration_preserves_games_posts_and_settings_and_guards_downgrade(pg):
    from fczhk.models import Publication

    factory, _ = pg
    with factory() as db, db.begin():
        db.execute(text("UPDATE game_template SET enabled=false, version=7, start_time='20:30'"))
        match = Match(
            game_day="2032-06-04",
            starts_at=datetime(2032, 6, 4, 20, 30, tzinfo=MOSCOW),
            location="Манеж",
            status="open",
        )
        db.add(match)
        db.flush()
        mid = match.id
        db.execute(
            text(
                "INSERT INTO publications (match_id, kind, version, text, status, attempts, message_ids, chat_id, stale, stale_marked, next_attempt_at) "
                "VALUES (:mid, 'collection', 1, 'Старый пост', 'sent', 1, '[]', '-1005678', false, false, now())"
            ),
            {"mid": mid},
        )
    config = Config("alembic.ini")
    with factory.kw["bind"].begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    with factory() as db, db.begin():
        template = db.get(GameTemplate, 1)
        assert not template.enabled and template.version == 7 and template.start_time == "20:30"
        assert template.announcements_chat_id == template.extended_chat_id == ""
        assert (
            template.extended_auction_enabled
            and template.extended_registration_enabled
            and template.extended_cancellation_enabled
        )
        old = db.scalar(select(Publication))
        assert old.text == "Старый пост" and old.match_id == mid and old.dedupe_key is None
        assert not template.announcement_enabled and not template.payment_reminder_enabled
        db.add(
            Publication(kind="opening_notice", version=1, dedupe_key="opening:test", text="Анонс")
        )
    with (
        pytest.raises(ValueError, match="downgrade потеряет данные"),
        factory.kw["bind"].begin() as connection,
    ):
        config.attributes["connection"] = connection
        command.downgrade(config, "f97c3e8d210a")
    with factory() as db:
        assert db.get(Match, mid).location == "Манеж"
        assert len(list(db.scalars(select(Publication)))) == 2


@pytest.mark.parametrize("custom", [False, True])
def test_real_migration_scheduler_and_concurrent_duplicate_join(pg, custom):
    factory, pid = pg
    cfg = Settings(_env_file=None, env="test")
    at = datetime(2026, 9, 15, 12, tzinfo=MOSCOW)
    if custom:
        with factory() as db, db.begin():
            template = db.get(GameTemplate, 1)
            template.opening_weekday, template.opening_time = 6, "23:45"
            template.game_weekday, template.start_time = 0, "00:15"
        at = datetime.fromisoformat("2026-10-18T21:00:00+00:00")

    def schedule(_):
        with factory() as db, db.begin():
            return schedule_tick(db, cfg, at)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(schedule, range(4)))
    assert sum(r is not None for r in results) == 1
    mid = next(r for r in results if r is not None)

    def join(_):
        with factory() as db, db.begin():
            register(db, pid, get_match(db, mid, lock=True), "field")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(join, range(4)))
    with factory() as db:
        assert len(list(db.scalars(select(Registration)))) == 1


def test_parallel_finalization_rejects_stale_version(pg):
    factory, pid = pg
    with factory() as db, db.begin():
        m = Match(
            game_day="2026-10-02",
            starts_at=datetime(2026, 10, 2, 20, tzinfo=MOSCOW),
            location="Стадион",
            status="open",
        )
        db.add(m)
        db.flush()
        mid, version = m.id, m.version

    def finish(_):
        try:
            with factory() as db, db.begin():
                finalize(db, pid, get_match(db, mid, version, lock=True))
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, range(2)))
    assert sorted(results) == ["conflict", "ok"]


def test_concurrent_rating_edits_do_not_lose_history(pg):
    from fczhk.ratings import aggregate, save_rating
    from fczhk.schemas import RatingEdit

    factory, pid = pg
    with factory() as db, db.begin():
        assert db.get(RatingState, 1) is not None
        target = Player(alias="Оцениваемый", telegram_id=5679)
        db.add(target)
        db.flush()
        target_id = target.id

    def rate(value):
        try:
            with factory() as db, db.begin():
                save_rating(
                    db,
                    pid,
                    target_id,
                    RatingEdit(position="field", attack=value, defense=3, revision=0),
                )
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rate, [2, 4]))
    assert sorted(results) == ["conflict", "ok"]
    with factory() as db:
        assert len(list(db.scalars(select(Rating)))) == 1
        assert len(list(db.scalars(select(RatingHistory)))) == 1
        assert aggregate(db, [target_id])[(target_id, "field")][2] == 1


@pytest.mark.parametrize("operation", ["approve", "temporary"])
def test_guest_link_between_request_read_and_rating_lock_uses_current_identity(pg, operation):
    from fczhk.models import TeamRatingSnapshot, TeamSnapshot
    from fczhk.ratings import save_rating, set_temporary
    from fczhk.schemas import RatingEdit, RatingValues
    from fczhk.services import approve, merge_guest

    factory, actor = pg
    with factory() as db, db.begin():
        guest = Player(alias="Гость")
        target = Player(alias="Зарегистрированный", telegram_id=9876)
        m = Match(
            game_day="2026-10-02",
            starts_at=datetime(2026, 10, 2, 20, tzinfo=MOSCOW),
            location="Стадион",
            status="finalized",
        )
        db.add_all([guest, target, m])
        db.flush()
        reg = Registration(
            match_id=m.id, player_id=guest.id, position="field", selected=True, team="white"
        )
        db.add_all(
            [
                reg,
                Registration(
                    match_id=m.id, player_id=actor, position="field", selected=True, team="black"
                ),
            ]
        )
        save_rating(
            db, actor, target.id, RatingEdit(position="field", attack=5, defense=3, revision=0)
        )
        mid, rid, guest_id, target_id = m.id, reg.id, guest.id, target.id

    with factory() as request, request.begin():
        match = get_match(request, mid, lock=True)
        cached = request.get(Registration, rid)
        assert cached.player_id == guest_id
        # A different request links the card while this request has already read it.
        with factory() as linking, linking.begin():
            merge_guest(linking, actor, guest_id, target_id)
        with factory() as check:
            assert check.get(Player, target_id).alias == "Гость"
            assert check.get(Player, guest_id).merged_into == target_id
            assert list(check.scalars(select(Player.id).where(Player.alias == "Гость"))) == [
                target_id
            ]
        if operation == "temporary":
            with pytest.raises(DomainError, match="Есть оценки сообщества"):
                set_temporary(
                    request,
                    actor,
                    match,
                    cached,
                    RatingValues(position="field", attack=1, defense=1),
                )
        else:
            approve(request, actor, match, Settings(_env_file=None, env="test"))
            request.flush()
            teams = request.scalar(select(TeamSnapshot))
            assert {p["player_id"] for p in teams.teams} == {actor, target_id}
            ratings = request.get(TeamRatingSnapshot, teams.id)
            assert {p["player_id"] for p in ratings.data["inputs"]} == {actor, target_id}
            assert ratings.data["frozen"] is True


@pytest.mark.parametrize("pg", ["990662d3f1e7"], indirect=True)
def test_upgrade_from_mvp1_preserves_data_and_matches_metadata(pg):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from fczhk.db import Base

    factory, pid = pg
    with factory() as db, db.begin():
        # Both the old player and the new singleton survive a migration rerun.
        conn = db.connection()
        config = Config("alembic.ini")
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert db.get(Player, pid).alias == "Тестовый игрок"
        assert db.get(RatingState, 1).revision == 0
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert differences == []


@pytest.mark.parametrize("pg", ["a71f4b6d2e90"], indirect=True)
def test_schedule_migration_preserves_settings_and_blocks_loss_on_downgrade(pg):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy.exc import IntegrityError

    from fczhk.db import Base

    factory, _ = pg
    with factory() as db, db.begin():
        db.execute(text("UPDATE game_template SET enabled=false, version=7, start_time='21:35'"))
    config = Config("alembic.ini")
    with factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    with factory() as db, db.begin():
        template = db.get(GameTemplate, 1)
        assert not template.enabled and template.version == 7 and template.start_time == "21:35"
        assert template.location == "Стадион"
        assert (template.opening_weekday, template.opening_time, template.game_weekday) == (
            1,
            "12:00",
            4,
        )
        template.opening_weekday, template.opening_time = 6, "23:45"
        template.game_weekday, template.start_time = 0, "00:15"
    with pytest.raises(ValueError, match="потеряет настройки"), factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "a71f4b6d2e90")
    with pytest.raises(IntegrityError), factory() as db, db.begin():
        db.get(GameTemplate, 1).opening_weekday = 7
        db.flush()
    with factory() as db:
        assert db.get(GameTemplate, 1).opening_weekday == 6


@pytest.mark.parametrize("pg", ["9c2d8f4a10b7"], indirect=True)
def test_administrator_migration_preserves_players_and_refuses_to_drop_role_decisions(pg):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from fczhk.db import Base

    factory, pid = pg
    config = Config("alembic.ini")
    with factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    with factory() as db, db.begin():
        player = db.get(Player, pid)
        assert player.alias == "Тестовый игрок"
        assert player.admin_access is None and player.admin_access_revision == 0
        # Even a revocation must survive: losing it could restore legacy access.
        player.admin_access = False
        player.admin_access_revision = 1
    with pytest.raises(ValueError, match="решения владельца"), factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "9c2d8f4a10b7")
    with factory() as db:
        assert db.get(Player, pid).admin_access is False


def test_concurrent_administrator_changes_reject_stale_revision(pg):
    from fczhk.administrators import change
    from fczhk.models import Audit
    from fczhk.schemas import AdminAccessEdit

    factory, owner_id = pg
    cfg = Settings(_env_file=None, env="test", owner_id=5678)
    with factory() as db, db.begin():
        target = Player(alias="Будущий администратор", telegram_id=987654)
        db.add(target)
        db.flush()
        target_id = target.id

    def grant(_):
        try:
            with factory() as db, db.begin():
                change(
                    db,
                    cfg,
                    db.get(Player, owner_id),
                    target_id,
                    AdminAccessEdit(is_admin=True, revision=0),
                )
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(grant, range(2))) == ["conflict", "ok"]
    with factory() as db:
        player = db.get(Player, target_id)
        assert player.admin_access and player.admin_access_revision == 1
        assert (
            len(list(db.scalars(select(Audit).where(Audit.action == "administrator.granted")))) == 1
        )


@pytest.mark.parametrize("pg", ["8b1d6a0c42ef"], indirect=True)
def test_names_and_unknown_own_goal_migration_preserves_data_and_refuses_loss(pg):
    from sqlalchemy.exc import IntegrityError

    from fczhk.db import now
    from fczhk.models import MatchResult, ResultGoal

    factory, pid = pg
    with factory() as db, db.begin():
        duplicate_id = db.execute(
            text("INSERT INTO players (alias, created_at) VALUES (:name, now()) RETURNING id"),
            {"name": "Тестовый игрок"},
        ).scalar_one()
    config = Config("alembic.ini")
    with pytest.raises(ValueError, match="повторяющиеся имена"), factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    with factory() as db, db.begin():
        db.execute(text("DELETE FROM players WHERE id = :id"), {"id": duplicate_id})
    with factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
    with factory() as db, db.begin():
        assert db.get(Player, pid).alias == "Тестовый игрок"
        match = Match(game_day="2026-10-09", starts_at=now(), location="Поле", status="completed")
        db.add(match)
        db.flush()
        db.add(MatchResult(match_id=match.id, completed=True))
        db.flush()
        db.add(ResultGoal(match_id=match.id, id=str(uuid4()), team="white", kind="own_goal"))
        db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(Player(alias="Тестовый игрок"))
            db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(ResultGoal(match_id=match.id, id=str(uuid4()), team="white", kind="invalid"))
            db.flush()
    with pytest.raises(ValueError, match="уточните авторов"), factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "8b1d6a0c42ef")
    with factory() as db:
        assert db.scalar(select(ResultGoal)).author_id is None


def test_concurrent_telegram_registration_keeps_names_unique(pg):
    from threading import Barrier

    from fczhk.auth import player_for_telegram

    factory, _ = pg
    ready = Barrier(2)

    def register_user(tid):
        ready.wait(timeout=5)
        with factory() as db, db.begin():
            player = player_for_telegram(db, tid, "Одинаковое имя")
            return player.id, player.alias

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(register_user, [7001, 7002]))
    assert len({pid for pid, _ in created}) == len({alias for _, alias in created}) == 2
    assert "Одинаковое имя" in {alias for _, alias in created}
    with factory() as db, db.begin():
        for tid, (pid, alias) in zip([7001, 7002], created, strict=True):
            player = player_for_telegram(db, tid, "Теперь другое имя")
            assert (player.id, player.alias) == (pid, alias)


def test_concurrent_result_edits_are_atomic(pg):
    from datetime import timedelta

    from fczhk.db import now
    from fczhk.models import MatchResult, Publication, ResultGoal, ResultParticipant
    from fczhk.results import save_result
    from fczhk.schemas import ResultEdit

    factory, actor = pg
    cfg = Settings(_env_file=None, env="test", publication_chat_id="-1005678")
    with factory() as db, db.begin():
        other = Player(alias="Соперник", telegram_id=9999)
        match = Match(
            game_day="2020-01-03",
            starts_at=now() - timedelta(days=1),
            location="Поле",
            status="approved",
        )
        db.add_all([other, match])
        db.flush()
        mid, version, oid = match.id, match.version, other.id
    body = ResultEdit(
        version=version,
        completed=True,
        participants=[
            dict(player_id=actor, team="white", position="field"),
            dict(player_id=oid, team="black", position="keeper"),
        ],
        goals=[dict(id=str(uuid4()), team="white", author_id=actor)],
    )

    def save(_):
        try:
            with factory() as db, db.begin():
                save_result(db, actor, get_match(db, mid, version, lock=True), body, cfg)
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, range(2))) == ["conflict", "ok"]
    with factory() as db:
        posts = list(db.scalars(select(Publication).where(Publication.kind == "result")))
        assert len(posts) == 1 and posts[0].chat_id == cfg.publication_chat_id
    with factory() as db:
        assert db.get(MatchResult, mid).completed
        assert len(list(db.scalars(select(ResultGoal)))) == 1
        assert len(list(db.scalars(select(ResultParticipant)))) == 2


def test_simultaneous_auction_bids_resolve_once_and_persist(pg):
    from fczhk.auctions import bid, data, start
    from fczhk.db import now
    from fczhk.models import Auction, AuctionLot, Publication
    from fczhk.schemas import AuctionBid, AuctionStart

    factory, actor = pg
    cfg = Settings(_env_file=None, env="test", publication_chat_id="-1005678")
    with factory() as db, db.begin():
        db.get(GameTemplate, 1).extended_chat_id = "-1005678"
        people = [Player(alias=f"Торги {i}", telegram_id=6000 + i) for i in range(3)]
        m = Match(game_day="2020-01-03", starts_at=now(), location="Поле", status="finalized")
        db.add_all([m, *people])
        db.flush()
        ids = [actor, *[p.id for p in people]]
        for pid in ids:
            db.add(Registration(match_id=m.id, player_id=pid, position="field", selected=True))
        db.flush()
        a = start(
            db,
            actor,
            m,
            AuctionStart(version=m.version, white_captain=actor, black_captain=ids[1]),
            cfg,
        )
        view = data(db, a, actor)
        mid, aid, lot, other = m.id, a.id, view["current"]["id"], ids[1]

    def submit(player):
        with factory() as db, db.begin():
            bid(
                db,
                player,
                get_match(db, mid, lock=True),
                AuctionBid(auction_id=aid, lot_id=lot, amount=1 if player == actor else 0),
                cfg,
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(submit, [actor, other, actor, other]))
    with factory() as db:
        a = db.get(Auction, aid)
        assert a.status == "completed"
        assert a.white_budget == 99 and a.black_budget == 100
        assert len(a.state["assignments"]) == 4
        assert len(list(db.scalars(select(AuctionLot)))) == 1
        messages = list(db.scalars(select(Publication).where(Publication.kind == "auction_lot")))
        assert len(messages) == 2  # One winning lot and one free assignment, despite replayed bids.
        opened = list(db.scalars(select(Publication).where(Publication.kind == "auction_open")))
        assert len(opened) == 1 and "Новый лот 1 · круг 1" in opened[0].text
        assert all("Текущие команды" in message.text for message in [*opened, *messages])
        free = next(message for message in messages if "Без торгов" in message.text)
        assert "⚪ Белые · полевые 2/2" in free.text and "⚫ Чёрные · полевые 2/2" in free.text
        assert data(db, a, actor)["prices"] == {
            str(lot.registration_id): 1 for lot in db.scalars(select(AuctionLot))
        } | {str(rid): 0 for rid in a.state["automatic"]}


def test_concurrent_prediction_edit_rejects_stale_revision(pg):
    from datetime import timedelta

    from fczhk.db import now
    from fczhk.models import Prediction
    from fczhk.predictions import save
    from fczhk.schemas import PredictionEdit

    factory, actor = pg
    with factory() as db, db.begin():
        m = Match(
            game_day="2030-01-03",
            starts_at=now() + timedelta(days=1),
            location="Поле",
            status="approved",
            approved_version=1,
        )
        db.add(m)
        db.flush()
        mid = m.id

    def submit(amount):
        try:
            with factory() as db, db.begin():
                save(
                    db,
                    actor,
                    get_match(db, mid, lock=True),
                    PredictionEdit(
                        white_score=amount, black_score=0, revision=0, approved_version=1
                    ),
                )
            return "ok"
        except DomainError as exc:
            assert exc.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, [1, 2])) == ["conflict", "ok"]
    with factory() as db:
        predictions = list(db.scalars(select(Prediction)))
        assert len(predictions) == 1 and predictions[0].revision == 1


def test_prediction_deadline_is_checked_after_waiting_for_match_lock(pg, monkeypatch):
    from datetime import timedelta
    from threading import Event

    from fczhk.db import now
    from fczhk.models import Prediction
    from fczhk.predictions import save
    from fczhk.schemas import PredictionEdit

    factory, actor = pg
    start = now() + timedelta(minutes=1)
    clock = [start - timedelta(seconds=1)]
    monkeypatch.setattr("fczhk.predictions.now", lambda: clock[0])
    with factory() as db, db.begin():
        m = Match(
            game_day="2030-01-03",
            starts_at=start,
            location="Поле",
            status="approved",
            approved_version=1,
        )
        db.add(m)
        db.flush()
        mid = m.id
    waiting = Event()

    def submit():
        try:
            with factory() as db, db.begin():
                waiting.set()
                save(
                    db,
                    actor,
                    get_match(db, mid, lock=True),
                    PredictionEdit(white_score=1, black_score=0, revision=0, approved_version=1),
                )
        except DomainError as exc:
            return exc.status
        return 200

    with ThreadPoolExecutor(max_workers=1) as pool:
        with factory() as lock, lock.begin():
            get_match(lock, mid, lock=True)
            future = pool.submit(submit)
            assert waiting.wait(5)
            clock[0] = start
        assert future.result(timeout=5) == 409
    with factory() as db:
        assert list(db.scalars(select(Prediction))) == []


async def test_parallel_api_reads_do_not_starve_connection_pool(pg):
    import asyncio

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import event

    from fczhk.api import create_app
    from fczhk.auth import create_session

    factory, pid = pg
    cfg = Settings(_env_file=None, env="test")
    with factory() as db, db.begin():
        token = create_session(db, cfg, db.get(Player, pid))
    engine = factory.kw["bind"]

    # Reproduce contention even on fast CI machines: each checked-out connection
    # remains busy while the event loop must continue to release other requests.
    def pause(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT"):
            cursor.execute("SELECT pg_sleep(0.005)")

    event.listen(engine, "before_cursor_execute", pause)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=create_app(cfg, factory)), base_url="http://test"
        ) as client:
            responses = await asyncio.wait_for(
                asyncio.gather(
                    *[
                        client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
                        for _ in range(30)
                    ]
                ),
                timeout=10,
            )
        assert all(response.status_code == 200 for response in responses)
    finally:
        event.remove(engine, "before_cursor_execute", pause)


async def test_simultaneous_login_of_same_identity_commits_without_event_loop_lock(pg, monkeypatch):
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from fczhk.api import create_app
    from fczhk.models import LoginSession
    from tests.helpers import signed_data

    factory, _ = pg
    cfg = Settings(_env_file=None, env="test", bot_token="123:test")
    reached = 0
    ready = asyncio.Event()

    async def check_member(*args):
        nonlocal reached
        reached += 1
        if reached == 2:
            ready.set()
        await ready.wait()

    monkeypatch.setattr("fczhk.auth.check_member", check_member)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(cfg, factory)), base_url="http://test"
    ) as client:
        responses = await asyncio.wait_for(
            asyncio.gather(
                *[
                    client.post(
                        "/api/auth/telegram", json={"init_data": signed_data(cfg.bot_token)}
                    )
                    for _ in range(2)
                ]
            ),
            timeout=10,
        )
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["token"] != responses[1].json()["token"]
    with factory() as db:
        assert len(list(db.scalars(select(LoginSession)))) == 2
        assert len(list(db.scalars(select(Player).where(Player.telegram_id == 102)))) == 1


@pytest.mark.parametrize("pg", ["e6b2f48a913c"], indirect=True)
def test_season_migration_preserves_matches_and_refuses_loss(pg):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from fczhk.db import Base

    factory, _ = pg
    with factory() as db, db.begin():
        mid = db.execute(
            text(
                "INSERT INTO matches (game_day, starts_at, location, description, cost, payment_details, status, version, roster_version, field_limit, keeper_limit, created_at) VALUES ('2026-06-05', '2026-06-05T20:30:00+03:00', 'История', '', 0, '', 'completed', 3, 2, 16, 2, now()) RETURNING id"
            )
        ).scalar_one()
    config = Config("alembic.ini")
    with factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    with factory() as db, db.begin():
        match = db.get(Match, mid)
        assert (match.season, match.version, match.roster_version, match.location) == (
            "2026",
            3,
            2,
            "История",
        )
        match.season = "2024-2025"
    with pytest.raises(ValueError, match="потеряет разделение"), factory.kw["bind"].begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "e6b2f48a913c")
    with factory() as db:
        assert db.get(Match, mid).season == "2024-2025"
