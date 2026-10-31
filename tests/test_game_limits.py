import pytest

from fczhk.models import Player, Registration
from tests.test_ratings import add_guest, prepared


def edit(call, match, expected=200, role="admin", **changes):
    body = {
        key: match[key]
        for key in ("starts_at", "location", "season", "description", "cost", "payment_details")
    }
    return call(
        "PUT",
        f"/matches/{match['id']}",
        {**body, "version": match["version"], **changes},
        role=role,
        expected=expected,
    )


def test_admin_expands_full_collection_to_eighteen_fields_and_approves_two_subs_per_team(
    call, game
):
    m = prepared(call, game, n=16, keepers=2)
    path = f"/matches/{m['id']}"
    first = m["registrations"][0]
    m = call(
        "PUT",
        path + f"/registrations/{first['id']}/payment",
        {
            "version": m["version"],
            "paid": True,
            "reported": True,
        },
    )
    before = m["registrations"]
    m = edit(call, m, field_limit=18, keeper_limit=2)
    assert m["registrations"] == before
    m, _ = add_guest(call, m, "Дополнительный 17")
    m, _ = add_guest(call, m, "Дополнительный 18")
    extra = call("POST", "/players/guests", {"alias": "Лишний 19"}, expected=201)
    call(
        "POST",
        path + "/participants",
        {
            "version": m["version"],
            "player_id": extra["id"],
            "position": "field",
        },
        expected=409,
    )
    for method in ("community", "game"):
        preview = call(
            "POST",
            path + "/lineup/preview",
            {
                "version": m["version"],
                "method": method,
            },
            role="player",
        )
        assert len(preview["players"]) == 20
        for variant in preview["result"]["variants"]:
            for team in ("white", "black"):
                members = [
                    p
                    for p in preview["players"]
                    if variant["assignments"][str(p["registration_id"])] == team
                ]
                assert sum(p["position"] == "field" for p in members) == 9
                assert sum(p["position"] == "keeper" for p in members) == 1
    m = call(
        "POST",
        path + "/lineup/confirm",
        {
            **{key: preview[key] for key in ("version", "roster_version", "fingerprint")},
            "assignments": preview["result"]["variants"][0]["assignments"],
        },
    )
    assert m["status"] == "approved"
    assert len([r for r in m["registrations"] if r["selected"]]) == 20
    assert next(r for r in m["registrations"] if r["id"] == first["id"])["paid"]
    edit(call, m, field_limit=16, expected=409)


def test_open_capacity_controls_queue_and_paid_selection_without_resetting_registration(
    env, call, game
):
    with env[1]() as db, db.begin():
        players = [Player(alias=f"Очередь {i:02}") for i in range(19)]
        db.add_all(players)
        db.flush()
        db.add_all(
            Registration(
                match_id=game["id"],
                player_id=p.id,
                position="field",
                paid=True,
                payment_reported=True,
            )
            for p in players
        )
    m = call("GET", f"/matches/{game['id']}")
    assert sum(r["in_main"] for r in m["registrations"]) == 16
    m = edit(call, m, field_limit=18)
    assert sum(r["in_main"] for r in m["registrations"]) == 18
    assert not m["registrations"][-1]["in_main"]
    assert all(r["paid"] and r["payment_reported"] for r in m["registrations"])
    timestamps = [r["registered_at"] for r in m["registrations"]]
    m = edit(call, m, location="Другое поле")  # Legacy clients omit limits.
    assert m["field_limit"] == 18 and m["keeper_limit"] == 2
    m = call("POST", f"/matches/{m['id']}/actions/finalize", {"version": m["version"]})
    assert sum(r["selected"] for r in m["registrations"]) == 18
    assert [r["registered_at"] for r in m["registrations"]] == timestamps


@pytest.mark.parametrize(
    "limits",
    [
        {"field_limit": 1},
        {"field_limit": 19},
        {"field_limit": True},
        {"keeper_limit": -1},
        {"keeper_limit": 3},
    ],
)
def test_invalid_capacity_is_rejected_without_changes(call, game, limits):
    edit(call, game, expected=422, **limits)
    assert call("GET", f"/matches/{game['id']}") == game


def test_only_admin_changes_limits_and_creation_accepts_custom_capacity(call, game):
    edit(call, game, role="player", field_limit=18, expected=403)
    m = call(
        "POST",
        "/matches",
        {
            "starts_at": "2038-10-01T20:30:00+03:00",
            "location": "Две замены",
            "field_limit": 18,
            "keeper_limit": 2,
        },
        expected=201,
    )
    assert m["field_limit"] == 18 and m["keeper_limit"] == 2
