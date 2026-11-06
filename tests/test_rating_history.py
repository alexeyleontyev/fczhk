from datetime import UTC, datetime, timedelta

import pytest

from fczhk.models import ImportedRating, Player, Rating, RatingHistory


def imported(author, target, at, attack=1000, defense=1000):
    return ImportedRating(
        source_id="history-test", source_sha256="a" * 64, author_id=author,
        player_id=target, position="field", attack_milli=attack, defense_milli=defense,
        attack_cell="A1", defense_cell="B1", imported_at=at,
    )


def test_daily_history_replays_trimmed_votes_and_uses_moscow_midnight(env, call):
    target = env[4]["player"]
    initial = datetime(2026, 10, 17, 21, tzinfo=UTC)
    times = [datetime(2026, 10, 20, 20, 59, tzinfo=UTC),
             datetime(2026, 10, 20, 21, 1, tzinfo=UTC),
             datetime(2026, 10, 20, 21, 5, tzinfo=UTC)]
    with env[1]() as db, db.begin():
        authors = [Player(alias=f"История {i}", telegram_id=4000 + i) for i in range(5)]
        db.add_all(authors)
        db.flush()
        for i, (a, d) in enumerate(zip([0, 1000, 2000, 3000, 5000], [5000, 4000, 3000, 2000, 0])):
            db.add(imported(authors[i].id, target, initial + timedelta(microseconds=i), a, d))
        row = Rating(author_id=authors[-1].id, player_id=target, position="field",
                     attack=10, defense=40, revision=3, updated_at=times[-1])
        db.add(row)
        db.flush()
        for revision, (a, d) in enumerate([(40, 10), (0, 50), (10, 40)], start=1):
            db.add(RatingHistory(rating_id=row.id, revision=revision, attack=a, defense=d,
                                 created_at=times[revision - 1]))
    path = f"/players/{target}/rating-history"
    result = call("GET", path)
    assert result["timezone"] == "Europe/Moscow"
    assert result["method"] == "trimmed_mean_20_percent"
    assert result["keeper"] == []
    assert [p["date"] for p in result["field"]] == ["2026-10-18", "2026-10-20", "2026-10-21"]
    assert [(p["attack"], p["defense"]) for p in result["field"][:2]] == [(2, 3), (2, 3)]
    last = result["field"][-1]
    assert last["attack"] == pytest.approx(4 / 3)
    assert last["defense"] == pytest.approx(11 / 3)
    assert [p["count"] for p in result["field"]] == [5, 5, 5]
    assert [p["changes"] for p in result["field"]] == [0, 1, 2]
    averages = call("GET", f"/players/{target}/ratings/field")["averages"]
    assert {k: last[k] for k in averages} == averages
    public = call("GET", path, role="player")
    assert len(public["field"]) == 3
    assert all(set(p) == {"date", "at", "attack", "defense"} for p in public["field"])
    call("GET", path, role=None, expected=401)


def test_history_deduplicates_linked_cards_and_app_overrides_import(env, call):
    target = env[4]["player"]
    initial = datetime(2026, 10, 18, tzinfo=UTC)
    with env[1]() as db, db.begin():
        author = Player(alias="Автор истории", telegram_id=5000)
        other = Player(alias="Второй автор истории", telegram_id=5001)
        db.add_all([author, other])
        db.flush()
        old_author = Player(alias="Старая карточка автора", merged_into=author.id)
        old_target = Player(alias="Старая карточка игрока", merged_into=target)
        db.add_all([old_author, old_target])
        db.flush()
        db.add_all([
            imported(author.id, target, initial, 5000, 5000),
            imported(old_author.id, old_target.id, initial, 4000, 4000),
            imported(other.id, target, initial, 0, 0),
            imported(target, old_target.id, initial, 5000, 5000),
            Rating(author_id=old_author.id, player_id=old_target.id, position="field",
                   attack=10, defense=10, updated_at=initial + timedelta(days=1)),
            Rating(author_id=author.id, player_id=target, position="field",
                   attack=20, defense=20, updated_at=initial + timedelta(days=2)),
            Rating(author_id=target, player_id=old_target.id, position="field",
                   attack=50, defense=50, updated_at=initial + timedelta(days=3)),
        ])
    rows = call("GET", f"/players/{target}/rating-history")["field"]
    assert [(p["attack"], p["defense"], p["count"]) for p in rows] == [(2, 2, 2), (.5, .5, 2), (1, 1, 2)]
    call("GET", f"/players/{old_target.id}/rating-history", expected=404)


def test_keeper_zero_empty_profiles_and_missing_latest_revision(env, call):
    target = env[4]["player"]
    path = f"/players/{target}/rating-history"
    assert call("GET", path)["field"] == call("GET", path)["keeper"] == []
    initial = datetime(2026, 10, 20, 10, tzinfo=UTC)
    with env[1]() as db, db.begin():
        row = Rating(author_id=env[4]["admin"], player_id=target, position="keeper",
                     attack=None, defense=0, revision=2, updated_at=initial + timedelta(days=1))
        db.add(row)
        db.flush()
        db.add(RatingHistory(rating_id=row.id, revision=1, attack=None, defense=50,
                             created_at=initial))
    data = call("GET", path)
    assert data["field"] == []
    assert [(p["attack"], p["defense"]) for p in data["keeper"]] == [(None, 5), (None, 0)]
    assert [p["date"] for p in data["keeper"]] == ["2026-10-20", "2026-10-21"]
    assert data["keeper"][-1]["count"] == 1
    call("GET", "/players/987654/rating-history", expected=404)
