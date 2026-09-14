import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from sqlalchemy import select

from fczhk.auth import parse_telegram
from fczhk.config import Settings
from fczhk.db import now
from fczhk.models import Player, Registration
from fczhk.services import (
    DomainError,
)


def populate(factory, mid, fields=18, keepers=3):
    with factory() as db, db.begin():
        for i in range(fields + keepers):
            p = Player(alias=f"Участник {i:02}", telegram_id=1000 + i)
            db.add(p)
            db.flush()
            db.add(
                Registration(
                    match_id=mid,
                    player_id=p.id,
                    position="field" if i < fields else "keeper",
                    registered_at=now() - timedelta(minutes=100 - i),
                    paid=True,
                )
            )


def test_no_auth_or_player_admin_privileges(env, call, game):
    call("GET", "/matches", role=None, expected=401)
    call(
        "POST",
        f"/matches/{game['id']}/actions/finalize",
        {"version": game["version"]},
        role="player",
        expected=403,
    )
    call("GET", "/template", role="player", expected=403)
    call("GET", f"/matches/{game['id']}/history", role="player", expected=403)
    call("POST", "/auth/demo/admin", role=None, expected=404)


def test_join_repeat_position_cancel_rejoin(call, game):
    path = f"/matches/{game['id']}"
    first = call("POST", path + "/join", {"position": "field"}, role="player")
    second = call("POST", path + "/join", {"position": "field"}, role="player")
    assert second["registrations"] == first["registrations"]
    assert second["version"] == first["version"]
    rid = first["registrations"][0]["id"]
    paid = call(
        "PUT", path + f"/registrations/{rid}/payment", {"version": second["version"], "paid": True}
    )
    moved = call("POST", path + "/join", {"position": "keeper"}, role="player")
    assert moved["registrations"][0]["paid"]
    assert moved["registrations"][0]["registered_at"] > paid["registrations"][0]["registered_at"]
    call("DELETE", path + "/join", role="player")
    rejoined = call("POST", path + "/join", {"position": "field"}, role="player")
    assert len(rejoined["registrations"]) == 1
    assert not rejoined["registrations"][0]["paid"]
    assert (
        rejoined["registrations"][0]["registered_at"] > moved["registrations"][0]["registered_at"]
    )


def test_finalization_orders_registration_not_payment_and_separates_roles(env, call, game):
    _, factory, _, _, _ = env
    populate(factory, game["id"])
    with factory() as db, db.begin():
        regs = list(db.scalars(select(Registration).order_by(Registration.id)))
        regs[0].paid_at = now()
        regs[1].paid_at = now() - timedelta(hours=4)
        regs[2].paid = False
    result = call("POST", f"/matches/{game['id']}/actions/finalize", {"version": game["version"]})
    chosen = [r for r in result["registrations"] if r["selected"]]
    assert len(chosen) == 18
    assert sum(r["position"] == "field" for r in chosen) == 16
    assert "Участник 00" in [r["alias"] for r in chosen]
    assert "Участник 02" not in [r["alias"] for r in chosen]
    assert "Участник 17" not in [r["alias"] for r in chosen]
    assert "Участник 20" not in [r["alias"] for r in chosen]
    call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player", expected=400)


def test_cancel_after_finalization_requires_admin(env, call, game):
    joined = call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    call("POST", f"/matches/{game['id']}/actions/finalize", {"version": joined["version"]})
    call("DELETE", f"/matches/{game['id']}/join", role="player", expected=400)


def test_reserve_requires_confirmation_and_preserves_order(env, call, game):
    _, factory, _, _, _ = env
    populate(factory, game["id"])
    path = f"/matches/{game['id']}"
    m = call("POST", path + "/actions/finalize", {"version": game["version"]})
    removed = next(r for r in m["registrations"] if r["selected"] and r["position"] == "field")
    m = call("POST", path + f"/registrations/{removed['id']}/remove", {"version": m["version"]})
    assert sum(r["selected"] and r["position"] == "field" for r in m["registrations"]) == 15
    m = call("POST", path + "/promote", {"version": m["version"], "position": "field"})
    assert next(r for r in m["registrations"] if r["alias"] == "Участник 16")["selected"]
    call("POST", path + "/promote", {"version": m["version"], "position": "field"}, expected=400)


def test_guest_replacement_and_rollback(env, call, game):
    _, factory, _, _, _ = env
    populate(factory, game["id"], 16, 2)
    path = f"/matches/{game['id']}"
    m = call("POST", path + "/actions/finalize", {"version": game["version"]})
    g = call("POST", "/players/guests", {"alias": "Гость"}, expected=201)
    body = {"version": m["version"], "player_id": g["id"], "position": "field"}
    call("POST", path + "/participants", body, expected=409)
    assert len(call("GET", path)["registrations"]) == 18
    body["replace_id"] = m["registrations"][0]["id"]
    m = call("POST", path + "/participants", body)
    guest = next(r for r in m["registrations"] if r["player_id"] == g["id"])
    assert guest["selected"] and guest["forced"] and not guest["paid"]
    assert len(m["registrations"]) == 18


def test_forced_guest_before_finalization_is_retained(env, call, game):
    _, factory, _, _, _ = env
    g = call("POST", "/players/guests", {"alias": "Закрепленный гость"}, expected=201)
    m = call(
        "POST",
        f"/matches/{game['id']}/participants",
        {"version": game["version"], "player_id": g["id"], "position": "field"},
    )
    populate(factory, game["id"], 18, 2)
    m = call("POST", f"/matches/{game['id']}/actions/finalize", {"version": m["version"]})
    assert sum(r["selected"] for r in m["registrations"]) == 18
    assert next(r for r in m["registrations"] if r["player_id"] == g["id"])["selected"]


