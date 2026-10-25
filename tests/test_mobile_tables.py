from datetime import timedelta

from sqlalchemy import event

from fczhk.db import now
from fczhk.models import (
    ImportedRating,
    Match,
    MatchResult,
    Player,
    Registration,
    ResultGoal,
    ResultParticipant,
)


def test_catalog_own_votes_are_private_bulk_and_follow_linked_targets(env, call):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        guest = Player(alias="Старая карточка", merged_into=ids["player"])
        author = Player(alias="Старый оценщик", merged_into=ids["admin"])
        db.add_all([guest, author])
        db.flush()
        db.add(
            ImportedRating(
                source_id="catalog",
                source_sha256="a" * 64,
                author_id=author.id,
                player_id=guest.id,
                attack_milli=4239,
                defense_milli=0,
                attack_cell="A1",
                defense_cell="B1",
            )
        )
    rows = {p["id"]: p for p in call("GET", "/players")}
    assert rows[ids["player"]]["my_ratings"]["field"] == {
        "attack": 4.239,
        "defense": 0,
        "revision": 0,
        "source": "sheet",
    }
    assert rows[ids["admin"]]["my_ratings"] == {"field": None, "keeper": None}
    public = {p["id"]: p for p in call("GET", "/players", role="player")}
    assert all(p["my_ratings"] == {"field": None, "keeper": None} for p in public.values())
    assert public[ids["player"]]["ratings"]["field"] == {"attack": 4.239, "defense": 0}
    for position, attack, defense in [("field", 0, 5), ("keeper", None, 0)]:
        call(
            "PUT",
            f"/players/{ids['player']}/ratings",
            dict(position=position, attack=attack, defense=defense, revision=0),
        )
    rows = {p["id"]: p for p in call("GET", "/players")}
    assert rows[ids["player"]]["my_ratings"]["field"]["attack"] == 0
    assert rows[ids["player"]]["my_ratings"]["field"]["revision"] == 1
    assert rows[ids["player"]]["my_ratings"]["keeper"]["defense"] == 0
    # Catalog query count stays constant as the catalog grows.
    with factory() as db:
        engine = db.get_bind()
    queries = []

    def record(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        call("GET", "/players")
        before = len(queries)
        with factory() as db, db.begin():
            db.add_all([Player(alias=f"Новый {i}") for i in range(30)])
        queries.clear()
        assert len(call("GET", "/players")) == 32
        assert len(queries) == before
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_last_completed_uses_actual_protocol_and_canonical_catalog_ids(env, call):
    assert call("GET", "/matches/last-completed", role="player") is None
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        old = Player(alias="Участник до привязки", merged_into=ids["player"])
        keeper1 = Player(alias="Приглашённый вратарь")
        keeper2 = Player(alias="Вратарь (смены, 26.06.2026, белые)")
        db.add_all([old, keeper1, keeper2])
        db.flush()
        target = None
        for index, (status, completed, days) in enumerate(
            [
                ("completed", True, -10),
                ("completed", True, -2),
                ("approved", False, -1),
                ("cancelled", True, -1),
                ("draft", True, -1),
                ("completed", True, 5),
            ]
        ):
            m = Match(
                starts_at=now() + timedelta(days=days),
                game_day=f"2026-01-{index + 1:02}",
                status=status,
                location="Поле",
            )
            db.add(m)
            db.flush()
            db.add(MatchResult(match_id=m.id, completed=completed))
            db.flush()
            if index == 1:
                target = m.id
                db.add_all(
                    [
                        ResultParticipant(
                            match_id=m.id, player_id=old.id, position="field", team="white"
                        ),
                        ResultParticipant(
                            match_id=m.id, player_id=keeper2.id, position="keeper", team="black"
                        ),
                        # A registration alone must never pass the previous-game filter.
                        Registration(
                            match_id=m.id,
                            player_id=ids["admin"],
                            position="field",
                            selected=True,
                            team="white",
                        ),
                        ResultGoal(match_id=m.id, id="score", team="white", kind="goal"),
                    ]
                )
        keeper = keeper1.id
    for role in ("admin", "player"):
        data = call("GET", "/matches/last-completed", role=role)
        assert data["id"] == target
        assert data["participant_ids"] == sorted([ids["player"], keeper])
        assert data["result"] == {"completed": True, "score": {"white": 1, "black": 0}}
        assert "registrations" not in data
    call("GET", "/matches/last-completed", role=None, expected=401)
