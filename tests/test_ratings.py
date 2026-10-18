from fractions import Fraction
from itertools import combinations
from random import Random

import pytest
from sqlalchemy import func, select

from fczhk import balancing
from fczhk.models import MatchRating, Player, Publication, Rating, RatingHistory
from fczhk.schemas import BalanceSettings


def vote(
    call, player, attack=2, defense=3, revision=0, role="admin", position="field", expected=200
):
    return call(
        "PUT",
        f"/players/{player}/ratings",
        dict(position=position, attack=attack, defense=defense, revision=revision),
        role=role,
        expected=expected,
    )


def add_guest(call, m, alias, position="field", attack=2, defense=3):
    p = call("POST", "/players/guests", {"alias": alias}, expected=201)
    path = f"/matches/{m['id']}"
    m = call(
        "POST",
        path + "/participants",
        dict(version=m["version"], player_id=p["id"], position=position),
    )
    reg = next(r for r in m["registrations"] if r["player_id"] == p["id"])
    if defense is not None:
        m = call(
            "PUT",
            path + f"/registrations/{reg['id']}/rating",
            dict(
                version=m["version"],
                position=position,
                attack=attack if position == "field" else None,
                defense=defense,
            ),
        )
    return m, reg


def prepared(call, m, n=4, keepers=0):
    for i in range(n):
        m, _ = add_guest(call, m, f"Гость {i:02}", attack=3, defense=3)
    for i in range(keepers):
        m, _ = add_guest(call, m, f"Вратарь {i}", position="keeper", defense=5)
    return call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})


def generate(call, m, **settings):
    return call(
        "POST",
        f"/matches/{m['id']}/balance",
        {"version": m["version"], "settings": settings},
        expected=201,
    )


def apply(call, m, run, variant=0, expected=200):
    return call(
        "POST",
        f"/matches/{m['id']}/balance/{run['id']}/apply",
        {"version": m["version"], "variant": variant},
        expected=expected,
    )


def test_current_vote_replaces_without_extra_weight_and_history_is_private(env, call):
    _, factory, _, _, ids = env
    vote(call, ids["player"], attack="2,2", defense="3.4")
    data = vote(call, ids["player"], attack="4,5", defense=0, revision=1)
    assert data["own"]["attack"] == 4.5
    assert data["averages"] == {"attack": 4.5, "defense": 0, "count": 1}
    assert [h["attack"] for h in data["reviews"][0]["history"]] == [4.5, 2.2]
    # Replaying a stale edit never overwrites the current score.
    vote(call, ids["player"], revision=1, expected=409)
    own = call("GET", f"/players/{ids['player']}/ratings/field", role="player")
    assert own == {"own": None, "averages": {"attack": 4.5, "defense": 0}}
    for p in call("GET", "/players", role="player"):
        assert all("count" not in rating for rating in p["ratings"].values())
        assert "reviews" not in p
    # Own edits are visible, but another author's vote cannot be submitted.
    vote(call, ids["admin"], role="player")
    assert (
        call("GET", f"/players/{ids['admin']}/ratings/field", role="player")["own"]["attack"] == 2
    )
    call(
        "PUT",
        f"/players/{ids['admin']}/ratings",
        dict(position="field", attack=5, defense=5, revision=1, author_id=ids["admin"]),
        role="player",
        expected=422,
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Rating)) == 2
        assert db.scalar(select(func.count()).select_from(RatingHistory)) == 3


@pytest.mark.parametrize(
    "attack,defense",
    [
        (-0.1, 3),
        (5.1, 3),
        (2.22, 3),
        (None, 3),
        (True, 3),
        ("NaN", 3),
        (3, "Infinity"),
        (3, None),
        (3, "3,33"),
    ],
)
def test_invalid_values_rejected(env, call, attack, defense):
    vote(call, env[4]["player"], attack, defense, expected=422)


def test_self_catalog_and_keeper_rules(env, call):
    ids = env[4]
    vote(call, ids["admin"], expected=400)
    g = call("POST", "/players/guests", {"alias": "Гость без Telegram"}, expected=201)
    guest_rating = vote(call, g["id"], attack=4.2, defense=3.1, role="player")
    assert guest_rating["own"]["attack"] == 4.2
    assert guest_rating["averages"] == {"attack": 4.2, "defense": 3.1}
    assert "reviews" not in guest_rating
    assert (
        call("GET", f"/players/{g['id']}/ratings/field")["reviews"][0]["author_id"] == ids["player"]
    )
    vote(call, ids["player"], position="keeper", expected=422)
    data = vote(call, ids["player"], attack=None, defense=4.7, position="keeper")
    assert data["averages"]["attack"] is None
    field = call("GET", f"/players/{ids['player']}/ratings/field")
    assert field["averages"]["defense"] is None
    vote(call, ids["player"], attack=0, defense=0)
    assert call("GET", f"/players/{ids['player']}/ratings/keeper")["averages"]["defense"] == 4.7


