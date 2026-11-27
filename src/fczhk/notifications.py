"""Transactional notifications: delivery is always performed by the existing outbox worker."""

from datetime import timedelta
from math import ceil

from sqlalchemy import select

from .db import now
from .models import Audit, GameTemplate, Match, Player, Publication, Registration, SkippedGameDay
from .scheduling import MOSCOW, schedule_window

SCHEDULED_KINDS = ("opening_notice", "payment_notice")
RETIRED_POINT_KINDS = ("points_request", "points_decided")
ROSTER_REMINDERS = {"roster_notice_2": 2, "roster_notice_1": 1}
ROSTER_FULL_KINDS = ("roster_full", "roster_full_ch")
ROSTER_CLOSED_KINDS = ("roster_closed", "roster_close_ch")
ROSTER_KINDS = (*ROSTER_REMINDERS, *ROSTER_FULL_KINDS, "roster_reported", *ROSTER_CLOSED_KINDS)
ROSTER_CHANNEL_KINDS = (*ROSTER_REMINDERS, "roster_full_ch", "roster_close_ch")
AWAITING_PAYMENT_HEADING = "Состав набран, ожидание оплаты"
PREGAME_STATUSES = ("open", "finalized", "approved")
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


def next_collection(db, at=None, *, exclude_planned_id=None, include_disabled=False):
    """Public schedule only; no channel IDs, payment details or writes."""
    at = at or now()
    result = dict(server_now=at, opening_at=None, starts_at=None, location=None)
    template = db.get(GameTemplate, 1)
    if not template or (not template.enabled and not include_disabled):
        return result
    planned = db.scalar(
        select(Match)
        .where(
            Match.status == "draft",
            (
                Match.scheduled_opening_at.is_not(None)
                | Match.id.in_(select(Audit.match_id).where(Audit.action == "collection.closed"))
            ),
            Match.id != exclude_planned_id if exclude_planned_id is not None else True,
            Match.starts_at > at,
            Match.game_day.not_in(select(SkippedGameDay.game_day)),
        )
        .order_by(Match.starts_at, Match.id)
        .limit(1)
    )
    planned_schedule = (
        {
            **result,
            "opening_at": planned.scheduled_opening_at.astimezone(MOSCOW)
            if planned.scheduled_opening_at
            else None,
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
            if planned and planned.starts_at <= starts:
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


def queue_scheduled(db, kind, key, text, expires_at, *, chat_id, version, match_id=None):
    pub = db.scalar(select(Publication).where(Publication.dedupe_key == key))
    if pub and pub.status not in ("pending", "cancelled", "expired"):
        return
    if pub:
        if pub.message_ids:
            return
        if (
            pub.status == "pending"
            and pub.chat_id == chat_id
            and pub.expires_at == expires_at
            and (kind in ROSTER_KINDS or pub.version == version)
        ):
            return
    if pub is None:
        pub = Publication(kind=kind, dedupe_key=key)
        db.add(pub)
    pub.match_id, pub.version = match_id, version
    pub.chat_id, pub.text, pub.expires_at = chat_id, text, expires_at
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
                "opening_notice",
                f"opening:{opening.isoformat()}",
                f"Внимание, сбор откроется через {remaining} мин.\n"
                f"Открытие: {opening:%d.%m.%Y · %H:%M МСК}\n"
                f"Игра: {starts:%d.%m.%Y · %H:%M МСК}",
                opening,
                chat_id=template.announcements_chat_id,
                version=template.version,
            )
    if not template.payment_reminder_enabled:
        return
    # Reminders also work for existing manual games and do not change their schedule.
    for match in db.scalars(
        select(Match).where(
            Match.status.in_(PREGAME_STATUSES),
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
                "payment_notice",
                f"payment:{match.id}",
                f"Полевым игрокам нужно оплатить футбол.\nИгра: {starts:%d.%m.%Y · %H:%M МСК}",
                starts,
                chat_id=template.announcements_chat_id,
                version=template.version,
                match_id=match.id,
            )


def roster_recipient(kind, match, cfg, template, at):
    if match.status not in PREGAME_STATUSES or match.starts_at <= at:
        return "", None
    if kind not in ROSTER_CHANNEL_KINDS:
        return cfg.community_chat_id, match.starts_at
    chat = template.announcements_chat_id if template else ""
    if kind not in ROSTER_REMINDERS:
        return chat if chat != cfg.community_chat_id else "", match.starts_at
    due = match.starts_at - timedelta(days=ROSTER_REMINDERS[kind])
    deadline = due + timedelta(days=1)
    if due <= at < deadline:
        return chat, deadline
    return "", None


def counted(amount, forms):
    if 11 <= amount % 100 <= 14:
        return f"{amount} {forms[2]}"
    last = amount % 10
    return f"{amount} {forms[0 if last == 1 else 1 if 2 <= last <= 4 else 2]}"


def roster_players(db, match):
    groups = {"field": [], "keeper": []}
    rows = db.execute(
        select(Registration, Player)
        .join(Player, Player.id == Registration.player_id)
        .where(Registration.match_id == match.id, Registration.active.is_(True))
        .order_by(
            (Registration.forced | Registration.selected).desc(),
            Registration.registered_at,
            Registration.id,
        )
    )
    for registration, player in rows:
        groups[registration.position].append((registration, player.display_alias))
    return groups


def eligible_roster_notices(match, groups):
    if len(groups["field"]) < match.field_limit or len(groups["keeper"]) < match.keeper_limit:
        return tuple(ROSTER_REMINDERS)
    main_fields = groups["field"][: match.field_limit]
    if all(registration.paid for registration, _ in main_fields):
        return ROSTER_CLOSED_KINDS
    if all(registration.payment_reported for registration, _ in main_fields):
        return (*ROSTER_FULL_KINDS, "roster_reported")
    return ROSTER_FULL_KINDS


def payment_circles(reported, paid):
    return ("🟢" if reported else "🔴") + ("🟢" if paid else "🔴")


def roster_text(match, groups, kind):
    when = match.starts_at.astimezone(MOSCOW).strftime("%d.%m в %H:%M МСК")
    reminder = kind in ROSTER_REMINDERS
    if kind == "roster_reported":
        return (
            f"🟢 Все полевые отметили оплату игры {when}. "
            "@xohsap, проверьте переводы и подтвердите оплаты в Mini App."
        )
    if reminder:
        needs = []
        field_needed = max(0, match.field_limit - len(groups["field"]))
        keeper_needed = max(0, match.keeper_limit - len(groups["keeper"]))
        if field_needed:
            needs.append(
                counted(field_needed, ("полевой игрок", "полевых игрока", "полевых игроков"))
            )
        if keeper_needed:
            needs.append(counted(keeper_needed, ("вратарь", "вратаря", "вратарей")))
        lines = [f"⚽ На игру {when} ещё требуется {' и '.join(needs)}!"]
    elif kind in ROSTER_CLOSED_KINDS:
        lines = [f"✅ Набор на игру {when} окончен. Все оплаты подтверждены."]
    else:
        lines = [f"⚽ Состав на игру {when} набран!"]
    for position, label, limit in (
        ("field", "Полевые", match.field_limit),
        ("keeper", "Вратари", match.keeper_limit),
    ):
        group = groups[position] if reminder else groups[position][:limit]
        lines.extend(("", f"{label} ({len(group)}/{limit})"))
        if not group:
            lines.append("Пока никого.")
        for index, (registration, alias) in enumerate(group, 1):
            line = f"{index}. {alias}"
            if reminder and position == "field":
                line += f" {payment_circles(registration.payment_reported, registration.paid)}"
            lines.append(line)
    if reminder and groups["field"]:
        lines.extend(("", "Первый кружок — отметка игрока, второй — подтверждение администратора."))
    return "\n".join(lines)


def retire_roster_reminders(db, match_id, *, confirmed):
    heading = "Набор окончен" if confirmed else AWAITING_PAYMENT_HEADING
    needs_edit = Publication.stale.is_(False)
    if confirmed:
        needs_edit = needs_edit | (Publication.stale_heading == AWAITING_PAYMENT_HEADING)
    for publication in db.scalars(
        select(Publication)
        .where(
            Publication.match_id == match_id,
            Publication.kind.in_(ROSTER_REMINDERS),
            needs_edit,
            Publication.status != "sending",
        )
        .with_for_update(skip_locked=True)
    ):
        if publication.message_ids:
            # A multipart reminder may have reached the channel before a retry or failure.
            publication.status = "sent"
        elif publication.status != "demo":
            continue
        publication.stale = True
        publication.stale_heading = heading
        publication.stale_marked = False
        publication.error = None


def schedule_roster_notifications(db, template, cfg, at):
    if not (cfg.community_chat_id or template.announcements_chat_id):
        return
    for match in db.scalars(
        select(Match).where(Match.status.in_(PREGAME_STATUSES), Match.starts_at > at)
    ):
        groups = roster_players(db, match)
        kinds = eligible_roster_notices(match, groups)
        if not any(kind in ROSTER_REMINDERS for kind in kinds):
            retire_roster_reminders(db, match.id, confirmed=kinds == ROSTER_CLOSED_KINDS)
        for kind in kinds:
            chat, expires = roster_recipient(kind, match, cfg, template, at)
            if not chat:
                continue
            key = f"{kind}:{match.id}"
            if kind in ROSTER_REMINDERS:
                key += f":{match.game_day}"
            queue_scheduled(
                db, kind, key, "", expires, chat_id=chat, version=match.version, match_id=match.id
            )


def roster_delivery_text(db, publication, cfg, at):
    match = db.get(Match, publication.match_id)
    if not match:
        return None
    template = db.get(GameTemplate, 1) if publication.kind in ROSTER_CHANNEL_KINDS else None
    chat, expires = roster_recipient(publication.kind, match, cfg, template, at)
    if not chat or chat != publication.chat_id or expires != publication.expires_at:
        return None
    groups = roster_players(db, match)
    if publication.kind not in eligible_roster_notices(match, groups):
        return None
    return roster_text(match, groups, publication.kind)


def delivery_text(db, publication, cfg, at=None):
    if publication.kind in ROSTER_KINDS:
        text = roster_delivery_text(db, publication, cfg, at or now())
        return publication.text if text is not None and publication.message_ids else text
    return publication.text if delivery_allowed(db, publication, at) else None


def delivery_allowed(db, publication, at=None, *, cfg=None):
    if publication.kind in RETIRED_POINT_KINDS:
        return False
    at = at or now()
    if publication.expires_at and publication.expires_at <= at:
        return False
    if publication.kind == "lineup_share":
        template = db.get(GameTemplate, 1)
        return bool(template and template.extended_chat_id == publication.chat_id)
    if publication.kind in EXTENDED_TYPES:
        return extended_chat(db, publication.kind) == publication.chat_id
    if publication.kind in ROSTER_KINDS:
        return bool(cfg and roster_delivery_text(db, publication, cfg, at) is not None)
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
        and match.status in PREGAME_STATUSES
        and match.starts_at > at
    )
