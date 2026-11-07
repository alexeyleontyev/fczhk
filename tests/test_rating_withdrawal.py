from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from fczhk.models import ImportedRating, Player, RatingHistory
from fczhk.ratings import field_opinions
from tests.test_rating_history import imported
from tests.test_ratings import vote


def withdraw(call, target, revision, position="field", **kwargs):
    return call("DELETE", f"/players/{target}/ratings/{position}", {"revision": revision}, **kwargs)


@pytest.mark.parametrize("position", ["field", "keeper"])
def test_withdrawal_zero_revision_privacy_and_restore(env, call, position):
    target = env[4]["player"]
    vote(call, target, attack=0 if position == "field" else None, defense=0, position=position)
    withdraw(call, target, 0, position, expected=409)
    result = withdraw(call, target, 1, position)
    assert result["own"]["withdrawn"] and result["own"]["revision"] == 2
    assert result["own"]["attack"] is None and result["own"]["defense"] is None
    assert result["averages"] == {"attack": None, "defense": None, "count": 0}
    # Replaying a lost DELETE response is idempotent, without adding history.
    assert withdraw(call, target, 1, position) == result
    assert call("GET", f"/players/{target}/reviews")[position] == []
    catalog = next(p for p in call("GET", "/players") if p["id"] == target)
    assert catalog["my_ratings"][position]["withdrawn"]
    with env[1]() as db:
        assert field_opinions(db, [target]) == []
        assert len(list(db.scalars(select(RatingHistory)))) == 2
    vote(
        call,
        target,
        position=position,
        attack=0 if position == "field" else None,
        defense=0,
        revision=0,
        expected=409,
    )
    restored = vote(
        call,
        target,
        position=position,
        attack=0 if position == "field" else None,
        defense=0,
        revision=2,
    )
    assert restored["own"]["revision"] == 3 and not restored["own"].get("withdrawn")
    assert restored["averages"]["defense"] == 0
    withdraw(call, target, 1, position, expected=409)
    assert restored["reviews"][0]["history"][1]["withdrawn"]
    withdraw(call, target, 3, position, role=None, expected=401)
    withdraw(call, env[4]["admin"], 0, position, expected=400)


@pytest.mark.parametrize("app_vote", [False, True])
def test_removal_suppresses_import_and_linked_cards_and_preserves_exact_source(env, call, app_vote):
    target, author = env[4]["player"], env[4]["admin"]
    with env[1]() as db, db.begin():
        old_target = Player(alias="Прежняя карточка", merged_into=target)
        db.add(old_target)
        db.flush()
        db.add(imported(author, old_target.id, datetime(2026, 1, 1, tzinfo=UTC), 1234, 4567))
        old_id = old_target.id
    if app_vote:
        vote(call, target, attack=3, defense=4)
    removed = withdraw(call, target, int(app_vote))
    assert removed["own"]["withdrawn"] and "imported_own" not in removed
    assert removed["averages"]["count"] == 0
    assert call("GET", f"/players/{target}/reviews")["field"] == []
    with env[1]() as db:
        row = db.scalar(select(ImportedRating))
        assert (row.attack_milli, row.defense_milli) == (1234, 4567)
        assert field_opinions(db, [target]) == []
    assert all(
        p["player_id"] != target
        for p in call("GET", "/leaderboards")["community"]["boards"]["field_total"]
    )
    withdraw(call, old_id, 0, expected=404)
    # A later source re-import must not restore the withdrawn vote.
    with env[1]() as db, db.begin():
        row = db.scalar(select(ImportedRating))
        row.attack_milli, row.defense_milli = 5000, 5000
    assert call("GET", f"/players/{target}/ratings/field")["averages"]["count"] == 0


def test_deletion_history_retains_old_days_and_empty_average_not_zero(env, call, monkeypatch):
    from fczhk import ratings

    target = env[4]["player"]
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(ratings, "now", lambda: start)
    vote(call, target, attack=4, defense=2)
    with env[1]() as db, db.begin():
        db.scalar(select(RatingHistory)).created_at = start
    monkeypatch.setattr(ratings, "now", lambda: start + timedelta(days=1))
    withdraw(call, target, 1)
    with env[1]() as db, db.begin():
        db.scalar(select(RatingHistory).where(RatingHistory.revision == 2)).created_at = (
            start + timedelta(days=1)
        )
    rows = call("GET", f"/players/{target}/rating-history")["field"]
    assert [(r["attack"], r["defense"], r["count"]) for r in rows] == [(4, 2, 1), (None, None, 0)]
    assert rows[-1]["changes"] == 1
    monkeypatch.setattr(ratings, "now", lambda: start + timedelta(days=2))
    vote(call, target, attack=0, defense=0, revision=2)
    with env[1]() as db, db.begin():
        db.scalar(select(RatingHistory).where(RatingHistory.revision == 3)).created_at = (
            start + timedelta(days=2)
        )
    rows = call("GET", f"/players/{target}/rating-history")["field"]
    assert [(r["attack"], r["defense"], r["count"]) for r in rows] == [
        (4, 2, 1),
        (None, None, 0),
        (0, 0, 1),
    ]


