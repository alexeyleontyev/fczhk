from fractions import Fraction

import pytest
from sqlalchemy import func, select

from fczhk import ratings
from fczhk.models import ImportedRating, Player, Rating, TeamRatingSnapshot
from tests.test_lineups import payload, preview
from tests.test_ratings import add_guest, apply, generate, prepared


@pytest.mark.parametrize(
    "values,expected",
    [
        ([], None),
        ([0], Fraction(0)),
        ([4239], Fraction(4239, 1000)),
        ([1000, 1000, 1000, 5000], Fraction(2)),
        ([1000, 1000, 1000, 1000, 5000], Fraction(1)),
        ([0, 0, 0, 0, 5000], Fraction(0)),
        ([1000, 1000, 1000, 1239, 5000], Fraction(3239, 3000)),
        ([0, 1000, 2000, 2000, 2000, 3000, 4000, 5000, 5000], Fraction(19, 7)),
        ([0, 0, 1000, 2000, 2000, 2000, 3000, 4000, 5000, 5000], Fraction(7, 3)),
        ([0, 0, *([1000] * 9), 5000, 5000], Fraction(1)),
    ],
)
def test_trimmed_average_preserves_units_precision_zero_and_tail_boundaries(values, expected):
    assert ratings.trimmed_average(values) == expected
    assert ratings.trimmed_average(list(reversed(values))) == expected
    weights = ratings.trimmed_vote_weights(values)
    if values:
        assert sum(Fraction(v, 1000) * weights[v] for v in values) / sum(weights[v] for v in values) == expected
    else:
        assert weights == {}


def authors(db, count):
    people = [Player(alias=f"Оценщик {i}", telegram_id=8000 + i) for i in range(count)]
    db.add_all(people)
    db.flush()
    return people


def test_all_current_community_views_and_balance_inputs_use_trimmed_scores(env, call, game):
    target = env[4]["player"]
    with env[1]() as db, db.begin():
        for i, author in enumerate(authors(db, 5)):
            db.add_all(
                [
                    Rating(
                        author_id=author.id, player_id=target, position="field",
                        attack=50 if i == 4 else 10, defense=0 if i == 4 else 50,
                    ),
                    Rating(
                        author_id=author.id, player_id=target, position="keeper",
                        attack=None, defense=50 if i == 4 else 0,
                    ),
                ]
            )
    catalog = {p["id"]: p for p in call("GET", "/players")}
    assert catalog[target]["ratings"] == {
        "field": {"attack": 1, "defense": 5, "count": 5},
        "keeper": {"attack": None, "defense": 0, "count": 5},
    }
    assert call("GET", "/me", role="player")["ratings"]["field"] == {"attack": 1, "defense": 5}
    detail = call("GET", f"/players/{target}/ratings/field")
    assert detail["averages"] == {"attack": 1, "defense": 5, "count": 5}
    assert len(detail["reviews"]) == 5
    assert sorted(r["attack"] for r in detail["reviews"]) == [1, 1, 1, 1, 5]
    public_reviews = call("GET", f"/players/{target}/reviews", role="player")
    assert sorted(r["defense"] for r in public_reviews["field"]) == [0, 5, 5, 5, 5]
    assert sorted(r["attack_weight"] for r in public_reviews["field"]) == [0, .75, .75, .75, .75]
    assert sorted(r["defense_weight"] for r in public_reviews["field"]) == [0, .75, .75, .75, .75]
    assert next(r for r in public_reviews["field"] if r["attack"] == 5)["attack_weight"] == 0
    assert all(r["attack_weight"] is None for r in public_reviews["keeper"])
    assert sorted(r["defense_weight"] for r in public_reviews["keeper"]) == [0, .75, .75, .75, .75]
    boards = call("GET", "/leaderboards", role="player")["community"]["boards"]
    assert next(r for r in boards["field_total"] if r["player_id"] == target)["score"] == 6
    assert next(r for r in boards["keeper_defense"] if r["player_id"] == target)["score"] == 0

    m = call("POST", f"/matches/{game['id']}/participants", {
        "version": game["version"], "player_id": target, "position": "field",
    })
    assert m["registrations"][0]["rating"] == {"attack": 1, "defense": 5, "source": "community"}
    m, other = add_guest(call, m, "Другой полевой", attack=3, defense=3)
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    board = call("GET", f"/matches/{m['id']}/lineup")
    person = next(p for p in board["players"] if p["player_id"] == target)
    assert (person["attack"], person["defense"], person["community_attack"], person["community_defense"]) == (1, 5, 1, 5)
    run = generate(call, m)
    person = next(p for p in run["inputs"] if p["player_id"] == target)
    assert person["attack_fraction"] == [1, 1] and person["defense_fraction"] == [5, 1]
    assert run["inputs"][0]["source"] == "community"
    # A temporary match grade stays separate from the general rating.
    assert next(p for p in board["players"] if p["registration_id"] == other["id"])["source"] == "temporary"
    assert next(p for p in call("GET", "/players") if p["id"] == other["player_id"])["ratings"]["field"]["attack"] is None


