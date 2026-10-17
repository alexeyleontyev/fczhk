from datetime import timedelta

from sqlalchemy import event

from fczhk.db import now
from fczhk.models import Match, MatchResult, Registration, ResultGoal, ResultParticipant


def test_archive_batches_queries_and_paginates_without_rosters(env, call):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        for i in range(120):
            start = now() - timedelta(days=i + 1)
            match = Match(
                game_day=start.date().isoformat(),
                starts_at=start,
                location="Архив",
                status="completed",
            )
            db.add(match)
            db.flush()
            db.add_all(
                [
                    MatchResult(match_id=match.id, completed=True),
                    ResultParticipant(
                        match_id=match.id, player_id=ids["player"], team="white", position="field"
                    ),
                    ResultGoal(id=f"goal-{i}", match_id=match.id, team="white", kind="goal"),
                    Registration(
                        match_id=match.id, player_id=ids["player"], position="field", selected=True
                    ),
                ]
            )
    queries = []
    engine = factory.kw["bind"]

    def record(*args):
        queries.append(args[2])

    event.listen(engine, "before_cursor_execute", record)
    try:
        page = call("GET", "/matches?limit=100")
        assert len(page) == 100
        assert len(queries) <= 9
        assert "registrations" not in page[0]
        assert page[0]["result"]["score"] == {"white": 1, "black": 0}
        assert page[0]["participant_count"] == 1
        second = call("GET", "/matches?limit=100&offset=100")
        assert len(second) == 20
        assert not {m["id"] for m in page} & {m["id"] for m in second}
        queries.clear()
        call("GET", "/game-ratings")
        assert len(queries) <= 8
    finally:
        event.remove(engine, "before_cursor_execute", record)
    call("GET", "/matches?limit=101", expected=422)
    call("GET", "/matches?offset=-1", expected=422)
