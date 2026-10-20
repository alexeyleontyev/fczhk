from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import select

from fczhk.auth import create_session
from fczhk.db import now
from fczhk.models import Auction, AuctionLot, GameTemplate, Match, Player, Publication, Registration


@pytest.fixture
def auction_game(env, call):
    cfg, factory, _, tokens, ids = env
    with factory() as db, db.begin():
        db.get(GameTemplate, 1).extended_chat_id = "-1005678"
        m = Match(
            game_day="2020-01-03",
            starts_at=now() + timedelta(days=1),
            location="Торги",
            status="finalized",
        )
        players = [Player(alias=f"Лот {i}") for i in range(4)]
        observer = Player(alias="Наблюдатель", telegram_id=303)
        db.add_all([m, observer, *players])
        db.flush()
        tokens["observer"] = create_session(db, cfg, observer)
        for pid in [ids["admin"], ids["player"], *[p.id for p in players]]:
            db.add(Registration(match_id=m.id, player_id=pid, position="field", selected=True))
        mid = m.id
    return mid


def start(call, env, mid, **kw):
    m = call("GET", f"/matches/{mid}")
    return call(
        "POST",
        f"/matches/{mid}/auction",
        dict(
            version=m["version"],
            white_captain=env[4]["admin"],
            black_captain=env[4]["player"],
            **kw,
        ),
        expected=201,
    )


def bid(call, mid, a, amount, role="admin", expected=200):
    return call(
        "POST",
        f"/matches/{mid}/auction/bids",
        dict(auction_id=a["id"], lot_id=a["current"]["id"], amount=amount),
        role=role,
        expected=expected,
    )


def control(call, mid, a, action, expected=200):
    return call(
        "POST",
        f"/matches/{mid}/auction/control",
        dict(auction_id=a["id"], revision=a["revision"], action=action),
        expected=expected,
    )


def test_lineup_preview_hides_pending_bids_and_cannot_override_active_auction(
    env, call, auction_game
):
    a = start(call, env, auction_game)
    a = bid(call, auction_game, a, 17)
    path = f"/matches/{auction_game}"
    m = call("GET", path)
    p = call(
        "POST", path + "/lineup/preview", dict(version=m["version"], method="game"), role="observer"
    )
    assert set(p["auction"]) == {"id", "status", "assignments", "prices"}
    assert p["auction"]["prices"] == {}
    body = {k: p[k] for k in ("version", "roster_version", "fingerprint")}
    body.update(assignments=p["result"]["variants"][0]["assignments"])
    call("POST", path + "/lineup/confirm", body, expected=409)
    control(call, auction_game, a, "pause")
    call("POST", path + "/lineup/confirm", body, expected=409)
    assert call("GET", path + "/balance") == []


def test_demo_concurrent_bids_wait_for_the_first_transaction(env, call, auction_game):
    from fczhk import auctions
    from fczhk.schemas import AuctionBid
    from fczhk.services import get_match

    cfg, factory, _, _, ids = env
    auction = start(call, env, auction_game)
    first_read, release_first = Event(), Event()
    second_started, second_read = Event(), Event()

    def submit(first):
        with factory() as db, db.begin():
            if not first:
                second_started.set()
            match = get_match(db, auction_game, lock=True)
            if first:
                first_read.set()
                assert release_first.wait(5)
            else:
                second_read.set()
            auctions.bid(
                db,
                ids["admin" if first else "player"],
                match,
                AuctionBid(
                    auction_id=auction["id"],
                    lot_id=auction["current"]["id"],
                    amount=10 if first else 0,
                ),
                cfg,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, True)
        try:
            assert first_read.wait(5)
            second = pool.submit(submit, False)
            assert second_started.wait(5)
            # SQLite has no row locks: the transaction must reserve the writer
            # before reading, otherwise both bids can miss the other captain.
            assert not second_read.wait(0.2)
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
    view = call("GET", f"/matches/{auction_game}/auction")
    assert view["revision"] == auction["revision"] + 2
    assert len(view["lots"]) == 1
    assert view["lots"][0]["winner"] == "white"
    assert view["lots"][0]["white_bid"] == 10
    assert view["lots"][0]["black_bid"] == 0
    assert view["budgets"] == {"white": 90, "black": 100}


def test_same_player_cannot_captain_both_teams(env, call, auction_game):
    mid = auction_game
    before = call("GET", f"/matches/{mid}")
    response = call(
        "POST",
        f"/matches/{mid}/auction",
        dict(
            version=before["version"],
            white_captain=env[4]["admin"],
            black_captain=env[4]["admin"],
        ),
        expected=400,
    )
    assert "двух разных" in response["detail"]
    assert call("GET", f"/matches/{mid}") == before
    assert call("GET", f"/matches/{mid}/auction") is None
    assert call("GET", f"/matches/{mid}/auctions/history") == []
    with env[1]() as db:
        assert not list(db.scalars(select(Publication)))
    assert start(call, env, mid)["captains"] == {
        "white": env[4]["admin"],
        "black": env[4]["player"],
    }


