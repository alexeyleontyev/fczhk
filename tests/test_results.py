from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from fczhk.db import now
from fczhk.models import (
    Match,
    MatchResult,
    Player,
    Publication,
    Registration,
    ResultGoal,
    ResultParticipant,
)
from fczhk.results import win_rate


def test_win_rate_examples():
    assert win_rate(1, 1, 3) == 50
    assert win_rate(3, 1, 5) == 70
    assert win_rate(0, 0, 0) is None


@pytest.fixture
def played(env, call):
    _, factory, _, _, ids = env
    with factory() as db, db.begin():
        m = Match(
            game_day="2020-01-03",
            starts_at=now() - timedelta(days=1),
            location="Поле",
            status="approved",
            approved_version=1,
        )
        guest = Player(alias="Гость бомбардир")
        mate = Player(alias="Вратарь партнёр", telegram_id=555)
        db.add_all([m, guest, mate])
        db.flush()
        for pid, team, position in [
            (ids["admin"], "white", "field"),
            (mate.id, "white", "keeper"),
            (guest.id, "black", "field"),
        ]:
            db.add(
                Registration(
                    match_id=m.id, player_id=pid, team=team, position=position, selected=True
                )
            )
        mid, gid, mateid = m.id, guest.id, mate.id
    return mid, gid, mateid


def event(team, author=None, assist=None, kind="goal"):
    return dict(id=str(uuid4()), team=team, kind=kind, author_id=author, assist_id=assist)


def payload(call, mid, completed=False):
    result = call("GET", f"/matches/{mid}/result")
    return dict(
        version=result["version"],
        completed=completed,
        participants=[
            {k: p[k] for k in ("player_id", "team", "position")} for p in result["participants"]
        ],
        goals=result["goals"],
    )


def test_draft_completed_corrections_and_partners(env, call, played):
    mid, guest, mate = played
    admin = env[4]["admin"]
    body = payload(call, mid)
    body["goals"] = [
        event("white", admin, mate),
        event("white", guest, kind="own_goal"),
        event("black"),
    ]
    draft = call("PUT", f"/matches/{mid}/result", body)
    assert draft["score"] == {"white": 2, "black": 1}
    assert call("GET", f"/players/{admin}/stats")["games"] == 0
    body.update(version=draft["version"], completed=True)
    done = call("PUT", f"/matches/{mid}/result", body)
    stats = call("GET", f"/players/{admin}/stats", role="player")
    assert (stats["games"], stats["wins"], stats["goals"], stats["assists"]) == (1, 1, 1, 0)
    assert [p["player_id"] for p in stats["partners"]] == [mate]
    assert stats["win_rate"] == stats["partners"][0]["win_rate"] == 100
    assert tuple(stats["partners"][0][key] for key in ("wins", "draws", "losses")) == (1, 0, 0)
    assert (stats["matches"][0]["goals"], stats["matches"][0]["assists"]) == (1, 0)
    mate_stats = call("GET", f"/players/{mate}/stats")
    assert mate_stats["assists"] == mate_stats["matches"][0]["assists"] == 1
    assert call("GET", f"/players/{guest}/stats")["goals"] == 0
    body.update(version=done["version"])
    body["goals"].append(event("black", guest))
    corrected = call("PUT", f"/matches/{mid}/result", body)
    stats = call("GET", f"/players/{admin}/stats")
    assert (stats["games"], stats["wins"], stats["draws"]) == (1, 0, 1)
    assert stats["win_rate"] == stats["partners"][0]["win_rate"] == 50
    assert tuple(stats["partners"][0][key] for key in ("wins", "draws", "losses")) == (0, 1, 0)
    assert call("GET", f"/players/{guest}/stats")["goals"] == 1
    call("PUT", f"/matches/{mid}/result", body, expected=409)
    assert len(call("GET", f"/matches/{mid}/history")["audit"]) == 3
    assert call("GET", f"/matches/{mid}")["status"] == "completed"
    assert corrected["score"] == {"white": 2, "black": 2}
    body.update(version=corrected["version"], completed=False)
    call("PUT", f"/matches/{mid}/result", body, expected=400)


