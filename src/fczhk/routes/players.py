from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import game_ratings as gr
from .. import profile_claims
from .. import ratings as rt
from .. import results as res
from .. import schemas as S
from .. import services as svc
from ..auth import has_admin_access, public_player
from ..guest_keepers import GUEST_KEEPER_ALIAS, LEGACY_KEEPER_ALIASES, SHARED_KEEPER_ALIASES
from ..models import (
    Match,
    Player,
    ProfileClaim,
)


def router(ctx):
    app = APIRouter()
    cfg = ctx.cfg
    db_dep = ctx.db_dep
    current = ctx.current
    admin = ctx.admin

    @app.get("/api/me")
    def me(p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")):
        return {
            **public_player(p, cfg, own=True),
            "ratings": rt.public_averages(db, [p.id], has_admin_access(p, cfg))[p.id],
        }

    @app.patch("/api/me")
    def update_me(
        body: S.Name, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        if body.alias in SHARED_KEEPER_ALIASES:
            raise svc.DomainError("Это имя общей карточки вратаря. Выберите другое.", 409)
        if db.scalar(select(Player.id).where(Player.alias == body.alias, Player.id != p.id)):
            raise svc.DomainError("Это имя игрока уже используется. Выберите другое.", 409)
        p = db.get(Player, p.id)
        old = p.alias
        p.alias = body.alias
        svc.audit(db, p.id, "player.renamed", old=old, new=p.alias)
        return public_player(p, cfg, own=True)

    @app.get("/api/players")
    def players(p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")):
        people = list(
            db.scalars(select(Player).where(Player.merged_into.is_(None)).order_by(Player.alias))
        )
        keepers = [x for x in people if x.shared_keeper]
        if keepers:
            representative = min(keepers, key=lambda x: x.id)
            people = [x for x in people if not x.shared_keeper or x.id == representative.id]
            people.sort(key=lambda x: x.display_alias)
        averages = rt.public_averages(db, [x.id for x in people], has_admin_access(p, cfg))
        own = rt.catalog_own_ratings(db, p.id, [x.id for x in people])
        return [
            {**public_player(x, cfg), "ratings": averages[x.id], "my_ratings": own[x.id]}
            for x in people
        ]

    @app.get("/api/game-ratings")
    def game_ratings(
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
        season: str | None = Query(
            default=None,
            min_length=1,
            max_length=40,
            deprecated=True,
            description="Параметр совместимости: рейтинг всегда учитывает все сезоны",
        ),
    ):
        return gr.leaderboard(db)

    @app.get("/api/seasons")
    def seasons(p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")):
        query = select(Match.season).distinct().order_by(Match.season.desc())
        if not has_admin_access(p, cfg):
            query = query.where(Match.status != "draft")
        return list(db.scalars(query))

    @app.get("/api/leaderboards")
    def leaderboards(
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
        season: str | None = Query(default=None, min_length=1, max_length=40),
    ):
        return {
            "results": res.leaderboards(db, season=season),
            "community": rt.community_leaderboards(db),
        }

    @app.get("/api/players/{player_id}/ratings/{position}")
    def rating_detail(
        player_id: int,
        position: S.Position,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        return rt.review_data(db, p.id, player_id, position, has_admin_access(p, cfg))

    @app.get("/api/players/{player_id}/reviews")
    def player_reviews(
        player_id: int,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        return {
            position: [
                {key: row[key] for key in ("author_id", "author", "attack", "defense", "at")}
                for row in rt.review_data(db, p.id, player_id, position, True)["reviews"]
                if row["author_id"] != player_id
            ]
            for position in ("field", "keeper")
        }

    @app.get("/api/players/{player_id}/stats")
    def statistics(
        player_id: int,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
        season: str | None = Query(default=None, min_length=1, max_length=40),
    ):
        return res.player_stats(db, player_id, season=season)

    @app.put("/api/players/{player_id}/ratings")
    def rate(
        player_id: int,
        body: S.RatingEdit,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        rt.save_rating(db, p.id, player_id, body)
        return rt.review_data(db, p.id, player_id, body.position, has_admin_access(p, cfg))

    @app.post("/api/players/guests", status_code=201)
    def guest(
        body: S.Name, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        if body.alias in LEGACY_KEEPER_ALIASES:
            raise svc.DomainError(f"Используйте общую карточку «{GUEST_KEEPER_ALIAS}».")
        if body.alias == GUEST_KEEPER_ALIAS and db.scalar(
            select(Player.id).where(
                Player.alias.in_(SHARED_KEEPER_ALIASES),
                Player.telegram_id.is_(None),
                Player.merged_into.is_(None),
            )
        ):
            raise svc.DomainError("Общая карточка вратаря уже есть в каталоге.", 409)
        if db.scalar(select(Player.id).where(Player.alias == body.alias)):
            raise svc.DomainError("Это имя игрока уже используется. Выберите другое.", 409)
        new = Player(alias=body.alias)
        db.add(new)
        db.flush()
        svc.audit(db, p.id, "guest.created", player_id=new.id)
        return public_player(new, cfg)

    @app.post("/api/players/{guest_id}/link")
    def link(
        guest_id: int,
        body: S.LinkGuest,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        svc.merge_guest(db, p.id, guest_id, body.target_id)
        return {"ok": True}

    @app.get("/api/me/profile-claim")
    def own_claim(p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")):
        return profile_claims.serialize(db, db.get(ProfileClaim, p.id))

    @app.post("/api/me/profile-claim")
    def claim(
        body: S.ClaimProfile,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        return profile_claims.request_claim(db, p.id, body.guest_id)

    @app.get("/api/profile-claims")
    def pending_claims(p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")):
        return [
            profile_claims.serialize(db, claim)
            for claim in db.scalars(select(ProfileClaim).where(ProfileClaim.status == "pending"))
        ]

    @app.post("/api/profile-claims/{player_id}/resolve")
    def resolve_claim(
        player_id: int,
        body: S.ResolveClaim,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        return profile_claims.resolve(db, p.id, player_id, body.guest_id, body.accept)

    return app
