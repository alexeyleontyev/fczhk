import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fczhk.auth import player_for_telegram
from fczhk.models import Player


def test_guest_and_profile_names_are_unique(env, call):
    call("POST", "/players/guests", {"alias": "Игрок"}, expected=409)
    call("PATCH", "/me", {"alias": "Игрок"}, expected=409)
    assert call("GET", "/me")["alias"] == "Администратор"
    call("PATCH", "/me", {"alias": "Администратор"})
    with pytest.raises(IntegrityError), env[1]() as db, db.begin():
        db.add(Player(alias="Игрок"))
        db.flush()


def test_telegram_names_do_not_claim_an_existing_guest_or_block_login(env):
    with env[1]() as db, db.begin():
        first = player_for_telegram(db, 8001, "Игрок")
        second = player_for_telegram(db, 8002, "Игрок")
        assert first.alias == "Игрок · 8001"
        assert second.alias == "Игрок · 8002"
        assert player_for_telegram(db, 8001, "Другое имя").id == first.id
        assert db.scalar(select(Player.id).where(Player.alias == "Игрок")) == env[4]["player"]