def test_catalog_votes_follow_link_and_latest_edit_counts_once(env, call):
    target = env[4]["player"]
    guest = call("POST", "/players/guests", {"alias": "Историческая карточка"}, expected=201)
    vote(call, target, attack=1, defense=1)
    vote(call, guest["id"], attack=3, defense=2)
    call("POST", f"/players/{guest['id']}/link", {"target_id": target})
    linked = call("GET", f"/players/{target}/ratings/field")
    assert linked["own"]["attack"] == 3
    assert linked["averages"] == {"attack": 3, "defense": 2, "count": 1}
    vote(call, target, attack=1, defense=1, revision=1, expected=409)
    updated = vote(call, target, attack=4, defense=5, revision=linked["own"]["revision"])
    assert updated["averages"] == {"attack": 4, "defense": 5, "count": 1}
    assert updated["reviews"][0]["history"][0]["attack"] == 4
    assert len(updated["reviews"]) == 1
    call("GET", f"/players/{guest['id']}/ratings/field", expected=404)
    vote(call, guest["id"], revision=2, expected=404)
    vote(call, 999999, expected=404)
    vote(call, target, role="player", expected=400)


def test_temporary_is_match_scoped_and_community_takes_precedence(env, call, game):
    ids = env[4]
    m, reg = add_guest(call, game, "Временный", attack=0, defense=0)
    assert m["registrations"][0]["rating"] == {"attack": 0, "defense": 0, "source": "temporary"}
    call("POST", f"/players/{reg['player_id']}/link", {"target_id": ids["player"]})
    m = call("GET", f"/matches/{m['id']}")
    assert m["registrations"][0]["rating"]["source"] == "temporary"
    vote(call, ids["player"], attack=5, defense=3)
    m = call("GET", f"/matches/{m['id']}")
    assert m["registrations"][0]["rating"] == {"attack": 5, "defense": 3, "source": "community"}
    path = f"/matches/{m['id']}/registrations/{reg['id']}/rating"
    call(
        "PUT", path, dict(version=m["version"], position="field", attack=1, defense=1), expected=409
    )
    other = call(
        "POST",
        "/matches",
        dict(starts_at="2026-10-09T20:00:00+03:00", location="Другой матч"),
        expected=201,
    )
    # A different guest needs new temporary values on every game.
    m, guest = add_guest(call, m, "Другой гость", attack=4, defense=2)
    other = call(
        "POST",
        f"/matches/{other['id']}/participants",
        dict(version=other["version"], player_id=guest["player_id"], position="field"),
    )
    assert other["registrations"][0]["rating"]["source"] == "missing"
    with env[1]() as db:
        assert db.get(MatchRating, guest["id"]).attack == 40


def test_missing_not_zero_and_permissions(call, game):
    m, _ = add_guest(call, game, "Без рейтинга", defense=None)
    m, _ = add_guest(call, m, "Настоящий ноль", attack=0, defense=0)
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    path = f"/matches/{m['id']}"
    result = call("POST", path + "/balance", {"version": m["version"]}, expected=400)
    assert "Без рейтинга" in result["detail"] and "Настоящий ноль" not in result["detail"]
    call("POST", path + "/balance", {"version": m["version"]}, role="player", expected=403)
    call("GET", path + "/balance", role="player", expected=403)
    call("GET", "/balance/settings", role="player", expected=403)
    call(
        "PUT",
        path + f"/registrations/{m['registrations'][0]['id']}/rating",
        dict(version=m["version"], position="field", attack=1, defense=1),
        role="player",
        expected=403,
    )


def test_balance_snapshot_includes_both_community_and_match_scores(call, game):
    m, reg = add_guest(call, game, "Оба источника", attack=2, defense=3)
    m, _ = add_guest(call, m, "Только временная", attack=4, defense=1)
    vote(call, reg["player_id"], attack=4.5, defense=1.2)
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    run = generate(call, m)
    row = next(row for row in run["inputs"] if row["player_id"] == reg["player_id"])
    assert row["community"] == {"attack": 4.5, "defense": 1.2}
    assert row["temporary"] == {"attack": 2, "defense": 3}
    assert row["source"] == "community" and row["attack"] == 4.5
    other = next(row for row in run["inputs"] if row["player_id"] != reg["player_id"])
    assert other["community"] is None and other["temporary"] == {"attack": 4, "defense": 1}


