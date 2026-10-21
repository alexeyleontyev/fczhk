"""Archive corrections preserve imported results and historical identities."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from fczhk.archive import UNKNOWN_LOCATION
from fczhk.db import now
from fczhk.models import (
    Audit,
    Match,
    MatchResult,
    Prediction,
    Publication,
    ResultGoal,
    ResultParticipant,
    TeamRatingSnapshot,
    TeamSnapshot,
)
from fczhk.scheduling import MOSCOW


@pytest.fixture
def archived(env, call):
    with env[1]() as db, db.begin():
        match = Match(
            game_day="2026-06-26",
            starts_at=datetime(2026, 6, 26, 12, tzinfo=MOSCOW),
            location=UNKNOWN_LOCATION,
            status="completed",
            approved_version=1,
        )
        db.add(match)
        db.flush()
        db.add(MatchResult(match_id=match.id, completed=True))
        db.flush()
        db.add_all(
            ResultParticipant(match_id=match.id, player_id=pid, team=team, position="field")
            for pid, team in ((env[4]["admin"], "white"), (env[4]["player"], "black"))
        )
        db.add(
            ResultGoal(
                match_id=match.id,
                id=str(uuid4()),
                team="white",
                kind="goal",
                author_id=env[4]["admin"],
            )
        )
        db.add(
            Prediction(
                match_id=match.id,
                player_id=env[4]["player"],
                white_score=1,
                black_score=0,
                approved_version=1,
            )
        )
        db.add(
            Audit(
                match_id=match.id,
                action="history.imported",
                data={"date_only": True, "source_cells": {"A1": "original"}},
            )
        )
        snapshot = TeamSnapshot(match_id=match.id, version=1, teams=[])
        db.add(snapshot)
        db.flush()
        db.add(
            TeamRatingSnapshot(
                snapshot_id=snapshot.id, data={"method": "historical", "lineup_inputs": []}
            )
        )
        mid = match.id
    return call("GET", f"/matches/{mid}")


def body(match):
    return dict(
        version=match["version"],
        game_day=match["game_day"],
        start_time=None,
        location="",
        season=match["season"],
    )


def test_archive_metadata_edits_preserve_result_and_history_and_reveal_known_time(
    env, call, archived
):
    m = archived
    path = f"/matches/{m['id']}"
    assert m["historical"] and not m["time_known"]
    original_result = m["result"]
    with env[1]() as db:
        source = db.scalar(select(Audit).where(Audit.action == "history.imported")).data
        snapshot = db.scalar(select(TeamRatingSnapshot)).data
    request = {
        **body(m),
        "game_day": "2026-06-25",
        "start_time": "20:30",
        "location": "Манеж",
        "season": "2024-2025",
    }
    changed = call("PUT", path + "/archive-details", request)
    assert changed["status"] == "completed" and changed["historical"]
    assert changed["time_known"] and changed["game_day"] == "2026-06-25"
    assert (
        datetime.fromisoformat(changed["starts_at"]).astimezone(MOSCOW).strftime("%H:%M") == "20:30"
    )
    assert changed["location"] == "Манеж" and changed["season"] == "2024-2025"
    assert changed["roster_version"] == m["roster_version"]
    assert {k: v for k, v in changed["result"].items() if k != "version"} == {
        k: v for k, v in original_result.items() if k != "version"
    }
    summary = call("GET", "/matches?season=2024-2025")[0]
    assert summary["time_known"] and summary["game_day"] == changed["game_day"]
    history = call("GET", path + "/history")
    assert history["audit"][0]["action"] == "match.archive_details_edited"
    assert history["audit"][0]["actor"] == "Администратор"
    assert history["audit"][0]["data"]["old"]["time_known"] is False
    assert history["audit"][0]["data"]["new"]["time_known"] is True
    with env[1]() as db:
        assert db.scalar(select(Audit).where(Audit.action == "history.imported")).data == source
        assert db.scalar(select(TeamRatingSnapshot)).data == snapshot
        assert db.scalar(select(Prediction)).white_score == 1
        assert db.get(Match, m["id"]).approved_version == 1
        assert list(db.scalars(select(Publication))) == []
    # Identical saves are harmless; a stale form cannot overwrite a later correction.
    again = call("PUT", path + "/archive-details", {**request, "version": changed["version"]})
    assert again["version"] == changed["version"]
    call("PUT", path + "/archive-details", request, expected=409)


def test_unknown_time_and_location_remain_explicit_and_can_be_cleared(call, archived):
    path = f"/matches/{archived['id']}"
    unchanged = call("PUT", path + "/archive-details", body(archived))
    assert unchanged["version"] == archived["version"]
    assert unchanged["starts_at"] == archived["starts_at"] and not unchanged["time_known"]
    changed = call(
        "PUT",
        path + "/archive-details",
        {**body(archived), "start_time": "20:30", "location": "Поле"},
    )
    cleared = call("PUT", path + "/archive-details", body(changed))
    assert not cleared["time_known"] and cleared["location"] == UNKNOWN_LOCATION
    assert not call("GET", "/matches")[0]["time_known"]


@pytest.mark.parametrize(
    "bad", ["member", "anonymous", "future", "duplicate", "invalid_time", "extra", "short_place"]
)
def test_invalid_archive_edits_do_not_change_the_match(env, call, archived, bad):
    request = body(archived)
    role, expected = "admin", 400
    if bad == "member":
        role, expected = "player", 403
    elif bad == "anonymous":
        role, expected = None, 401
    elif bad == "future":
        request["game_day"] = (now() + timedelta(days=2)).date().isoformat()
    elif bad == "duplicate":
        with env[1]() as db, db.begin():
            db.add(
                Match(
                    game_day="2026-06-25",
                    starts_at=datetime(2026, 6, 25, 12, tzinfo=MOSCOW),
                    location="Другая игра",
                )
            )
        request["game_day"], expected = "2026-06-25", 409
    elif bad == "invalid_time":
        request["start_time"], expected = "25:99", 422
    elif bad == "extra":
        request["cost"], expected = 0, 422
    elif bad == "short_place":
        request["location"], expected = "X", 422
    call("PUT", f"/matches/{archived['id']}/archive-details", request, role=role, expected=expected)
    assert call("GET", f"/matches/{archived['id']}") == archived


def test_archive_edit_does_not_apply_to_live_game(call, game):
    call("PUT", f"/matches/{game['id']}/archive-details", body(game), expected=409)
    assert call("GET", f"/matches/{game['id']}") == game


def test_cancelled_game_correction_does_not_reopen_it(env, call):
    with env[1]() as db, db.begin():
        match = Match(
            game_day="2032-06-04",
            starts_at=datetime(2032, 6, 4, 20, tzinfo=MOSCOW),
            location="Поле",
            status="cancelled",
        )
        db.add(match)
        db.flush()
        mid = match.id
    m = call("GET", f"/matches/{mid}")
    changed = call(
        "PUT",
        f"/matches/{mid}/archive-details",
        {**body(m), "start_time": "20:30", "location": "Манеж"},
    )
    assert changed["status"] == "cancelled" and changed["result"] is None
    call("POST", f"/matches/{mid}/join", {"position": "field"}, role="player", expected=400)


def test_archive_metadata_correction_marks_old_posts_without_queuing_new_ones(env, call, archived):
    with env[1]() as db, db.begin():
        db.add(Publication(match_id=archived["id"], kind="result", version=1, text="Старый итог"))
    call(
        "PUT",
        f"/matches/{archived['id']}/archive-details",
        {**body(archived), "location": "Новый стадион"},
    )
    with env[1]() as db:
        posts = list(db.scalars(select(Publication)))
        assert len(posts) == 1 and posts[0].stale and posts[0].status == "cancelled"
