from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import predictions as pred
from .. import results as res
from .. import schemas as S
from .. import services as svc
from ..auth import has_admin_access
from ..db import now
from ..match_list import summaries
from ..models import (
    Audit,
    GameTemplate,
    Match,
    Player,
    Publication,
    Registration,
    SkippedGameDay,
    TeamRatingSnapshot,
    TeamSnapshot,
)


def router(ctx):
    app = APIRouter()
    cfg = ctx.cfg
    db_dep = ctx.db_dep
    current = ctx.current
    admin = ctx.admin

    @app.get("/api/matches")
    def matches(
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        season: str | None = Query(default=None, min_length=1, max_length=40),
    ):
        query = (
            select(Match)
            .order_by(Match.starts_at.desc(), Match.id.desc())
            .offset(offset)
            .limit(limit)
        )
        if not has_admin_access(p, cfg):
            query = query.where(Match.status != "draft")
        if season is not None:
            query = query.where(Match.season == season)
        return summaries(db, list(db.scalars(query)))

    @app.get("/api/matches/current")
    def current_match(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        query = select(Match).where(Match.status != "cancelled")
        if not has_admin_access(p, cfg):
            query = query.where(Match.status != "draft")
        match = db.scalar(
            query.where(Match.starts_at > now()).order_by(Match.starts_at, Match.id).limit(1)
        )
        if match is None:
            match = db.scalar(query.order_by(Match.starts_at.desc(), Match.id.desc()).limit(1))
        return svc.match_data(db, match) if match else None

    @app.get("/api/matches/{match_id}")
    def detail(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id)
        if m.status == "draft" and not has_admin_access(p, cfg):
            raise svc.DomainError("Игра не найдена", 404)
        return svc.match_data(db, m)

    @app.post("/api/matches", status_code=201)
    def create(
        body: S.GameFields,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        return svc.match_data(db, svc.create_match(db, p.id, body.model_dump()))

    @app.put("/api/matches/{match_id}")
    def edit(
        match_id: int,
        body: S.GameEdit,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
        m = svc.get_match(db, match_id, body.version, lock=True)
        if m.status == "cancelled":
            raise svc.DomainError("Игра отменена", 409)
        day = body.starts_at.astimezone(svc.MOSCOW).date().isoformat()
        if db.get(SkippedGameDay, day):
            raise svc.DomainError(
                "Эта неделя пропущена. Сначала снимите пропуск в расписании.", 409
            )
        before = {key: str(getattr(m, key)) for key in S.GameFields.model_fields}
        pred.validate_reschedule(db, m, body.starts_at)
        if db.get(res.MatchResult, m.id) and body.starts_at != m.starts_at:
            raise svc.DomainError("Время матча с результатом изменять нельзя")
        for key, value in body.model_dump(exclude={"version", "season"}).items():
            setattr(m, key, value)
        if body.season is not None:
            m.season = body.season
        m.game_day = m.starts_at.astimezone(svc.MOSCOW).date().isoformat()
        m.version += 1
        # Editing logistics invalidates published text; preserve manual assignments.
        for pub in db.scalars(
            select(Publication).where(Publication.match_id == m.id, Publication.stale.is_(False))
        ):
            pub.stale = True
            if pub.status == "pending":
                pub.status = "cancelled"
        if m.status == "open":
            svc.enqueue(db, m, "collection", cfg.publication_chat_id)
        svc.audit(
            db,
            p.id,
            "match.edited",
            m.id,
            old=before,
            new={key: str(getattr(m, key)) for key in S.GameFields.model_fields},
        )
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/actions/{action}")
    def action(
        match_id: int,
        action: str,
        body: S.Version,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        if action == "open":
            svc.open_match(db, p.id, m, cfg)
        elif action == "finalize":
            svc.finalize(db, p.id, m)
        elif action == "approve":
            svc.approve(db, p.id, m, cfg)
        elif action == "publish":
            svc.publish_teams(db, p.id, m, cfg)
        else:
            raise svc.DomainError("Неизвестное действие", 404)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/cancel")
    def cancel_match(
        match_id: int,
        body: S.Cancellation,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        match = svc.get_match(db, match_id, body.version, lock=True)
        svc.cancel_match(db, p.id, match, body.reason, cfg)
        db.flush()
        return svc.match_data(db, match)

    @app.post("/api/matches/{match_id}/join")
    def join(
        match_id: int,
        body: S.Join,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        svc.register(db, p.id, m, body.position)
        db.flush()
        return svc.match_data(db, m)

    @app.delete("/api/matches/{match_id}/join")
    def leave(
        match_id: int, p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        m = svc.get_match(db, match_id, lock=True)
        r = db.scalar(
            select(Registration).where(
                Registration.match_id == m.id, Registration.player_id == p.id
            )
        )
        if r:
            svc.cancel(db, p.id, m, r)
        db.flush()
        return svc.match_data(db, m)

    @app.put("/api/matches/{match_id}/registrations/{reg_id}/payment")
    def payment(
        match_id: int,
        reg_id: int,
        body: S.Payment,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.confirm_payment(db, p.id, m, svc.registration(db, match_id, reg_id), body.paid)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/registrations/{reg_id}/remove")
    def remove(
        match_id: int,
        reg_id: int,
        body: S.Version,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.cancel(db, p.id, m, svc.registration(db, match_id, reg_id), admin=True)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/participants")
    def include(
        match_id: int,
        body: S.Include,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.add_participant(db, p.id, m, body.player_id, body.position, body.replace_id)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/promote")
    def promote(
        match_id: int,
        body: S.Promote,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.promote(db, p.id, m, body.position)
        db.flush()
        return svc.match_data(db, m)

    @app.put("/api/matches/{match_id}/teams")
    def teams(
        match_id: int,
        body: S.Teams,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.save_teams(db, p.id, m, body.assignments, reset=body.reset)
        db.flush()
        return svc.match_data(db, m)

    @app.post("/api/matches/{match_id}/teams/swap-colors")
    def swap_team_colors(
        match_id: int,
        body: S.Version,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, body.version, lock=True)
        svc.swap_team_colors(db, p.id, m)
        db.flush()
        return svc.match_data(db, m)

    @app.get("/api/matches/{match_id}/history")
    def history(
        match_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        return dict(
            audit=[
                dict(id=a.id, actor_id=a.actor_id, action=a.action, data=a.data, at=a.created_at)
                for a in db.scalars(
                    select(Audit)
                    .where(Audit.match_id == match_id)
                    .order_by(Audit.id.desc())
                    .limit(200)
                )
            ],
            teams=[
                dict(
                    version=t.version,
                    teams=t.teams,
                    at=t.created_at,
                    ratings=s.data if (s := db.get(TeamRatingSnapshot, t.id)) else None,
                )
                for t in db.scalars(
                    select(TeamSnapshot)
                    .where(TeamSnapshot.match_id == match_id)
                    .order_by(TeamSnapshot.id.desc())
                )
            ],
        )

    return app
