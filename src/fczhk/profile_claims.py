from sqlalchemy import select

from .db import now
from .models import Player, ProfileClaim
from .ratings import lock_ratings
from .services import DomainError, audit, merge_guest


def serialize(db, claim):
    if claim is None:
        return None
    guest = db.get(Player, claim.guest_id)
    guest = db.get(Player, guest.merged_into) if guest.merged_into else guest
    return dict(
        player_id=claim.player_id,
        guest_id=claim.guest_id,
        status=claim.status,
        player=db.get(Player, claim.player_id).alias,
        guest=guest.alias,
        updated_at=claim.updated_at,
    )


def request_claim(db, player_id, guest_id):
    lock_ratings(db)
    guest = db.get(Player, guest_id)
    if not guest or guest.telegram_id is not None or guest.merged_into:
        raise DomainError("Выберите доступную историческую карточку", 409)
    claim = db.get(ProfileClaim, player_id)
    if claim and claim.status == "accepted":
        raise DomainError("Историческая карточка уже привязана. Обратитесь к администратору.", 409)
    if claim is None:
        claim = ProfileClaim(player_id=player_id, guest_id=guest_id)
        db.add(claim)
    claim.guest_id, claim.status, claim.updated_at = guest_id, "pending", now()
    audit(db, player_id, "profile.claimed", guest_id=guest_id)
    db.flush()
    return serialize(db, claim)


def resolve(db, actor, player_id, guest_id, accept):
    lock_ratings(db)
    claim = db.get(ProfileClaim, player_id)
    if not claim or claim.status != "pending" or claim.guest_id != guest_id:
        raise DomainError("Заявка изменилась. Обновите список.", 409)
    if accept:
        merge_guest(db, actor, guest_id, player_id)
        for other in db.scalars(
            select(ProfileClaim).where(
                ProfileClaim.guest_id == guest_id, ProfileClaim.status == "pending"
            )
        ):
            other.status, other.updated_at = "rejected", now()
    claim.status, claim.updated_at = ("accepted" if accept else "rejected"), now()
    audit(
        db, actor, "profile.claim_resolved", player_id=player_id, guest_id=guest_id, accepted=accept
    )
    return serialize(db, claim)