def test_other_authors_and_other_positions_remain(env, call):
    guest = call(
        "POST", "/players/guests", {"alias": "Удаление только своего голоса"}, expected=201
    )["id"]
    vote(call, guest, attack=5, defense=5)
    vote(call, guest, attack=1, defense=1, role="player")
    vote(call, guest, attack=None, defense=4, position="keeper")
    removed = withdraw(call, guest, 1)
    assert removed["averages"] == {"attack": 1, "defense": 1, "count": 1}
    assert call("GET", f"/players/{guest}/ratings/keeper")["own"]["defense"] == 4
    call(
        "DELETE",
        f"/players/{guest}/ratings/field",
        {"revision": 1, "author_id": env[4]["player"]},
        expected=422,
    )


def test_linking_after_removal_does_not_revive_an_older_vote(env, call):
    target = env[4]["player"]
    guest = call("POST", "/players/guests", {"alias": "Удалённый голос гостя"}, expected=201)["id"]
    vote(call, target, attack=5, defense=5)
    vote(call, guest, attack=2, defense=3)
    withdraw(call, guest, 1)
    call("POST", f"/players/{guest}/link", {"target_id": target})
    detail = call("GET", f"/players/{target}/ratings/field")
    assert detail["own"]["withdrawn"] and detail["own"]["revision"] > 2
    assert detail["averages"]["count"] == 0
    assert call("GET", f"/players/{target}/reviews")["field"] == []
    vote(call, target, revision=2, expected=409)


def test_removal_invalidates_live_lineup_without_rewriting_approved_snapshot(env, call, game):
    import copy

    from fczhk.models import TeamRatingSnapshot
    from tests.test_lineups import payload, preview
    from tests.test_ratings import add_guest

    m, reg = add_guest(call, game, "Голос для снимка", defense=None)
    target = reg["player_id"]
    vote(call, target, attack=4, defense=3)
    m, _ = add_guest(call, m, "Соперник для снимка")
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    p = preview(call, m)
    call("POST", f"/matches/{m['id']}/lineup/confirm", payload(p))
    before = call("GET", f"/matches/{m['id']}/lineup")
    with env[1]() as db:
        snapshot = copy.deepcopy(db.scalar(select(TeamRatingSnapshot)).data)
    withdraw(call, target, 1)
    after = call("GET", f"/matches/{m['id']}/lineup")
    assert after["fingerprint"] != before["fingerprint"]
    assert after["official_players"] == before["official_players"]
    assert next(p for p in after["players"] if p["player_id"] == target)["community_attack"] is None
    assert after["version"] == before["version"]
    with env[1]() as db:
        assert db.scalar(select(TeamRatingSnapshot)).data == snapshot


def test_withdrawal_sqlite_migration_and_downgrade_guard(tmp_path):
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
        command.upgrade(cfg, "c8e4a1b2906d")
        conn.execute(
            text(
                "INSERT INTO players (id, alias, created_at) VALUES (9001, 'Автор', '2026-01-01'), (9002, 'Игрок', '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO ratings (id, author_id, player_id, position, attack, defense, revision, updated_at) VALUES (1, 9001, 9002, 'field', 0, 40, 1, '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO rating_history (rating_id, revision, attack, defense, created_at) VALUES (1, 1, 0, 40, '2026-01-01')"
            )
        )
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
        assert conn.execute(
            text("SELECT attack, defense, revision, withdrawn FROM ratings")
        ).one() == (0, 40, 1, 0)
        assert conn.scalar(text("SELECT withdrawn FROM rating_history")) == 0
        command.downgrade(cfg, "c8e4a1b2906d")
        command.upgrade(cfg, "head")
        conn.execute(text("UPDATE ratings SET withdrawn = 1"))
    with pytest.raises(RuntimeError, match="историю удаления"), engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "c8e4a1b2906d")
    engine.dispose()