def test_teams_require_equal_counts_and_complete_assignment(env, call, game):
    _, factory, _, _, _ = env
    populate(factory, game["id"], 5, 2)
    path = f"/matches/{game['id']}"
    m = call("POST", path + "/actions/finalize", {"version": game["version"]})
    call("POST", path + "/actions/approve", {"version": m["version"]}, expected=400)
    assignments = {str(r["id"]): "white" for r in m["registrations"]}
    m = call("PUT", path + "/teams", {"version": m["version"], "assignments": assignments})
    call("POST", path + "/actions/approve", {"version": m["version"]}, expected=400)
    for i, r in enumerate(m["registrations"]):
        assignments[str(r["id"])] = "white" if (i < 3 or i == 5) else "black"
    m = call("PUT", path + "/teams", {"version": m["version"], "assignments": assignments})
    m = call("POST", path + "/actions/approve", {"version": m["version"]})
    assert m["status"] == "approved"
    first = call("POST", path + "/actions/publish", {"version": m["version"]})
    second = call("POST", path + "/actions/publish", {"version": m["version"]})
    assert len(first["publications"]) == len(second["publications"])
    r = m["registrations"][0]
    m = call("POST", path + f"/registrations/{r['id']}/remove", {"version": m["version"]})
    assert m["status"] == "finalized"
    assert all(r["team"] is None for r in m["registrations"])
    assert any(p["kind"] == "teams" and p["stale"] for p in m["publications"])
    assert len(call("GET", path + "/history")["teams"]) == 1


def test_outdated_admin_request_is_rejected(call, game):
    call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    call(
        "POST",
        f"/matches/{game['id']}/actions/finalize",
        {"version": game["version"]},
        expected=409,
    )
    assert call("GET", f"/matches/{game['id']}")["status"] == "open"


def test_payment_cannot_target_registration_of_another_game(call, game):
    m = call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    other = call(
        "POST",
        "/matches",
        dict(starts_at="2026-10-09T20:00:00+03:00", location="Другой стадион"),
        expected=201,
    )
    call(
        "PUT",
        f"/matches/{other['id']}/registrations/{m['registrations'][0]['id']}/payment",
        {"version": other["version"], "paid": True},
        expected=404,
    )


def test_guest_link_preserves_history_and_prevents_wrong_merge(env, call, game):
    _, factory, _, _, ids = env
    guest = call("POST", "/players/guests", {"alias": "Исторический гость"}, expected=201)
    call(
        "POST",
        f"/matches/{game['id']}/participants",
        {"version": game["version"], "player_id": guest["id"], "position": "field"},
    )
    call("POST", f"/players/{guest['id']}/link", {"target_id": ids["player"]})
    m = call("GET", f"/matches/{game['id']}")
    assert m["registrations"][0]["player_id"] == ids["player"]
    assert not m["registrations"][0]["guest"]
    call("POST", f"/players/{guest['id']}/link", {"target_id": ids["admin"]}, expected=400)
    assert all(p["id"] != guest["id"] for p in call("GET", "/players"))


def test_guest_link_same_game_overlap_is_atomic(env, call, game):
    _, _, _, _, ids = env
    m = call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    guest = call("POST", "/players/guests", {"alias": "Еще гость"}, expected=201)
    call(
        "POST",
        f"/matches/{game['id']}/participants",
        {"version": m["version"], "player_id": guest["id"], "position": "field"},
    )
    call("POST", f"/players/{guest['id']}/link", {"target_id": ids["player"]}, expected=409)
    assert any(p["id"] == guest["id"] for p in call("GET", "/players"))


def test_match_edit_marks_post_stale_and_preserves_template(call, game):
    changed = call(
        "PUT",
        f"/matches/{game['id']}",
        dict(
            version=game["version"],
            starts_at=game["starts_at"],
            location="Новый адрес",
            description="",
            payment_details="",
            cost=90000,
        ),
    )
    assert changed["location"] == "Новый адрес"
    assert len(changed["publications"]) == 2
    assert sum(p["stale"] for p in changed["publications"]) == 1
    assert call("GET", "/template")["location"] == ""


def signed_data(token, age=0, user_id=102):
    values = {
        "auth_date": str(int(now().timestamp()) - age),
        "query_id": "abc",
        "user": json.dumps({"id": user_id, "first_name": "Игрок"}),
    }
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(values)


def test_telegram_auth_checks_signature_and_age():
    cfg = Settings(_env_file=None, env="test", bot_token="123:token")
    assert parse_telegram(cfg, signed_data(cfg.bot_token)).id == 102
    for data in (
        signed_data("wrong"),
        signed_data(cfg.bot_token, age=301),
        signed_data(cfg.bot_token, age=-60),
    ):
        with pytest.raises(DomainError):
            parse_telegram(cfg, data)


def test_invalid_input_and_drafts_hidden(call):
    call(
        "POST", "/matches", dict(starts_at="2026-10-02T20:00:00", location="Стадион"), expected=422
    )
    m = call(
        "POST",
        "/matches",
        dict(starts_at="2026-10-02T20:00:00+03:00", location="Стадион"),
        expected=201,
    )
    call("GET", f"/matches/{m['id']}", role="player", expected=404)
    assert call("GET", "/matches", role="player") == []
    assert "telegram_id" not in call("GET", "/players")[0]