def test_autoteams_keeper_assignment_edit_snapshot_and_publish(call, game):
    m = prepared(call, game, n=5, keepers=2)
    path = f"/matches/{m['id']}"
    run = generate(call, m)
    assert len(run["result"]["variants"]) == 3
    assert len(run["inputs"]) == 5
    m = apply(call, m, run)
    assert all(r["team"] is None for r in m["registrations"] if r["position"] == "keeper")
    call("POST", path + "/actions/approve", {"version": m["version"]}, expected=400)
    assignments = {r["id"]: r["team"] for r in m["registrations"]}
    keepers = [r for r in m["registrations"] if r["position"] == "keeper"]
    assignments[keepers[0]["id"]], assignments[keepers[1]["id"]] = "white", "black"
    m = call("PUT", path + "/teams", dict(version=m["version"], assignments=assignments))
    assert not call("GET", path + "/balance")[0]["stale"]  # team edits aren't roster changes
    assert m["team_ratings"]["summary"]["white"]["attack"] == 3
    assert m["team_ratings"]["summary"]["black"]["defense"] == 1.5
    assert m["team_ratings"]["summary"]["cost"] == 0
    assert m["team_ratings"]["method"] == "auto"
    m = call("POST", path + "/actions/approve", {"version": m["version"]})
    assert m["team_ratings"]["frozen"]
    history = call("GET", path + "/history")["teams"][0]["ratings"]
    assert history["settings"]["epsilon"] == "0.10"
    assert history["inputs"][0]["attack_fraction"] == [3, 1]
    call("POST", path + "/actions/publish", {"version": m["version"]})
    # Explicit manual reset works even with an approved automatic choice.
    m = call(
        "PUT",
        path + "/teams",
        dict(
            version=m["version"],
            reset=True,
            assignments={r["id"]: None for r in m["registrations"]},
        ),
    )
    assert m["status"] == "finalized" and m["team_ratings"]["method"] == "manual"
    assert all(r["team"] is None for r in m["registrations"])


def test_collection_strength_includes_keepers_excludes_reserve_and_freezes_at_approval(
    env, call, game
):
    # A regular unpaid registration stays in reserve and must not count towards strength.
    game = call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    vote(call, env[4]["player"], attack=5, defense=5)
    m = prepared(call, game, n=4, keepers=2)
    path = f"/matches/{m['id']}"
    assert m["team_ratings"]["strength"]["total"] == 34
    assert m["team_ratings"]["strength"]["count"] == 6
    field = [r for r in m["registrations"] if r["selected"] and r["position"] == "field"]
    keepers = [r for r in m["registrations"] if r["selected"] and r["position"] == "keeper"]
    # Community values take precedence over temporary values, including for keepers.
    vote(call, field[0]["player_id"], attack=5, defense=4)
    vote(call, keepers[0]["player_id"], attack=None, defense=4, position="keeper")
    m = call("GET", path)
    assert m["team_ratings"]["strength"]["total"] == 36
    selected = [r for r in m["registrations"] if r["selected"]]
    white_ids = {r["id"] for r in field[:2] + keepers[:1]}
    assignments = {r["id"]: "white" if r["id"] in white_ids else "black" for r in selected}
    m = call("PUT", path + "/teams", dict(version=m["version"], assignments=assignments))
    m = call("POST", path + "/actions/approve", {"version": m["version"]})
    frozen = m["team_ratings"]["strength"]
    assert frozen["teams"]["white"]["total"] == 19 and frozen["teams"]["black"]["total"] == 17
    vote(call, field[0]["player_id"], attack=0, defense=0, revision=1)
    vote(call, keepers[0]["player_id"], attack=None, defense=0, position="keeper", revision=1)
    assert call("GET", path)["team_ratings"]["strength"] == frozen
    call("POST", path + "/actions/publish", {"version": m["version"]})
    with env[1]() as db:
        post = db.scalar(select(Publication).where(Publication.kind == "teams"))
        assert "Сила сбора: 36.00" in post.text
        assert "⚪ Белые · сила 19.00" in post.text and "⚫ Черные · сила 17.00" in post.text


def test_missing_strength_is_not_zero_and_zero_scores_are_rated(call, game):
    m, _ = add_guest(call, game, "Без оценки", defense=None)
    m, _ = add_guest(call, m, "Настоящий ноль", attack=0, defense=0)
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    strength = m["team_ratings"]["strength"]
    assert strength["total"] is None and strength["rated_total"] == 0
    assert strength["rated"] == 1 and strength["count"] == 2


