from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import archive as arc
from .. import post_images
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
    MatchResult,
    Player,
    Publication,
    Registration,
    ResultParticipant,
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

    @app.get("/api/matches/last-completed")
    def last_completed(
        p: Player = Depends(current), db: Session = Depends(db_dep, scope="function")
    ):
        match = db.scalar(
            select(Match)
            .join(MatchResult, MatchResult.match_id == Match.id)
            .where(
                Match.status == "completed",
                MatchResult.completed.is_(True),
                Match.starts_at <= now(),
            )
            .order_by(Match.starts_at.desc(), Match.id.desc())
            .limit(1)
        )
        if match is None:
            return None
        people, canonical = res.identities(db)
        keeper = min(
            (p.id for p in people.values() if p.shared_keeper and not p.merged_into), default=None
        )
        ids = {
            canonical[pid]
            for pid in db.scalars(
                select(ResultParticipant.player_id).where(ResultParticipant.match_id == match.id)
            )
        }
        ids = {keeper if people[pid].shared_keeper and keeper is not None else pid for pid in ids}
        return {**summaries(db, [match])[0], "participant_ids": sorted(ids)}

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

    @app.put("/api/matches/{match_id}/collection-image")
    async def upload_collection_image(
        match_id: int, request: Request, version: int = Query(ge=1), p: Player = Depends(admin)
    ):
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > post_images.MAX_BYTES):
            raise svc.DomainError("Выберите JPG или PNG размером до 10 МБ", 413)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > post_images.MAX_BYTES:
                raise svc.DomainError("Выберите JPG или PNG размером до 10 МБ", 413)
            data.extend(chunk)
        content = bytes(data)
        info = await run_in_threadpool(post_images.validate, content)
        image = await run_in_threadpool(
            post_images.save, ctx.factory, p.id, match_id, version, content, info
        )
        return {"image": image}

    @app.get("/api/matches/{match_id}/collection-image")
    def collection_image(
        match_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        content, mime = post_images.content(db, match_id)
        return Response(content=content, media_type=mime)

    @app.delete("/api/matches/{match_id}/collection-image")
    def remove_collection_image(
        match_id: int,
        body: S.Version,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        post_images.remove(db, p.id, match_id, body.version)
        return {"ok": True}

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
        if (
            m.status == "draft"
            and m.scheduled_opening_at
            and body.starts_at <= m.scheduled_opening_at
        ):
            raise svc.DomainError("Начало игры должно быть позже запланированного открытия сбора")
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

    @app.put("/api/matches/{match_id}/archive-details")
    def archive_details(
        match_id: int,
        body: S.ArchiveDetailsEdit,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
        m = svc.get_match(db, match_id, body.version, lock=True)
        arc.edit_details(db, p.id, m, body)
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

    @app.get("/api/matches/{match_id}/cancellation")
    def cancellation_options(
        match_id: int, p: Player = Depends(admin), db: Session = Depends(db_dep, scope="function")
    ):
        match = svc.get_match(db, match_id)
        return svc.cancellation_options(db, match)

    @app.post("/api/matches/{match_id}/cancel")
    def cancel_match(
        match_id: int,
        body: S.Cancellation,
        p: Player = Depends(admin),
        db: Session = Depends(db_dep, scope="function"),
    ):
        db.scalar(select(GameTemplate).where(GameTemplate.id == 1).with_for_update())
        match = svc.get_match(db, match_id, body.version, lock=True)
        svc.cancel_match(
            db,
            p.id,
            match,
            body.reason,
            cfg,
            advance_schedule=body.advance_schedule,
            expected_next_starts_at=body.expected_next_starts_at,
        )
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

    @app.put("/api/matches/{match_id}/payment-report")
    def payment_report(
        match_id: int,
        body: S.PaymentReport,
        p: Player = Depends(current),
        db: Session = Depends(db_dep, scope="function"),
    ):
        m = svc.get_match(db, match_id, lock=True)
        r = db.scalar(
            select(Registration).where(
                Registration.match_id == m.id,
                Registration.player_id == p.id,
            )
        )
        if r is None:
            raise svc.DomainError("Сначала запишитесь на игру", 409)
        svc.report_payment(db, p.id, m, r, body.reported)
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
        r = svc.registration(db, match_id, reg_id)
        svc.confirm_payment(db, p.id, m, r, body.paid)
        if body.reported is not None and r.payment_reported != body.reported:
            r.payment_reported = body.reported
            r.payment_reported_at = now() if body.reported else None
            m.version += 1
            svc.audit(
                db, p.id, "payment.reported", m.id, registration_id=r.id, reported=body.reported
            )
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
        svc.get_match(db, match_id)
        people = {person.id: person for person in db.scalars(select(Player))}

        def actor_name(actor_id):
            person = people.get(actor_id)
            if person and person.merged_into:
                person = people.get(person.merged_into)
            return person.display_alias if person else None

        return dict(
            audit=[
                dict(
                    id=a.id,
                    actor_id=a.actor_id,
                    actor=actor_name(a.actor_id),
                    action=a.action,
                    data=a.data,
                    at=a.created_at,
                )
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
