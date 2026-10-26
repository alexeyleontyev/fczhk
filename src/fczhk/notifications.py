"""Transactional notifications: delivery is always performed by the existing outbox worker."""

from datetime import timedelta
from math import ceil

from sqlalchemy import select

from .db import now
from .models import GameTemplate, Match, Player, Publication, SkippedGameDay
from .scheduling import MOSCOW, schedule_window

SCHEDULED_KINDS = ("opening_notice", "payment_notice")
EXTENDED_TYPES = {
    "auction_start": "extended_auction_enabled",
    "auction_open": "extended_auction_enabled",
    "auction_lot": "extended_auction_enabled",
    "registration": "extended_registration_enabled",
    "withdrawal": "extended_cancellation_enabled",
}


def extended_chat(db, kind):
    template = db.get(GameTemplate, 1)
    return template.extended_chat_id if template and getattr(template, EXTENDED_TYPES[kind]) else ""


def registration_notice(db, match, player_id, action, position, actor=None):
    if match.status == "draft":
        return
    kind = "withdrawal" if action == "cancelled" else "registration"
    chat = extended_chat(db, kind)
    if not chat:
        return
    player = db.get(Player, player_id)
    label = "полевым" if position == "field" else "вратарём"
    if action == "cancelled":
        line = f"➖ {player.display_alias} отменил запись на игру."
        if actor is not None and actor != player_id:
            line = f"➖ Администратор отменил запись игрока {player.display_alias}."
    elif action == "changed":
        line = f"🔄 {player.display_alias} изменил амплуа: теперь записан {label}."
    elif actor is not None and actor != player_id:
        line = f"➕ Администратор добавил игрока {player.display_alias} {label}."
    else:
        line = f"➕ {player.display_alias} записался {label}."
    db.add(
        Publication(
            match_id=match.id,
            kind=kind,
            version=match.version,
            chat_id=chat,
            text=f"{line}\nИгра {match.starts_at.astimezone(MOSCOW):%d.%m.%Y · %H:%M МСК}",
        )
    )


def next_collection(db, at=None):
    """Public schedule only; no channel IDs, payment details or writes."""
    at = at or now()
    result = dict(server_now=at, opening_at=None, starts_at=None, location=None)
    template = db.get(GameTemplate, 1)
    if not template or not template.enabled:
        return result
    planned = db.scalar(
        select(Match)
        .where(
            Match.status == "draft",
            Match.scheduled_opening_at.is_not(None),
            Match.starts_at > at,
            Match.game_day.not_in(select(SkippedGameDay.game_day)),
        )
        .order_by(Match.scheduled_opening_at, Match.id)
        .limit(1)
    )
    planned_schedule = (
        {
            **result,
            "opening_at": planned.scheduled_opening_at.astimezone(MOSCOW),
            "starts_at": planned.starts_at.astimezone(MOSCOW),
            "location": planned.location,
        }
        if planned
        else result
    )
    opening, starts = schedule_window(template, at)
    end_day = (starts + timedelta(weeks=54)).date().isoformat()
    first_day = starts.date().isoformat()
    occupied = set(
        db.scalars(
            select(Match.game_day).where(Match.game_day >= first_day, Match.game_day <= end_day)
        )
    )
    skipped = set(
        db.scalars(
            select(SkippedGameDay.game_day).where(
                SkippedGameDay.game_day >= first_day, SkippedGameDay.game_day <= end_day
            )
        )
    )
    # Include an opening just reached until the worker has actually opened it.
    for _ in range(54):
        day = starts.date().isoformat()
        if day not in skipped and day not in occupied:
            if planned and planned.scheduled_opening_at <= opening:
                return planned_schedule
            return {
                **result,
                "opening_at": opening,
                "starts_at": starts,
                "location": template.location,
            }
        opening += timedelta(weeks=1)
        starts += timedelta(weeks=1)
    return planned_schedule


def queue_scheduled(db, template, kind, key, text, expires_at, match_id=None):
    pub = db.scalar(select(Publication).where(Publication.dedupe_key == key))
    if pub and pub.status not in ("pending", "cancelled", "expired"):
        return
    if pub and pub.status == "pending" and pub.version == template.version:
        return
    if pub is None:
        pub = Publication(kind=kind, dedupe_key=key)
        db.add(pub)
    pub.match_id, pub.version = match_id, template.version
    pub.chat_id, pub.text, pub.expires_at = template.announcements_chat_id, text, expires_at
    pub.status, pub.error, pub.stale, pub.attempts = "pending", None, False, 0
    pub.next_attempt_at = now()


def schedule_notifications(db, template, at):
    """Called while holding the same template lock as automatic game creation."""
    if not template.announcements_chat_id:
        return
    if template.enabled and template.announcement_enabled:
        upcoming = next_collection(db, at)
        opening, starts = upcoming["opening_at"], upcoming["starts_at"]
        if opening and opening - timedelta(minutes=template.announcement_minutes) <= at < opening:
            remaining = ceil((opening - at).total_seconds() / 60)
            queue_scheduled(
                db,
                template,
                "opening_notice",
                f"opening:{opening.isoformat()}",
                f"Внимание, сбор откроется через {remaining} мин.\n"
                f"Открытие: {opening:%d.%m.%Y · %H:%M МСК}\n"
                f"Игра: {starts:%d.%m.%Y · %H:%M МСК}",
                opening,
            )
    if not template.payment_reminder_enabled:
        return
    # Reminders also work for existing manual games and do not change their schedule.
    for match in db.scalars(
        select(Match).where(
            Match.status.in_(("open", "finalized", "approved")),
            Match.starts_at > at,
            Match.starts_at <= at + timedelta(weeks=1),
        )
    ):
        starts = match.starts_at.astimezone(MOSCOW)
        hour, minute = map(int, template.payment_reminder_time.split(":"))
        reminder = (
            starts - timedelta(days=(starts.weekday() - template.payment_reminder_weekday) % 7)
        ).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if reminder >= starts:
            reminder -= timedelta(weeks=1)
        if reminder <= at < starts:
            queue_scheduled(
                db,
                template,
                "payment_notice",
                f"payment:{match.id}",
                f"Внимание, нужно оплатить футбол!\nИгра: {starts:%d.%m.%Y · %H:%M МСК}",
                starts,
                match.id,
            )


def delivery_allowed(db, publication, at=None):
    at = at or now()
    if publication.expires_at and publication.expires_at <= at:
        return False
    if publication.kind == "lineup_share":
        template = db.get(GameTemplate, 1)
        return bool(template and template.extended_chat_id == publication.chat_id)
    if publication.kind in EXTENDED_TYPES:
        return extended_chat(db, publication.kind) == publication.chat_id
    if publication.kind not in SCHEDULED_KINDS:
        return True
    template = db.get(GameTemplate, 1)
    if (
        not template
        or template.announcements_chat_id != publication.chat_id
        or template.version != publication.version
    ):
        return False
    if publication.kind == "opening_notice":
        if not template.enabled or not template.announcement_enabled:
            return False
        upcoming = next_collection(db, at)
        return upcoming["opening_at"] == publication.expires_at
    match = db.get(Match, publication.match_id)
    return bool(
        template.payment_reminder_enabled
        and match
        and match.status in ("open", "finalized", "approved")
        and match.starts_at > at
    )