def test_changed_ratings_block_old_choice_and_approval_but_not_frozen_teams(env, call, game):
    m = prepared(call, game)
    path = f"/matches/{m['id']}"
    reg = m["registrations"][0]
    call("POST", f"/players/{reg['player_id']}/link", {"target_id": env[4]["player"]})
    run = generate(call, m)
    m = apply(call, m, run)
    vote(call, env[4]["player"], attack=5, defense=1)
    assert call("GET", path + "/balance")[0]["stale"]
    assert call("GET", path)["team_ratings"]["stale"]
    apply(call, m, run, expected=409)
    call("POST", path + "/actions/approve", {"version": m["version"]}, expected=409)
    new = generate(call, m, max_epsilon=5, epsilon_step=1)
    m = apply(call, m, new)
    m = call("POST", path + "/actions/approve", {"version": m["version"]})
    before = m["team_ratings"]
    vote(call, env[4]["player"], attack=0, defense=0, revision=1)
    after = call("GET", path)
    assert after["status"] == "approved" and after["team_ratings"] == before
    assert after["version"] == m["version"]
    assert call("GET", path + "/history")["teams"][0]["ratings"]["inputs"][0]["attack"] == 5


def test_roster_change_invalidates_variants_and_clears_teams(call, game):
    m = prepared(call, game)
    run = generate(call, m)
    m = apply(call, m, run)
    path = f"/matches/{m['id']}"
    m = call(
        "POST",
        path + f"/registrations/{m['registrations'][0]['id']}/remove",
        {"version": m["version"]},
    )
    assert all(r["team"] is None for r in m["registrations"])
    apply(call, m, run, expected=409)
    assert call("GET", path + "/balance")[0]["stale"]


def test_generation_validation_and_small_roster_no_duplicates(call, game):
    call("POST", f"/matches/{game['id']}/balance", {"version": game["version"]}, expected=400)
    m = prepared(call, game, n=2)
    run = generate(call, m)
    assert len(run["result"]["variants"]) == 1
    assert run["result"]["warnings"]
    apply(call, m, run, variant=1, expected=404)
    call(
        "POST",
        f"/matches/{m['id']}/balance",
        {"version": m["version"], "settings": {"epsilon": 1, "max_epsilon": 0.5}},
        expected=422,
    )


def inputs(n, seed=None):
    rng = Random(seed)
    result = []
    for i in range(n):
        a, d = (
            (Fraction(3), Fraction(3))
            if seed is None
            else (Fraction(rng.randrange(51), 10), Fraction(rng.randrange(51), 10))
        )
        result.append(
            dict(
                registration_id=i,
                attack_fraction=[a.numerator, a.denominator],
                defense_fraction=[d.numerator, d.denominator],
            )
        )
    return result


@pytest.mark.parametrize(
    "a,d,expected", [(2, 3, (1, 3)), (5, 3, (5, 1.5)), (4, 4, (4, 2)), (0, 0, (0, 0))]
)
def test_transform(a, d, expected):
    assert balancing.transform(Fraction(a), Fraction(d)) == expected


@pytest.mark.parametrize(
    "n,partitions",
    [(2, 1), (3, 3), (4, 3), (5, 10), (6, 10), (7, 35), (8, 35), (15, 6435), (16, 6435)],
)
def test_exhaustive_partitions_diversity_and_odd_means(n, partitions):
    result = balancing.generate(inputs(n), BalanceSettings())
    assert result["partition_count"] == partitions
    assert len(result["variants"]) == min(3, partitions)
    assert all(v["summary"]["cost"] == 0 for v in result["variants"])
    for i, j in combinations(range(len(result["variants"])), 2):
        assert result["distances"][i][j] >= result["min_distance"]
    for v in result["variants"]:
        assert set(v["assignments"]) == set(range(n))
        assert abs(v["summary"]["white"]["count"] - v["summary"]["black"]["count"]) <= 1
        assert v["summary"]["white"]["attack"] == 3
        assert v["summary"]["black"]["defense"] == 1.5


def test_realistic_scores_stay_in_tolerance_and_colors_do_not_matter():
    result = balancing.generate(inputs(16, seed=42), BalanceSettings())
    assert len(result["variants"]) == 3
    assert result["diversity_optimum_guaranteed"] is False
    for v in result["variants"]:
        assert v["summary"]["cost"] <= result["minimum_cost"] + result["epsilon_used"] + 1e-12
    assert min(result["distances"][i][j] for i, j in combinations(range(3), 2)) >= 6
    mask = 0b11110000
    assert balancing.distance(mask, mask ^ 255, 8) == 0


def test_exact_averages_not_rounded_before_transform(env, call):
    ids = env[4]
    with env[1]() as db, db.begin():
        for i in range(3):
            p = Player(alias=f"Автор {i}", telegram_id=2000 + i)
            db.add(p)
            db.flush()
            db.add(
                Rating(
                    author_id=p.id,
                    player_id=ids["player"],
                    position="field",
                    attack=[20, 20, 21][i],
                    defense=20,
                )
            )
    from fczhk.ratings import aggregate

    with env[1]() as db:
        a, d, n = aggregate(db, [ids["player"]])[(ids["player"], "field")]
        assert a == Fraction(61, 30) and d == 2 and n == 3
        assert balancing.transform(a, d) == (a, 1)
