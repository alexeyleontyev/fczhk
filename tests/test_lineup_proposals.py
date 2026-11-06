from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from fczhk.models import Audit, LineupProposal, Match, Player, Publication
from tests.test_lineups import payload, preview
from tests.test_ratings import prepared, vote


@pytest.fixture
def future_lineup(env, call, game):
    m = prepared(call, game, keepers=2)
    with env[1]() as db, db.begin():
        match = db.get(Match, m["id"])
        match.starts_at = datetime(2099, 10, 2, 17, tzinfo=UTC)
        match.game_day = "2099-10-02"
    return call("GET", f"/matches/{m['id']}")


def proposal_body(call, m, revision=0):
    p = preview(call, m, role="player")
    return {
        "roster_version": p["roster_version"],
        "fingerprint": p["fingerprint"],
        "assignments": p["result"]["variants"][0]["assignments"],
        "revision": revision,
    }


def test_one_proposal_per_member_with_independent_revisions_and_no_publications(
    env, call, future_lineup
):
    m = future_lineup
    path = f"/matches/{m['id']}/lineup/proposals"
    before = call("GET", f"/matches/{m['id']}")
    with env[1]() as db:
        posts = db.scalar(select(func.count()).select_from(Publication))
    body = proposal_body(call, m)
    first = call("PUT", path + "/mine", body, role="player")
    assert first["revision"] == 1
    listing = call("GET", path)
    assert len(listing["proposals"]) == 1
    saved = listing["proposals"][0]
    assert saved["author_id"] == env[4]["player"]
    assert saved["assignments"] == body["assignments"]
    assert not saved["roster_stale"] and not saved["ratings_changed"]
    assert call("GET", path, role="player")["mine_revision"] == 1
    call("PUT", path + "/mine", body, role="player", expected=409)
    changed = {
        **body,
        "revision": 1,
        "assignments": {
            rid: "black" if team == "white" else "white"
            for rid, team in body["assignments"].items()
        },
    }
    assert call("PUT", path + "/mine", changed, role="player") == {**first, "revision": 2}
    call("PUT", path + "/mine", body)  # An independent author may publish the same assignment.
    assert len(call("GET", path)["proposals"]) == 2
    with env[1]() as db, db.begin():
        db.get(Player, env[4]["player"]).alias = "Новое имя"
    assert any(p["author"] == "Новое имя" for p in call("GET", path)["proposals"])
    assert call("GET", f"/matches/{m['id']}")["version"] == before["version"]
    assert call("GET", f"/matches/{m['id']}")["registrations"] == before["registrations"]
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(Publication)) == posts
        assert db.scalar(select(func.count()).select_from(LineupProposal)) == 2


def test_withdraw_and_republish_keep_history_and_revision(env, call, future_lineup):
    m = future_lineup
    path = f"/matches/{m['id']}/lineup/proposals"
    body = proposal_body(call, m)
    first = call("PUT", path + "/mine", body, role="player")
    call("POST", path + "/mine/withdraw", {"revision": 2}, role="player", expected=409)
    assert call("POST", path + "/mine/withdraw", {"revision": 1}, role="player") == {"revision": 2}
    assert call("GET", path, role="player") == {
        "proposals": [],
        "mine_revision": 2,
        "editable": True,
    }
    call("PUT", path + "/mine", {**body, "revision": 1}, role="player", expected=409)
    assert call("PUT", path + "/mine", {**body, "revision": 2}, role="player") == {
        **first,
        "revision": 3,
    }
    with env[1]() as db:
        assert db.scalar(select(func.count()).select_from(LineupProposal)) == 1
        actions = list(db.scalars(select(Audit.action).where(Audit.action.like("lineup.propos%"))))
        assert actions == ["lineup.proposed", "lineup.proposal_withdrawn", "lineup.proposed"]


