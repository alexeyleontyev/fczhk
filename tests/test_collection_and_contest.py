from datetime import timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from fczhk.db import database, now
from fczhk.models import Match, Player, PredictionBaseline, Publication, Registration
from fczhk.predictions import category, points
from fczhk.worker import app_link, deliver_one
from tests.test_telegram import callback_replies, command_replies, payment_button
from tests.test_workflows import populate


def test_payment_report_requires_registration_and_never_confirms_payment(env, call, game):
    path = f"/matches/{game['id']}"
    call("PUT", path + "/payment-report", {"reported": True}, role="player", expected=409)
    joined = call("POST", path + "/join", {"position": "field"}, role="player")
    reported = call("PUT", path + "/payment-report", {"reported": True}, role="player")
    r = reported["registrations"][0]
    assert r["in_main"] and not r["paid"] and not r["selected"]
    assert r["payment_status"] == "reported"
    assert (
        call("PUT", path + "/payment-report", {"reported": True}, role="player")["version"]
        == reported["version"]
    )
    call(
        "PUT",
        path + f"/registrations/{r['id']}/payment",
        {"version": reported["version"], "paid": True},
        role="player",
        expected=403,
    )
    confirmed = call(
        "PUT",
        path + f"/registrations/{r['id']}/payment",
        {"version": reported["version"], "paid": True},
    )
    assert confirmed["registrations"][0]["payment_status"] == "confirmed"
    call("PUT", path + "/payment-report", {"reported": False}, role="player", expected=409)
    reset = call(
        "PUT",
        path + f"/registrations/{r['id']}/payment",
        {"version": confirmed["version"], "paid": False, "reported": False},
    )
    assert reset["registrations"][0]["payment_status"] == "unpaid"
    assert reported["version"] == joined["version"] + 1
    call("PUT", path + "/payment-report", {"reported": True}, role="player")
    call("DELETE", path + "/join", role="player")
    rejoined = call("POST", path + "/join", {"position": "field"}, role="player")
    assert rejoined["registrations"][0]["payment_status"] == "unpaid"


def test_provisional_main_uses_queue_but_finalization_requires_admin_confirmation(env, call, game):
    populate(env[1], game["id"])
    with env[1]() as db, db.begin():
        first = db.scalar(select(Registration).order_by(Registration.id))
        first.paid = False
        first.payment_reported = True
    path = f"/matches/{game['id']}"
    before = call("GET", path)
    main = [r for r in before["registrations"] if r["in_main"]]
    assert len(main) == 18
    assert sum(r["position"] == "field" for r in main) == 16
    assert main[0]["payment_status"] == "reported"
    assert not next(r for r in before["registrations"] if r["alias"] == "Участник 16")["in_main"]
    after = call("POST", path + "/actions/finalize", {"version": before["version"]})
    selected = [r for r in after["registrations"] if r["in_main"]]
    assert len(selected) == 18 and all(r["paid"] for r in selected)
    assert not next(r for r in after["registrations"] if r["alias"] == "Участник 00")["in_main"]
    assert next(r for r in after["registrations"] if r["alias"] == "Участник 16")["in_main"]


async def test_game_payment_button_reports_once_and_waits_for_admin(env, call, monkeypatch):
    starts = now() + timedelta(days=2)
    game = call(
        "POST",
        "/matches",
        {"starts_at": starts.isoformat(), "location": "Поле оплаты"},
        expected=201,
    )
    game = call("POST", f"/matches/{game['id']}/actions/open", {"version": game["version"]})
    game = call("POST", f"/matches/{game['id']}/join", {"position": "field"}, role="player")
    replies = await command_replies(env, monkeypatch, "/game")
    button = payment_button(replies[-1].reply_markup)
    for _ in range(2):
        await callback_replies(env, monkeypatch, button.callback_data)
    after = call("GET", f"/matches/{game['id']}")
    assert after["version"] == game["version"] + 1
    assert after["registrations"][0]["payment_status"] == "reported"
    finalized = call(
        "POST", f"/matches/{game['id']}/actions/finalize", {"version": after["version"]}
    )
    assert not finalized["registrations"][0]["selected"]
    replies = await command_replies(env, monkeypatch, "/game")
    markup = replies[-1].reply_markup
    assert payment_button(markup).text == "Оплачен"
    assert not any(
        b.callback_data.startswith(("join:", "leave:"))
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data
    )