def test_start_mentions_both_captains_once_and_escapes_names(env, call, auction_game):
    cfg, factory, _, _, ids = env
    cfg.publication_chat_id = "-1005678"
    with factory() as db, db.begin():
        db.get(Player, ids["admin"]).alias = 'Капитан <⚽> & "Белый"'
    before = call("GET", f"/matches/{auction_game}")
    auction = start(call, env, auction_game)
    call(
        "POST",
        f"/matches/{auction_game}/auction",
        dict(version=before["version"], white_captain=ids["admin"], black_captain=ids["player"]),
        expected=409,
    )
    with factory() as db:
        notice = db.scalar(select(Publication).where(Publication.kind == "auction_start"))
        assert notice.version == auction["id"] and notice.chat_id == cfg.publication_chat_id
        assert 'href="tg://user?id=101"' in notice.text and 'href="tg://user?id=102"' in notice.text
        assert "Капитан &lt;⚽&gt; &amp; &quot;Белый&quot;" in notice.text
        assert "Аукцион" in notice.text and "начат!" in notice.text
        assert "white_bid" not in notice.text and "black_bid" not in notice.text
        assert len(list(db.scalars(select(Publication)))) == 1
    control(call, auction_game, auction, "cancel")
    restarted = start(call, env, auction_game)
    with factory() as db:
        assert sorted(
            db.scalars(select(Publication.version).where(Publication.kind == "auction_start"))
        ) == [auction["id"], restarted["id"]]


def test_secret_bids_reveal_only_after_resolution(env, call, auction_game):
    mid = auction_game
    a = start(call, env, mid)
    first = bid(call, mid, a, 30)
    assert first["current"]["own_bid"] == 30
    for role in ["player", "observer"]:
        other = call("GET", f"/matches/{mid}/auction", role=role)
        assert other["current"]["own_bid"] is None
        assert other["lots"] == []
        assert "white_bid" not in other["current"]
    audits = call("GET", f"/matches/{mid}/history")["audit"]
    assert all("white_bid" not in row["data"] for row in audits)
    assert bid(call, mid, a, 30)["revision"] == first["revision"]
    bid(call, mid, a, 31, expected=409)
    bid(call, mid, a, 40, role="observer", expected=403)
    second = bid(call, mid, a, 29, role="player")
    assert second["budgets"] == {"white": 70, "black": 100}
    assert second["lots"][0]["white_bid"] == 30
    assert second["lots"][0]["black_bid"] == 29
    assert bid(call, mid, a, 30)["budgets"] == second["budgets"]
    bid(call, mid, a, 1, expected=409)
    assert call("GET", f"/matches/{mid}/auction", role="observer")["lots"] == second["lots"]


def test_auction_notifications_can_be_disabled_without_disabling_bids(env, call, auction_game):
    with env[1]() as db, db.begin():
        db.get(GameTemplate, 1).extended_auction_enabled = False
    auction = start(call, env, auction_game)
    bid(call, auction_game, auction, 20)
    result = bid(call, auction_game, auction, 10, "player")
    assert result["budgets"] == {"white": 80, "black": 100}
    with env[1]() as db:
        assert not list(db.scalars(select(Publication)))


def test_prices_and_chat_results_are_revealed_once_after_both_bids(env, call, auction_game):
    cfg, factory, _, _, _ = env
    cfg.publication_chat_id = "-1005678"
    mid = auction_game
    auction = start(call, env, mid)
    player = auction["current"]["player"]
    bid(call, mid, auction, 17)
    with factory() as db:
        assert not list(db.scalars(select(Publication).where(Publication.kind == "auction_lot")))
    resolved = bid(call, mid, auction, 12, "player")
    assert resolved["prices"] == {str(player["registration_id"]): 17}
    for role, amount in (("admin", 17), ("player", 12)):
        bid(call, mid, auction, amount, role)
    with factory() as db:
        messages = list(db.scalars(select(Publication).where(Publication.kind == "auction_lot")))
        assert len(messages) == 1
        message = messages[0]
        assert message.chat_id == "-1005678" and message.status == "pending"
        assert player["alias"] in message.text
        assert "Белые: 17" in message.text and "Чёрные: 12" in message.text
        assert "Белые получают игрока за 17 баллов" in message.text
        assert "Осталось баллов: ⚪ Белые — 83 · ⚫ Чёрные — 100" in message.text
    control(call, mid, resolved, "cancel")
    restarted = start(call, env, mid)
    bid(call, mid, restarted, 1)
    bid(call, mid, restarted, 0, "player")
    with factory() as db:
        messages = list(
            db.scalars(
                select(Publication)
                .where(Publication.kind == "auction_lot")
                .order_by(Publication.version)
            )
        )
        assert [message.version for message in messages] == [1, 2]


