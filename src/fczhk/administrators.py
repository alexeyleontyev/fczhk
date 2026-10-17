"""Only the configured owner can change application administrators."""

from sqlalchemy import select

from .auth import has_admin_access, is_owner
from .models import Player
from .services import DomainError, audit


def describe(player, cfg):
    return {
        "id": player.id,
        "alias": player.alias,
        "telegram_id": player.telegram_id,
        "role": "owner"
        if is_owner(player, cfg)
        else "admin"
        if has_admin_access(player, cfg)
        else "player",
        "revision": player.admin_access_revision,
    }


def members(db, cfg):
    return [
        describe(player, cfg)
        for player in db.scalars(
            select(Player)
            .where(Player.telegram_id.is_not(None), Player.merged_into.is_(None))
            .order_by(Player.alias, Player.id)
        )
    ]


def change(db, cfg, actor: Player, player_id: int, body):
    # Check ownership here too: callers outside HTTP must not bypass it.
    if not is_owner(actor, cfg):
        raise DomainError("Действие доступно только владельцу", 403)
    player = db.scalar(
        select(Player)
        .where(Player.id == player_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not player or player.merged_into:
        raise DomainError("Игрок не найден", 404)
    if not player.telegram_id:
        raise DomainError("Игрок должен сначала войти через Telegram", 409)
    if is_owner(player, cfg):
        raise DomainError("Права владельца нельзя изменить в приложении", 409)
    if player.admin_access_revision != body.revision:
        raise DomainError("Права игрока уже изменились. Обновите список.", 409)
    before = has_admin_access(player, cfg)
    if before != body.is_admin:
        player.admin_access = body.is_admin
        player.admin_access_revision += 1
        audit(
            db,
            actor.id,
            "administrator.granted" if body.is_admin else "administrator.revoked",
            player_id=player.id,
            telegram_id=player.telegram_id,
            old_admin=before,
            new_admin=body.is_admin,
            revision=player.admin_access_revision,
        )
    return describe(player, cfg)
