import hashlib
import re
import secrets
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramMigrateToChat
from aiogram.utils.web_app import safe_parse_webapp_init_data
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import now
from .guest_keepers import SHARED_KEEPER_ALIASES
from .models import LoginSession, Player
from .services import DomainError, audit


async def check_member(cfg, telegram_id: int):
    if cfg.env in ("demo", "test"):
        return
    try:
        async with Bot(cfg.bot_token) as bot:
            try:
                member = await bot.get_chat_member(cfg.community_chat_id, telegram_id)
            except TelegramMigrateToChat as migration:
                member = await bot.get_chat_member(migration.migrate_to_chat_id, telegram_id)
        allowed = member.status in ("creator", "administrator", "member") or (
            member.status == "restricted" and getattr(member, "is_member", False)
        )
    except Exception as exc:
        raise DomainError(
            "Не удалось проверить участие в сообществе. Попробуйте позже.", 503
        ) from exc
    if not allowed:
        raise DomainError("Доступ только для участников нашего чата или канала", 403)


def parse_telegram(cfg, init_data: str):
    try:
        parsed = safe_parse_webapp_init_data(cfg.bot_token, init_data)
    except (ValueError, TypeError) as exc:
        raise DomainError("Неверные данные Telegram. Откройте приложение через бота.", 401) from exc
    age = (now() - parsed.auth_date).total_seconds()
    if not parsed.user or not -30 <= age <= cfg.auth_max_age_seconds:
        raise DomainError("Ссылка входа устарела. Откройте приложение заново.", 401)
    return parsed.user


def create_session(db, cfg, player: Player) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            player_id=player.id,
            expires_at=now() + timedelta(hours=cfg.session_hours),
        )
    )
    return token


_USERNAME_UNSET = object()


def player_for_telegram(db, telegram_id: int, name: str, username=_USERNAME_UNSET) -> Player:
    # Serialize first registration across concurrent bot / web requests on PostgreSQL.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": telegram_id})
    player = db.scalar(select(Player).where(Player.telegram_id == telegram_id))
    if not player:
        base = name[:60].strip() or "Игрок"
        for attempt in range(10):
            suffix = (
                ""
                if attempt == 0 and base not in SHARED_KEEPER_ALIASES
                else f" · {telegram_id}" + (f".{attempt}" if attempt > 1 else "")
            )
            alias = base[: 60 - len(suffix)] + suffix
            try:
                with db.begin_nested():
                    player = Player(telegram_id=telegram_id, alias=alias)
                    db.add(player)
                    db.flush()
                break
            except IntegrityError:
                if not db.scalar(select(Player.id).where(Player.alias == alias)):
                    raise
        else:
            raise DomainError("Не удалось выбрать свободное имя. Повторите вход.", 409)
        audit(db, player.id, "player.registered")
    # Omitted metadata (e.g. a manual prebinding) must not erase a known username.
    # An explicit None from a verified Telegram profile means it was removed.
    if username is not _USERNAME_UNSET:
        player.telegram_username = (
            username
            if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{1,32}", username)
            else None
        )
    return player


def is_owner(player: Player, cfg) -> bool:
    return bool(cfg.effective_owner_id and player.telegram_id == cfg.effective_owner_id)


def has_admin_access(player: Player, cfg) -> bool:
    if not player.telegram_id:
        return False
    if is_owner(player, cfg):
        return True
    if player.admin_access is not None:
        return player.admin_access
    return player.telegram_id in cfg.admins


def public_player(player: Player, cfg, own=False):
    data = dict(id=player.id, alias=player.display_alias, guest=player.telegram_id is None)
    if player.shared_keeper:
        data["shared_keeper"] = True
    if own:
        data.update(telegram_profile(player))
        data["is_admin"] = has_admin_access(player, cfg)
        data["is_owner"] = is_owner(player, cfg)
    return data


def telegram_profile(player: Player):
    return dict(telegram_id=player.telegram_id, telegram_username=player.telegram_username)
