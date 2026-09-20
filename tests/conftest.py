import pytest
from fastapi.testclient import TestClient

from fczhk.api import create_app
from fczhk.auth import create_session
from fczhk.config import Settings
from fczhk.db import Base, database
from fczhk.models import GameTemplate, Player, RatingState


@pytest.fixture
def env(tmp_path):
    cfg = Settings(
        _env_file=None, env="test", database_url=f"sqlite:///{tmp_path}/test.db", admin_ids="101"
    )
    engine, factory = database(cfg.database_url)
    Base.metadata.create_all(engine)
    with factory() as db, db.begin():
        db.add(GameTemplate(id=1))
        db.add(RatingState(id=1))
        admin = Player(alias="Администратор", telegram_id=101)
        player = Player(alias="Игрок", telegram_id=102)
        db.add_all([admin, player])
        db.flush()
        tokens = {
            "admin": create_session(db, cfg, admin),
            "player": create_session(db, cfg, player),
        }
        ids = {"admin": admin.id, "player": player.id}
    with TestClient(create_app(cfg, factory)) as client:
        yield cfg, factory, client, tokens, ids
    engine.dispose()


@pytest.fixture
def call(env):
    _, _, client, tokens, _ = env

    def request(method, path, body=None, role="admin", expected=200):
        response = client.request(
            method,
            "/api" + path,
            json=body,
            headers={"Authorization": f"Bearer {tokens[role]}"} if role else {},
        )
        assert response.status_code == expected, response.text
        return response.json()

    return request


@pytest.fixture
def game(call):
    m = call(
        "POST",
        "/matches",
        dict(
            starts_at="2026-10-02T20:00:00+03:00",
            location="Стадион",
            cost=80000,
            description="Футбол",
            payment_details="Перевод",
        ),
        expected=201,
    )
    return call("POST", f"/matches/{m['id']}/actions/open", {"version": m["version"]})