def test_trim_after_import_replacement_and_identity_deduplication(env, call):
    target = env[4]["player"]
    with env[1]() as db, db.begin():
        people = authors(db, 5)
        old_author = Player(alias="Прежняя карточка автора", merged_into=people[0].id)
        old_target = Player(alias="Прежняя карточка игрока", merged_into=target)
        db.add_all([old_author, old_target])
        db.flush()
        values = [(5000, 1000), (1000, 2000), (1000, 3000), (1239, 4000), (5000, 0)]
        pairs = [(p.id, target, a, d) for p, (a, d) in zip(people, values)]
        pairs.extend([(old_author.id, old_target.id, 5000, 5000), (target, old_target.id, 5000, 5000)])
        for author, pid, attack, defense in pairs:
            db.add(ImportedRating(
                source_id="trimmed-test", source_sha256="a" * 64, author_id=author,
                player_id=pid, position="field", attack_milli=attack, defense_milli=defense,
                attack_cell="A1", defense_cell="B1",
            ))
        # This latest app vote supersedes both imported identities of the author.
        db.add(Rating(author_id=people[0].id, player_id=target, position="field", attack=10, defense=10))
        db.add(Rating(author_id=target, player_id=old_target.id, position="field", attack=50, defense=50))
    with env[1]() as db:
        assert ratings.aggregate(db, [target])[(target, "field")] == (Fraction(3239, 3000), Fraction(2), 5)
        assert db.scalar(select(func.count()).select_from(ImportedRating)) == 7
        assert db.scalar(select(func.count()).select_from(Rating)) == 2
    detail = call("GET", f"/players/{target}/ratings/field")
    assert detail["averages"]["count"] == 5
    assert len(detail["reviews"]) == 5


def test_crossing_five_votes_updates_live_scores_without_rewriting_approved_snapshot(env, call, game):
    m, reg = add_guest(call, game, "С оценками", defense=None)
    target = reg["player_id"]
    with env[1]() as db, db.begin():
        people = authors(db, 5)
        last_author = people[-1].id
        for i, author in enumerate(people[:4]):
            db.add(Rating(author_id=author.id, player_id=target, position="field",
                          attack=50 if i == 3 else 10, defense=50 if i == 3 else 10))
    m, _ = add_guest(call, m, "Второй", attack=3, defense=3)
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    p = preview(call, m)
    approved = call("POST", f"/matches/{m['id']}/lineup/confirm", payload(p))
    before = call("GET", f"/matches/{m['id']}")
    with env[1]() as db:
        saved = db.scalar(select(TeamRatingSnapshot)).data
        assert saved["community_rating_method"] == ratings.COMMUNITY_RATING_METHOD
        assert next(p for p in saved["inputs"] if p["player_id"] == target)["attack"] == 2
    with env[1]() as db, db.begin():
        db.add(Rating(author_id=last_author, player_id=target, position="field", attack=10, defense=10))
    assert call("GET", f"/players/{target}/ratings/field")["averages"] == {"attack": 1, "defense": 1, "count": 5}
    board = call("GET", f"/matches/{m['id']}/lineup")
    live = next(p for p in board["players"] if p["player_id"] == target)
    frozen = next(p for p in board["official_players"] if p["player_id"] == target)
    assert live["attack"] == live["community_attack"] == 1
    assert frozen["attack"] == 2
    after = call("GET", f"/matches/{m['id']}")
    assert after["version"] == approved["version"]
    assert after["team_ratings"] == before["team_ratings"]
    with env[1]() as db:
        assert db.scalar(select(TeamRatingSnapshot)).data == saved


@pytest.mark.parametrize("method", ["community", "game"])
def test_aggregation_policy_change_invalidates_cached_variants_even_with_same_scores(env, call, game, monkeypatch, method):
    m = prepared(call, game)
    monkeypatch.setattr(ratings, "COMMUNITY_RATING_METHOD", "previous_policy")
    old_board = call("GET", f"/matches/{m['id']}/lineup")
    run = generate(call, m, method=method)
    monkeypatch.setattr(ratings, "COMMUNITY_RATING_METHOD", "next_policy")
    new_board = call("GET", f"/matches/{m['id']}/lineup")
    assert old_board["players"] == new_board["players"]
    assert old_board["fingerprint"] != new_board["fingerprint"]
    assert call("GET", f"/matches/{m['id']}/balance")[0]["stale"]
    apply(call, m, run, expected=409)
