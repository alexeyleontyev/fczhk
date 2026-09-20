from fastapi.testclient import TestClient
from sqlalchemy import event, select

from fczhk.api import create_app
from fczhk.models import Player
from fczhk.services import DomainError


def test_mutation_is_committed_before_http_success_is_sent(env):
    cfg, factory, _, tokens, _ = env
    app = create_app(cfg, factory)
    visible_at_response = []

    async def probe(scope, receive, send):
        async def capture(message):
            if message["type"] == "http.response.start" and message["status"] == 201:
                # A following HTTP request must already see this committed write.
                with factory() as observer:
                    visible_at_response.append(
                        observer.scalar(select(Player.id).where(Player.alias == "Commit probe"))
                    )
            await send(message)

        await app(scope, receive, capture)

    with TestClient(probe) as client:
        response = client.post(
            "/api/players/guests",
            json={"alias": "Commit probe"},
            headers={"Authorization": f"Bearer {tokens['admin']}"},
        )
    assert response.status_code == 201
    assert visible_at_response == [response.json()["id"]]


def test_commit_failure_returns_error_and_rolls_back_instead_of_http_success(env, call):
    _, factory, _, _, _ = env

    def fail_commit(db):
        if db.bind is factory.kw["bind"]:
            raise DomainError("Тестовый отказ фиксации транзакции", 503)

    event.listen(factory.class_, "before_commit", fail_commit)
    try:
        result = call("POST", "/players/guests", {"alias": "Rollback probe"}, expected=503)
        assert result["detail"] == "Тестовый отказ фиксации транзакции"
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)
    with factory() as observer:
        assert observer.scalar(select(Player.id).where(Player.alias == "Rollback probe")) is None