def test_positive_tie_has_no_price_team_or_charge_and_announces_next_round(env, call, auction_game):
    mid = auction_game
    auction = start(call, env, mid)
    player = auction["current"]["player"]
    bid(call, mid, auction, 15)
    resolved = bid(call, mid, auction, 15, "player")
    assert resolved["budgets"] == {"white": 100, "black": 100}
    assert str(player["registration_id"]) not in resolved["assignments"]
    assert resolved["prices"] == {}
    with env[1]() as db:
        message = db.scalar(select(Publication).where(Publication.kind == "auction_lot"))
        assert "Белые: 15" in message.text and "Чёрные: 15" in message.text
        assert (
            "переходит на круг 2" in message.text and "Команда пока не определена" in message.text
        )


async def test_auction_result_is_delivered_once_by_existing_worker(env, call, auction_game):
    from types import SimpleNamespace

    from fczhk.worker import deliver_one, mark_stale

    cfg, factory, _, _, _ = env
    cfg.publication_chat_id = "-1005678"
    cfg.bot_username = "test_club_bot"
    auction = start(call, env, auction_game)
    alias = auction["current"]["player"]["alias"]
    bid(call, auction_game, auction, 9)
    bid(call, auction_game, auction, 4, "player")

    class Bot:
        def __init__(self):
            self.sent = []
            self.edited = []

        async def send_message(self, chat, text, **kwargs):
            self.sent.append((chat, text, kwargs))
            return SimpleNamespace(message_id=42)

        async def edit_message_text(self, **kwargs):
            self.edited.append(kwargs)

    bot = Bot()
    assert await deliver_one(cfg, factory, bot)
    assert await deliver_one(cfg, factory, bot)
    assert not await deliver_one(cfg, factory, bot)
    assert len(bot.sent) == 2 and all(row[0] == cfg.publication_chat_id for row in bot.sent)
    assert bot.sent[0][2]["parse_mode"] == "HTML"
    assert "tg://user?id=101" in bot.sent[0][1] and "tg://user?id=102" in bot.sent[0][1]
    assert alias in bot.sent[1][1] and "Белые получают игрока за 9 баллов" in bot.sent[1][1]
    assert bot.sent[1][2]["parse_mode"] is None
    with factory() as db:
        message = db.scalar(select(Publication).where(Publication.kind == "auction_lot"))
        assert message.status == "sent" and message.message_ids == [42]
    with factory() as db, db.begin():
        db.scalar(select(Publication).where(Publication.kind == "auction_start")).stale = True
    await mark_stale(cfg, factory, bot)
    assert len(bot.edited) == 1 and bot.edited[0]["parse_mode"] == "HTML"
    assert "tg://user?id=101" in bot.edited[0]["text"]


def test_ties_rounds_then_free_assignment_and_approval(env, call, auction_game):
    mid = auction_game
    a = start(call, env, mid)
    original_ids = set()
    for _ in range(4):
        original_ids.add(a["current"]["player"]["registration_id"])
        bid(call, mid, a, 0)
        a = bid(call, mid, a, 0, "player")
    assert a["current"]["round"] == 2
    assert a["current"]["player"]["registration_id"] in original_ids
    for _ in range(2):
        bid(call, mid, a, 1)
        a = bid(call, mid, a, 0, "player")
    assert a["status"] == "completed"
    assert a["budgets"] == {"white": 98, "black": 100}
    assert len(a["automatic"]) == 2
    assert sorted(a["prices"].values()) == [0, 0, 1, 1]
    with env[1]() as db:
        messages = list(db.scalars(select(Publication).where(Publication.kind == "auction_lot")))
        assert len(messages) == 8  # Four ties, two won lots and two automatic assignments.
        assert sum("0 баллов.\nБез торгов" in message.text for message in messages) == 2
    assert sorted(a["assignments"].values()) == ["black"] * 3 + ["white"] * 3
    m = call("GET", f"/matches/{mid}")
    assert m["team_ratings"]["method"] == "auction"
    assert all(r["team"] for r in m["registrations"])
    m = call("POST", f"/matches/{mid}/actions/approve", {"version": m["version"]})
    assert m["status"] == "approved"
    call("POST", f"/matches/{mid}/actions/publish", {"version": m["version"]})