@pytest.mark.parametrize(
    "predicted,expected",
    [
        ((7, 0), [3, 1, 0, 0, 0]),
        ((3, 0), [0.5, 2, 0.5, 0, 0]),
        ((8, 8), [0, 0.5, 3, 0.5, 0]),
        ((0, 3), [0, 0, 0.5, 2, 0.5]),
        ((0, 7), [0, 0, 0, 1, 3]),
    ],
)
def test_every_matrix_cell_and_category_boundaries(predicted, expected):
    assert [
        points(*predicted, *actual) for actual in [(4, 0), (3, 0), (1, 1), (0, 3), (0, 4)]
    ] == expected
    assert category(7, 3) == "Б4" and category(6, 3) == "Б13"
    assert category(3, 7) == "Ч4" and category(3, 6) == "Ч13"


def test_public_profile_reviews_include_authors_but_no_private_history(env, call):
    target = call("POST", "/players/guests", {"alias": "Оцениваемый"}, expected=201)
    call(
        "PUT",
        f"/players/{target['id']}/ratings",
        {"position": "field", "attack": 0, "defense": 4.2, "revision": 0},
    )
    reviews = call("GET", f"/players/{target['id']}/reviews", role="player")
    assert reviews["field"][0]["author_id"] == env[4]["admin"]
    assert reviews["field"][0]["author"] == "Администратор"
    assert reviews["field"][0]["attack"] == 0 and reviews["keeper"] == []
    assert "history" not in reviews["field"][0]
    call("GET", f"/players/{target['id']}/reviews", role=None, expected=401)


def test_migration_replaces_old_contest_with_exact_sheet_totals_once(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "1c8d7e0f325a")
    engine, factory = database(url)
    with engine.begin() as db:
        db.execute(
            text("INSERT INTO players (alias, created_at) VALUES ('Дима Михей', :at)"),
            {"at": now()},
        )
        db.execute(
            text(
                "INSERT INTO matches (game_day, season, starts_at, location, description, cost, payment_details, field_limit, keeper_limit, status, version, roster_version, created_at) VALUES ('2026-10-16', '2026', :at, 'Поле', '', 0, '', 16, 2, 'completed', 1, 0, :at)"
            ),
            {"at": now()},
        )
        db.execute(
            text(
                "INSERT INTO predictions (match_id, player_id, white_score, black_score, revision, approved_version, updated_at) VALUES (1, 1, 9, 0, 1, 1, :at)"
            ),
            {"at": now()},
        )
    command.upgrade(config, "head")
    from fczhk.predictions import standings

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PredictionBaseline)) == 28
        assert db.scalar(select(func.sum(PredictionBaseline.points_half))) == 182
        assert db.execute(text("SELECT scoring_version FROM predictions")).scalar_one() == 1
        table = standings(db, season="2026")
        mine = next(r for r in table if r["alias"] == "Дима Михей")
        assert mine["points"] == mine["baseline_points"] == 4
        assert mine["predictions"] == 0 and mine["settled"] == 0
        assert standings(db, season="2025") == []
        assert (
            db.scalar(select(func.count()).select_from(Player).where(Player.alias == "Дима Михей"))
            == 1
        )
    command.upgrade(config, "head")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PredictionBaseline)) == 28
    engine.dispose()


async def test_channel_team_post_links_directly_to_prediction(env):
    cfg, factory, *_ = env
    cfg.bot_username = "club_bot"
    with factory() as db, db.begin():
        m = Match(game_day="2097-01-01", starts_at=now() + timedelta(days=2), location="Поле")
        db.add(m)
        db.flush()
        mid = m.id
        db.add(Publication(match_id=mid, kind="teams", version=1, text="Составы", chat_id="123"))
    sent = []

    class FakeBot:
        async def send_message(self, *args, **kwargs):
            sent.append(kwargs["reply_markup"])
            return SimpleNamespace(message_id=10)

    assert await deliver_one(cfg, factory, FakeBot())
    buttons = [button for row in sent[0].inline_keyboard for button in row]
    assert (
        next(b.url for b in buttons if b.text == "Сделать прогноз")
        == f"https://t.me/club_bot?startapp=game_{mid}_prediction"
    )
    cfg.bot_username = ""
    assert app_link(cfg, mid, "prediction").endswith(f"/?game={mid}&screen=prediction")
