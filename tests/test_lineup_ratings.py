from fczhk.models import ImportedRating, Match, MatchResult, Player, ResultParticipant
from tests.test_ratings import add_guest, vote


def test_lineup_opinions_use_current_canonical_votes_and_only_field_targets(env, call, game):
    m, field = add_guest(call, game, "Полевой")
    m, other = add_guest(call, m, "Второй полевой")
    m, keeper = add_guest(call, m, "Вратарь", position="keeper", attack=None)
    outsider = call("POST", "/players/guests", {"alias": "Не в составе"}, expected=201)
    ids = env[4]
    vote(call, field["player_id"], attack=0, defense=0)
    vote(call, other["player_id"], attack=1, defense=2)
    vote(call, other["player_id"], attack=2, defense=3, role="player")
    vote(call, keeper["player_id"], attack=None, defense=5, position="keeper")
    vote(call, outsider["id"], attack=5, defense=5)
    with env[1]() as db, db.begin():
        old_author = Player(alias="Старое имя автора", merged_into=ids["admin"])
        old_target = Player(alias="Старая карточка полевого", merged_into=field["player_id"])
        imported_author = Player(alias="Оценивший из таблицы")
        db.add_all([old_author, old_target, imported_author])
        db.flush()
        imported_author_id = imported_author.id
        for author, target in (
            (old_author.id, old_target.id),
            (ids["admin"], field["player_id"]),
            # A linked card must not introduce a canonical self-vote.
            (field["player_id"], old_target.id),
            (imported_author.id, other["player_id"]),
        ):
            db.add(
                ImportedRating(
                    source_id="lineup-test",
                    source_sha256="a" * 64,
                    author_id=author,
                    player_id=target,
                    position="field",
                    attack_milli=4500,
                    defense_milli=4100,
                    attack_cell="A1",
                    defense_cell="B1",
                )
            )
    before = call("GET", f"/matches/{m['id']}")
    result = call("GET", f"/matches/{m['id']}/lineup/ratings", role="player")
    authors = {row["player_id"]: row for row in result["authors"]}
    assert set(authors) == {ids["admin"], ids["player"], imported_author_id}
    assert authors[ids["admin"]] == {
        "player_id": ids["admin"],
        "alias": "Администратор",
        "ratings": {
            str(field["player_id"]): {"attack": 0, "defense": 0},
            str(other["player_id"]): {"attack": 1, "defense": 2},
        },
    }
    assert authors[ids["player"]]["ratings"] == {
        str(other["player_id"]): {"attack": 2, "defense": 3}
    }
    assert authors[imported_author_id]["ratings"] == {
        str(other["player_id"]): {"attack": 4.5, "defense": 4.1}
    }
    assert call("GET", f"/matches/{m['id']}") == before
    call("GET", f"/matches/{m['id']}/lineup/ratings", role=None, expected=401)


def test_lineup_opinions_use_actual_historical_fields_and_hide_drafts(env, call, game):
    ids = env[4]
    vote(call, ids["player"], attack=3.2, defense=4.1)
    with env[1]() as db, db.begin():
        db.add(MatchResult(match_id=game["id"], completed=True))
        db.add(
            ResultParticipant(
                match_id=game["id"], player_id=ids["player"], position="field", team="white"
            )
        )
        db.get(Match, game["id"]).status = "completed"
    authors = call("GET", f"/matches/{game['id']}/lineup/ratings", role="player")["authors"]
    assert authors[0]["ratings"] == {str(ids["player"]): {"attack": 3.2, "defense": 4.1}}
    draft = call(
        "POST",
        "/matches",
        {"starts_at": "2026-11-06T20:00:00+03:00", "location": "Стадион"},
        expected=201,
    )
    call("GET", f"/matches/{draft['id']}/lineup/ratings", role="player", expected=404)
    assert call("GET", f"/matches/{draft['id']}/lineup/ratings") == {"authors": []}