def test_zero_budgets_manual_finish_preserves_winners_and_history(env, call, auction_game):
    mid = auction_game
    a = start(call, env, mid)
    bid(call, mid, a, 100)
    a = bid(call, mid, a, 0, "player")
    bid(call, mid, a, 0)
    a = bid(call, mid, a, 100, "player")
    assert a["budgets"] == {"white": 0, "black": 0}
    bid(call, mid, a, 1, expected=400)
    for _ in range(3):
        bid(call, mid, a, 0)
        a = bid(call, mid, a, 0, "player")
    prior = a["assignments"]
    a = control(call, mid, a, "manual")
    assert a["status"] == "manual"
    assert a["current"] is None
    m = call("GET", f"/matches/{mid}")
    assert {str(r["id"]): r["team"] for r in m["registrations"] if r["team"]} == prior
    assert sum(r["team"] is None for r in m["registrations"]) == 2
    assert len(call("GET", f"/matches/{mid}/auctions/history")) == 1
    assignments = {str(r["id"]): r["team"] for r in m["registrations"]}
    free = [rid for rid, team in assignments.items() if team is None]
    assignments.update(zip(free, ["white", "black"]))
    m = call("PUT", f"/matches/{mid}/teams", {"version": m["version"], "assignments": assignments})
    call("POST", f"/matches/{mid}/actions/approve", {"version": m["version"]})


def test_pause_cancel_restart_stale_controls_and_hidden_abandoned_bid(env, call, auction_game):
    mid = auction_game
    a = start(call, env, mid)
    a = bid(call, mid, a, 47)
    paused = control(call, mid, a, "pause")
    bid(call, mid, paused, 10, "player", expected=409)
    control(call, mid, a, "resume", expected=409)
    resumed = control(call, mid, paused, "resume")
    assert resumed["current"]["own_bid"] == 47
    control(call, mid, resumed, "cancel")
    history = call("GET", f"/matches/{mid}/auctions/history", role="observer")
    assert history[0]["lots"] == [] and history[0]["current"] is None
    fresh = start(call, env, mid)
    assert fresh["id"] != a["id"] and fresh["budgets"] == {"white": 100, "black": 100}
    bid(call, mid, a, 20, "player", expected=409)


def test_roster_change_invalidates_and_running_auction_blocks_other_modes(env, call, auction_game):
    mid = auction_game
    a = start(call, env, mid)
    m = call("GET", f"/matches/{mid}")
    call("POST", f"/matches/{mid}/actions/approve", {"version": m["version"]}, expected=409)
    assignments = {
        str(r["id"]): ("white" if i < 3 else "black") for i, r in enumerate(m["registrations"])
    }
    call(
        "PUT",
        f"/matches/{mid}/teams",
        {"version": m["version"], "assignments": assignments},
        expected=409,
    )
    rid = m["registrations"][-1]["id"]
    call("POST", f"/matches/{mid}/registrations/{rid}/remove", {"version": m["version"]})
    assert call("GET", f"/matches/{mid}/auction")["status"] == "invalidated"
    bid(call, mid, a, 0, expected=409)
    m = call("GET", f"/matches/{mid}")
    call(
        "POST",
        f"/matches/{mid}/auction",
        {
            "version": m["version"],
            "white_captain": env[4]["admin"],
            "black_captain": env[4]["player"],
        },
        expected=400,
    )
    fresh = start(call, env, mid, larger_team="black")
    assert fresh["limits"] == {"white": 2, "black": 3}


@pytest.mark.parametrize("amount", [-1, 101, 1.5, True, "3"])
def test_only_integer_bids_in_range(env, call, auction_game, amount):
    a = start(call, env, auction_game)
    bid(call, auction_game, a, amount, expected=422)


def test_persistence_and_non_captain_admin_cannot_read_bid(env, call, auction_game):
    mid = auction_game
    with env[1]() as db, db.begin():
        r = db.scalar(
            select(Registration).where(
                Registration.match_id == mid, Registration.player_id.not_in(env[4].values())
            )
        )
        p = db.get(Player, r.player_id)
        p.telegram_id = 707
        env[3]["captain"] = create_session(db, env[0], p)
        captain = p.id
    m = call("GET", f"/matches/{mid}")
    a = call(
        "POST",
        f"/matches/{mid}/auction",
        dict(version=m["version"], white_captain=captain, black_captain=env[4]["player"]),
        expected=201,
    )
    first = bid(call, mid, a, 73, "captain")
    hidden = call("GET", f"/matches/{mid}/auction")
    assert hidden["current"]["own_bid"] is None
    assert hidden["current"]["submitted"]["white"]
    with env[1]() as db:
        assert db.get(Auction, a["id"]).state["queue"]
        assert db.get(AuctionLot, a["current"]["id"]).white_bid == 73
    assert call("GET", f"/matches/{mid}/auction", role="captain")["current"] == first["current"]