def test_result_post_uses_actual_teams_and_events_and_replaces_outdated_posts(env, call, played):
    cfg, factory, _, _, ids = env
    cfg.publication_chat_id = "-1005678"
    mid, guest, mate = played
    body = payload(call, mid)
    # The actual teams can differ from the organizational lineup.
    next(p for p in body["participants"] if p["player_id"] == mate)["team"] = "black"
    body["goals"] = [
        event("black", guest, mate),
        event("white", guest, kind="own_goal"),
        event("white", kind="own_goal"),
        event("black"),
    ]
    draft = call("PUT", f"/matches/{mid}/result", body)
    with factory() as db:
        assert not list(db.scalars(select(Publication)))
    body.update(version=draft["version"], completed=True)
    done = call("PUT", f"/matches/{mid}/result", body)
    with factory() as db:
        post = db.scalar(select(Publication).where(Publication.kind == "result"))
        assert post.chat_id == cfg.publication_chat_id and post.version == done["version"]
        assert "Белые 2 : 2 Чёрные" in post.text and "Ничья" in post.text
        white, black = post.text.split("\n⚪ Белые\n", 1)[1].split("\n⚫ Чёрные\n")
        assert "Администратор" in white and "🧤 Вратарь партнёр" in black
        assert "⚽ Гость бомбардир · передача: Вратарь партнёр" in black
        assert "⚽ автор не указан · передача: не указана" in black
        assert "Автогол — Гость бомбардир" in white and "Автогол — автор не указан" in white
        original_id = post.id
    # A stale HTTP retry cannot create a second post.
    call("PUT", f"/matches/{mid}/result", body, expected=409)
    body.update(version=done["version"])
    unchanged = call("PUT", f"/matches/{mid}/result", body)
    with factory() as db, db.begin():
        assert len(list(db.scalars(select(Publication)))) == 1
        post = db.get(Publication, original_id)
        post.status, post.message_ids = "sent", [123]
    body.update(version=unchanged["version"])
    body["goals"].append(event("white", ids["admin"]))
    corrected = call("PUT", f"/matches/{mid}/result", body)
    with factory() as db:
        posts = list(db.scalars(select(Publication).order_by(Publication.id)))
        assert len(posts) == 2
        assert posts[0].stale and posts[0].status == "sent"
        assert posts[1].version == corrected["version"] and not posts[1].stale
        assert "Исправленный итог" in posts[1].text and "Победа белых" in posts[1].text
    # A further correction cancels the unsent outdated version instead of delivering it.
    body.update(version=corrected["version"])
    body["goals"] = []
    call("PUT", f"/matches/{mid}/result", body)
    with factory() as db:
        posts = list(db.scalars(select(Publication).order_by(Publication.id)))
        assert posts[1].stale and posts[1].status == "cancelled"
        assert "Белые 0 : 0 Чёрные" in posts[2].text and posts[2].text.count("Голов нет") == 2


async def test_completed_result_delivered_as_plain_text_once(env, call, played):
    from types import SimpleNamespace

    from fczhk.worker import deliver_one

    cfg, factory, _, _, _ = env
    cfg.publication_chat_id = "-1005678"
    mid, guest, _ = played
    with factory() as db, db.begin():
        db.get(Player, guest).alias = "Гость <b> & ⚽"
    body = payload(call, mid, completed=True)
    body["goals"] = [event("black", guest)]
    call("PUT", f"/matches/{mid}/result", body)
    sent = []

    class Bot:
        async def send_message(self, chat, text, **kwargs):
            sent.append((chat, text, kwargs))
            return SimpleNamespace(message_id=42)

    assert await deliver_one(cfg, factory, Bot())
    assert not await deliver_one(cfg, factory, Bot())
    assert len(sent) == 1 and sent[0][0] == cfg.publication_chat_id
    assert "⚽ Гость <b> & ⚽" in sent[0][1] and sent[0][2]["parse_mode"] is None