@pytest.mark.parametrize(
    "bad",
    [
        "anonymous",
        "spoof",
        "missing",
        "extra",
        "unassigned",
        "unequal",
        "placement",
        "started",
        "stale",
    ],
)
def test_reject_invalid_proposals(env, call, future_lineup, bad):
    m = future_lineup
    body = proposal_body(call, m)
    rid = next(iter(body["assignments"]))
    expected = 400
    role = "player"
    if bad == "anonymous":
        role, expected = None, 401
    elif bad == "spoof":
        body["author_id"] = env[4]["admin"]
        expected = 422
    elif bad == "missing":
        body["assignments"].pop(rid)
        expected = 409
    elif bad == "extra":
        body["assignments"][999999] = "white"
        expected = 409
    elif bad == "unassigned":
        body["assignments"][rid] = None
    elif bad == "unequal":
        body["assignments"] = {r: "white" for r in body["assignments"]}
    elif bad == "placement":
        body["placements"] = {
            rid: {"x": 0.5, "y": 0.1 if body["assignments"][rid] == "white" else 0.9}
        }
    elif bad == "started":
        with env[1]() as db, db.begin():
            db.get(Match, m["id"]).starts_at = datetime(2020, 1, 1, tzinfo=UTC)
        expected = 409
    elif bad == "stale":
        body["roster_version"] += 1
        expected = 409
    call("PUT", f"/matches/{m['id']}/lineup/proposals/mine", body, role=role, expected=expected)
    with env[1]() as db:
        assert not db.scalar(select(LineupProposal.id))


def test_proposal_snapshot_and_confirmation_keep_author_and_detect_updates(
    env, call, future_lineup
):
    m = future_lineup
    path = f"/matches/{m['id']}/lineup/proposals"
    p = preview(call, m)
    body = proposal_body(call, m)
    first = call("PUT", path + "/mine", body, role="player")
    ref = {"proposal_id": first["id"], "proposal_revision": 1, "source": "proposal"}
    confirm = {**payload(p), **ref}
    call("POST", f"/matches/{m['id']}/lineup/confirm", confirm, role="player", expected=403)
    done = call("POST", f"/matches/{m['id']}/lineup/confirm", confirm)
    assert done["status"] == "approved"
    with env[1]() as db:
        audit = db.scalar(select(Audit).where(Audit.action == "lineup.confirmed"))
        assert audit.data | {"author_id": env[4]["player"], **ref} == audit.data | {
            "source": "proposal"
        }
    frozen = call("GET", path)["proposals"][0]["players"]
    player = next(p for p in frozen if p["position"] == "field")
    vote(call, player["player_id"], attack=0, defense=0)
    saved = call("GET", path)["proposals"][0]
    assert saved["players"] == frozen
    assert saved["ratings_changed"] and not saved["roster_stale"]
    current = call("GET", f"/matches/{m['id']}/lineup")
    call(
        "POST",
        f"/matches/{m['id']}/lineup/confirm",
        {**confirm, "version": current["version"], "fingerprint": current["fingerprint"]},
        expected=409,
    )


def test_changed_roster_and_withdrawn_proposals_cannot_be_confirmed(env, call, future_lineup):
    m = future_lineup
    p = preview(call, m)
    path = f"/matches/{m['id']}/lineup/proposals"
    first = call("PUT", path + "/mine", proposal_body(call, m), role="player")
    confirm = {
        **payload(p),
        "source": "proposal",
        "proposal_id": first["id"],
        "proposal_revision": 1,
    }
    with env[1]() as db, db.begin():
        db.get(Match, m["id"]).roster_version += 1
    assert call("GET", path)["proposals"][0]["roster_stale"]
    current = call("GET", f"/matches/{m['id']}/lineup")
    call(
        "POST",
        f"/matches/{m['id']}/lineup/confirm",
        {**confirm, "roster_version": current["roster_version"]},
        expected=409,
    )
    call("POST", path + "/mine/withdraw", {"revision": 1}, role="player")
    call("POST", f"/matches/{m['id']}/lineup/confirm", confirm, expected=409)
