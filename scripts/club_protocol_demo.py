"""Local, isolated, fully functional FCZhK design preview."""

import argparse
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from fczhk import auctions, results, schemas, services
from fczhk.api import create_app
from fczhk.cli import demo_settings, seed_demo
from fczhk.db import database, now
from fczhk.models import (
    GameTemplate,
    Match,
    Player,
    Prediction,
    ProfileClaim,
    Rating,
    RatingHistory,
    Registration,
)

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend/dist"


def populate(cfg):
    seed_demo(cfg)
    engine, sessions = database(cfg.database_url)
    with sessions.begin() as db:
        # Startup is idempotent, including after someone changes a sample game's status.
        first = db.get(Match, 1)
        if db.get(Match, 2):
            return
        players = list(db.scalars(select(Player).order_by(Player.id)))
        owner = players[0].id
        # Start the poster with room for either position in the synthetic season.
        for pos, limit in (("field", 14), ("keeper", 1)):
            queue = db.scalars(
                select(Registration)
                .where(Registration.match_id == first.id, Registration.position == pos)
                .order_by(Registration.registered_at, Registration.id)
            ).all()
            for reg in queue[limit:]:
                reg.active = False
        first.starts_at = first.starts_at + timedelta(hours=1)
        db.get(GameTemplate, 1).start_time = "21:00"
        for n, person in enumerate(players[:20]):
            for author in (players[2], players[3], players[4]):
                if author.id == person.id:
                    continue
                pos = "field" if n < 18 else "keeper"
                attack = 31 + (n + author.id) % 17 if pos == "field" else None
                defense = 26 + (n * 5 + author.id) % 22
                vote = Rating(
                    author_id=author.id,
                    player_id=person.id,
                    position=pos,
                    attack=attack,
                    defense=defense,
                    revision=2,
                    updated_at=now() - timedelta(days=2),
                )
                db.add(vote)
                db.flush()
                for rev, days in ((1, 12), (2, 2)):
                    db.add(
                        RatingHistory(
                            rating_id=vote.id,
                            revision=rev,
                            attack=attack,
                            defense=defense - (2 - rev) * 3,
                            created_at=now() - timedelta(days=days),
                        )
                    )
        guest = Player(alias="Гость Саша")
        db.add(guest)
        db.flush()
        db.add(ProfileClaim(player_id=players[5].id, guest_id=guest.id))
        db.flush()
        for weeks, state in [(x, "completed") for x in range(-8, 0)] + [
            (1, "finalized"),
            (2, "auction"),
            (3, "approved"),
            (-9, "result"),
            (4, "draft"),
        ]:
            dt = first.starts_at + timedelta(weeks=weeks)
            match = Match(
                game_day=dt.date().isoformat(),
                starts_at=dt,
                season=str(dt.year),
                status="finalized",
                location="Манеж «Север»",
                cost=80000,
                payment_details="Демонстрационный сбор",
                description="Белая и чёрная футболки.",
            )
            db.add(match)
            db.flush()
            if state == "draft":
                match.status = "draft"
                match.scheduled_opening_at = dt - timedelta(days=3)
                continue
            field = players[:16]
            if weeks < 0 and weeks % 2:
                field = [*field[:15], players[16]]
            group = [*field, *players[18:20]]
            actual = []
            for i, person in enumerate(group):
                side = "white" if (i + weeks) % 2 == 0 else "black"
                pos = "keeper" if i >= 16 else "field"
                db.add(
                    Registration(
                        match_id=match.id,
                        player_id=person.id,
                        position=pos,
                        team=side,
                        paid=True,
                        selected=True,
                    )
                )
                actual.append(dict(player_id=person.id, team=side, position=pos))
            db.flush()
            if state == "auction":
                auctions.start(
                    db,
                    owner,
                    match,
                    schemas.AuctionStart(
                        version=match.version,
                        white_captain=players[0].id,
                        black_captain=players[1].id,
                    ),
                    cfg,
                )
            elif state != "finalized":
                services.approve(db, owner, match, cfg)
            if state == "completed":
                goals = []
                for side, n in (("white", 3 + abs(weeks) % 3), ("black", 2 + abs(weeks) % 4)):
                    side_ids = [
                        r["player_id"]
                        for r in actual
                        if r["team"] == side and r["position"] == "field"
                    ]
                    for j in range(n):
                        goals.append(
                            dict(
                                id=uuid4(),
                                team=side,
                                author_id=side_ids[(j - weeks) % 8],
                                assist_id=side_ids[(j - weeks + 1) % 8],
                            )
                        )
                for j, person in enumerate(players[:5]):
                    db.add(
                        Prediction(
                            match_id=match.id,
                            player_id=person.id,
                            approved_version=match.approved_version,
                            white_score=3 + j % 3,
                            black_score=2 + (j + weeks) % 4,
                            updated_at=dt - timedelta(hours=1),
                        )
                    )
                results.save_result(
                    db,
                    owner,
                    match,
                    schemas.ResultEdit(
                        version=match.version, completed=True, participants=actual, goals=goals
                    ),
                    cfg,
                )
    engine.dispose()


def serve(directory, port, examples):
    cfg = demo_settings()
    cfg.database_url = f"sqlite:///{directory / 'demo.db'}"
    cfg.public_url = f"http://127.0.0.1:{port}"
    cfg.bot_token = cfg.community_chat_id = cfg.publication_chat_id = ""
    if examples:
        populate(cfg)
    else:
        seed_demo(cfg)
    api = create_app(cfg)
    static = StaticFiles(directory=DIST, html=True)

    async def preview(scope, receive, send):
        target = api if scope["type"] != "http" or scope["path"].startswith("/api/") else static
        await target(scope, receive, send)

    uvicorn.run(
        preview,
        host="127.0.0.1",
        port=port,
        proxy_headers=False,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--qa", action="store_true")
    args.add_argument("--port", type=int, default=8747)
    args.add_argument("--data-directory", type=Path, default=ROOT / ".local/club-protocol-demo")
    options = args.parse_args()
    if options.qa:
        with TemporaryDirectory(prefix="fczhk-protocol-qa-") as tmp:
            serve(Path(tmp), options.port, False)
    else:
        options.data_directory.mkdir(parents=True, exist_ok=True)
        serve(options.data_directory.resolve(), options.port, True)