async def test_long_result_with_emoji_is_split_and_all_outdated_parts_are_marked(env, call, played):
    from types import SimpleNamespace

    from fczhk.worker import deliver_one, mark_stale

    cfg, factory, _, _, ids = env
    cfg.publication_chat_id = "-1005678"
    mid, _, mate = played
    with factory() as db, db.begin():
        db.get(Player, ids["admin"]).alias = "⚽" * 60
        db.get(Player, mate).alias = "🧤" * 60
    body = payload(call, mid, completed=True)
    body["goals"] = [event("white", ids["admin"], mate) for _ in range(200)]
    done = call("PUT", f"/matches/{mid}/result", body)
    sent, edited = [], []

    class Bot:
        async def send_message(self, chat, text, **kwargs):
            sent.append((text, kwargs))
            return SimpleNamespace(message_id=len(sent))

        async def edit_message_text(self, **kwargs):
            edited.append(kwargs)

    bot = Bot()
    assert await deliver_one(cfg, factory, bot)
    assert len(sent) > 1
    assert all(len(text.encode("utf-16-le")) // 2 <= 3500 for text, _ in sent)
    assert all(kwargs["parse_mode"] is None for _, kwargs in sent)
    assert all(kwargs["reply_markup"] is None for _, kwargs in sent[:-1])
    assert sent[-1][1]["reply_markup"] is not None
    assert sum(text.count(" · передача: ") for text, _ in sent) == 200
    body.update(version=done["version"])
    body["goals"] = []
    call("PUT", f"/matches/{mid}/result", body)
    await mark_stale(cfg, factory, bot)
    assert len(edited) == len(sent)
    assert [part["message_id"] for part in edited] == list(range(1, len(sent) + 1))
    assert all("результат исправлен" in part["text"] for part in edited)
    assert all(len(part["text"].encode("utf-16-le")) // 2 < 4096 for part in edited)
    with factory() as db:
        assert db.scalar(select(Publication).order_by(Publication.id)).stale_marked


def test_partner_win_rate_and_per_match_contributions(env, call, played):
    mid, guest, mate = played
    admin = env[4]["admin"]
    body = payload(call, mid, completed=True)
    body["goals"] = [
        event("white", admin, mate),
        event("white", mate, admin),
        event("black", guest),
    ]
    call("PUT", f"/matches/{mid}/result", body)
    with env[1]() as db, db.begin():
        match = Match(
            game_day="2020-01-04",
            starts_at=now() - timedelta(hours=1),
            location="Поле",
            status="completed",
        )
        db.add(match)
        db.flush()
        db.add(MatchResult(match_id=match.id, completed=True))
        db.add_all(
            [
                ResultParticipant(
                    match_id=match.id, player_id=admin, team="white", position="field"
                ),
                ResultParticipant(
                    match_id=match.id, player_id=mate, team="white", position="keeper"
                ),
                ResultParticipant(
                    match_id=match.id, player_id=guest, team="black", position="field"
                ),
            ]
        )
        loss = Match(
            game_day="2020-01-05",
            starts_at=now() - timedelta(minutes=30),
            location="Поле",
            status="completed",
        )
        db.add(loss)
        db.flush()
        db.add_all(
            [
                MatchResult(match_id=loss.id, completed=True),
                ResultParticipant(
                    match_id=loss.id, player_id=admin, team="white", position="field"
                ),
                ResultParticipant(
                    match_id=loss.id, player_id=mate, team="white", position="keeper"
                ),
                ResultParticipant(
                    match_id=loss.id, player_id=guest, team="black", position="field"
                ),
                ResultGoal(
                    match_id=loss.id, id=str(uuid4()), team="black", kind="goal", author_id=guest
                ),
            ]
        )
    stats = call("GET", f"/players/{admin}/stats", role="player")
    assert (stats["games"], stats["wins"], stats["draws"], stats["losses"]) == (3, 1, 1, 1)
    assert stats["win_rate"] == 50
    assert stats["partners"][0] == {
        "player_id": mate,
        "alias": "Вратарь партнёр",
        "games": 3,
        "wins": 1,
        "draws": 1,
        "losses": 1,
        "win_rate": 50,
    }
    assert [(m["goals"], m["assists"]) for m in stats["matches"]] == [
        (0, 0),
        (0, 0),
        (1, 1),
    ]


@pytest.mark.parametrize(
    "case",
    [
        "outsider",
        "self_assist",
        "opponent_assist",
        "wrong_team",
        "own_assist",
        "duplicate",
        "remove_scorer",
        "move_scorer",
    ],
)
def test_invalid_events_are_atomic(env, call, played, case):
    mid, guest, mate = played
    admin, outsider = env[4]["admin"], env[4]["player"]
    body = payload(call, mid, True)
    goal = event("white", admin, mate)
    if case == "outsider":
        goal["author_id"] = outsider
    if case == "self_assist":
        goal["assist_id"] = admin
    if case == "opponent_assist":
        goal["assist_id"] = guest
    if case == "wrong_team":
        goal["author_id"] = guest
    if case == "own_assist":
        goal.update(kind="own_goal", author_id=guest)
    if case == "remove_scorer":
        body["participants"] = [p for p in body["participants"] if p["player_id"] != admin]
    if case == "move_scorer":
        next(p for p in body["participants"] if p["player_id"] == admin)["team"] = "black"
    body["goals"] = [goal, goal] if case == "duplicate" else [goal]
    call("PUT", f"/matches/{mid}/result", body, expected=400)
    assert call("GET", f"/matches/{mid}/result")["exists"] is False


def test_actual_replacement_guests_and_permissions(env, call, played):
    mid, guest, mate = played
    admin, target = env[4]["admin"], env[4]["player"]
    body = payload(call, mid, True)
    call("PUT", f"/matches/{mid}/result", body, role="player", expected=403)
    body["participants"] = [p for p in body["participants"] if p["player_id"] != mate]
    body["goals"] = [event("black", guest)]
    call("PUT", f"/matches/{mid}/result", body)
    assert call("GET", f"/players/{mate}/stats")["games"] == 0
    call("POST", f"/players/{guest}/link", {"target_id": target})
    stats = call("GET", f"/players/{target}/stats")
    assert (stats["games"], stats["wins"], stats["goals"]) == (1, 1, 1)
    old_stats = call("GET", f"/players/{guest}/stats")
    assert old_stats == stats
    body = payload(call, mid, True)
    assert body["goals"][0]["author_id"] == target
    call("PUT", f"/matches/{mid}/result", body)
    m = call("GET", f"/matches/{mid}")
    rid = next(r["id"] for r in m["registrations"] if r["player_id"] == admin)
    call(
        "POST",
        f"/matches/{mid}/registrations/{rid}/remove",
        {"version": m["version"]},
        expected=400,
    )
    call("PUT", f"/matches/{mid}/teams", {"version": m["version"], "assignments": {}}, expected=400)
    assert call("GET", f"/players/{target}/stats")["goals"] == 1
    with env[1]() as db:
        assert len(list(db.scalars(select(ResultGoal)))) == 1


def test_start_boundary_and_unapproved_results(env, call, played, monkeypatch):
    mid, _, _ = played
    with env[1]() as db:
        start = db.get(Match, mid).starts_at
    body = payload(call, mid, True)
    monkeypatch.setattr("fczhk.results.now", lambda: start - timedelta(microseconds=1))
    call("PUT", f"/matches/{mid}/result", body, expected=400)
    monkeypatch.setattr("fczhk.results.now", lambda: start)
    call("PUT", f"/matches/{mid}/result", body)


def test_link_overlap_in_actual_roster_rejected(env, call, played):
    mid, guest, _ = played
    target = env[4]["player"]
    body = payload(call, mid, True)
    body["participants"].append(dict(player_id=target, team="black", position="field"))
    call("PUT", f"/matches/{mid}/result", body)
    call("POST", f"/players/{guest}/link", {"target_id": target}, expected=409)
    assert call("GET", f"/players/{guest}/stats")["player_id"] == guest
