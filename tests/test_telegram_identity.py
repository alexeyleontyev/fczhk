"""Profile identification survives alias changes and follows verified Telegram data."""

import pytest

from fczhk.auth import player_for_telegram
from fczhk.models import Player
from tests.helpers import signed_data


def test_username_changes_do_not_change_alias_and_omitted_metadata_is_preserved(env):
    with env[1]() as db, db.begin():
        player = player_for_telegram(db, 102, "Telegram name", "old_username")
        assert player.alias == "Игрок" and player.telegram_username == "old_username"
        assert player_for_telegram(db, 102, "Another name").telegram_username == "old_username"
        player_for_telegram(db, 102, "Another name", "new_username")
        assert player.telegram_username == "new_username" and player.alias == "Игрок"
        player_for_telegram(db, 102, "Another name", None)
        assert player.telegram_username is None and player.alias == "Игрок"


@pytest.mark.parametrize("username", ["", "@nickname", "bad/name", "юзер", "x" * 33, 42])
def test_invalid_username_is_not_stored_as_a_profile_link(env, username):
    with env[1]() as db, db.begin():
        player = player_for_telegram(db, 102, "Игрок", username)
        assert player.telegram_username is None and player.telegram_id == 102


def test_verified_miniapp_login_refreshes_username_and_keeps_id_and_alias(env, call):
    cfg, factory, client, _, ids = env
    forged = client.post(
        "/api/auth/telegram",
        json={"init_data": signed_data("wrong-token", username="forged_username")},
    )
    assert forged.status_code == 401
    assert call("GET", "/me", role="player")["telegram_username"] is None
    for username in ("old_username", "new_username", None):
        response = client.post(
            "/api/auth/telegram",
            json={"init_data": signed_data(cfg.bot_token, username=username)},
        )
        assert response.status_code == 200, response.text
        profile = response.json()["player"]
        assert profile["id"] == ids["player"] and profile["alias"] == "Игрок"
        assert profile["telegram_username"] == username and profile["telegram_id"] == 102
        assert call("GET", "/me", role="player")["telegram_username"] == username
        assert call("GET", f"/players/{ids['player']}/stats")["telegram_username"] == username
    # The existing session still works after verified logins and alias changes.
    call("PATCH", "/me", {"alias": "Новое игровое имя"}, role="player")
    assert call("GET", "/me", role="player")["telegram_id"] == 102
    with factory() as db:
        assert db.get(Player, ids["player"]).telegram_id == 102


def test_linked_and_renamed_profiles_keep_telegram_identity_without_catalog_noise(env, call):
    factory, ids = env[1], env[4]
    with factory() as db, db.begin():
        player_for_telegram(db, 102, "Игрок", "player_username")
    guest = call("POST", "/players/guests", {"alias": "Имя из истории"}, expected=201)
    guest_stats = call("GET", f"/players/{guest['id']}/stats", role="player")
    assert guest_stats["telegram_username"] is None and guest_stats["telegram_id"] is None
    call("POST", f"/players/{guest['id']}/link", {"target_id": ids["player"]})
    call("PATCH", "/me", {"alias": "Новое имя"}, role="player")
    for path in ("/me", f"/players/{ids['player']}/stats", f"/players/{guest['id']}/stats"):
        data = call("GET", path, role="player")
        assert data["alias"] == "Новое имя"
        assert data["telegram_username"] == "player_username" and data["telegram_id"] == 102
    for player in call("GET", "/players", role="player"):
        assert "telegram_username" not in player and "telegram_id" not in player
    call("GET", f"/players/{ids['player']}/stats", role=None, expected=401)
    call(
        "PATCH",
        "/me",
        {"alias": "Подмена", "telegram_username": "forged"},
        role="player",
        expected=422,
    )
