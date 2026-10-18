from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, now


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (Index("uq_players_alias", "alias", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    alias: Mapped[str] = mapped_column(String(60))
    # NULL preserves legacy ADMIN_IDS until the owner explicitly changes access.
    admin_access: Mapped[bool | None] = mapped_column(Boolean)
    admin_access_revision: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    merged_into: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class BotCallbackReceipt(Base):
    __tablename__ = "bot_callback_receipts"
    id: Mapped[str] = mapped_column(String(150), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (CheckConstraint("field_limit >= 2 AND keeper_limit >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    game_day: Mapped[str] = mapped_column(String(10), unique=True)
    season: Mapped[str] = mapped_column(
        String(40), default="2026", server_default="2026", index=True
    )
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    location: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[int] = mapped_column(Integer, default=0)
    payment_details: Mapped[str] = mapped_column(Text, default="")
    field_limit: Mapped[int] = mapped_column(default=16)
    keeper_limit: Mapped[int] = mapped_column(default=2)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(default=1)
    roster_version: Mapped[int] = mapped_column(default=0)
    approved_version: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id"),
        CheckConstraint("position IN ('field', 'keeper')"),
        CheckConstraint("team IS NULL OR team IN ('white', 'black')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    position: Mapped[str] = mapped_column(String(10))
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    team: Mapped[str | None] = mapped_column(String(10))


class GameTemplate(Base):
    __tablename__ = "game_template"
    __table_args__ = (
        CheckConstraint("opening_weekday BETWEEN 0 AND 6", name="ck_template_opening_weekday"),
        CheckConstraint("game_weekday BETWEEN 0 AND 6", name="ck_template_game_weekday"),
        CheckConstraint(
            "opening_weekday != game_weekday OR opening_time < start_time",
            name="ck_template_opening_before_game",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(default=1)
    opening_weekday: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    opening_time: Mapped[str] = mapped_column(String(5), default="12:00", server_default="12:00")
    game_weekday: Mapped[int] = mapped_column(default=4, server_default=text("4"))
    start_time: Mapped[str] = mapped_column(String(5), default="20:00")
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[int] = mapped_column(default=0)
    payment_details: Mapped[str] = mapped_column(Text, default="")


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    action: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class TeamSnapshot(Base):
    __tablename__ = "team_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    version: Mapped[int] = mapped_column()
    teams: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    __table_args__ = (UniqueConstraint("match_id", "version"),)


class Publication(Base):
    __tablename__ = "publications"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    kind: Mapped[str] = mapped_column(String(15))
    version: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    chat_id: Mapped[str] = mapped_column(String(100), default="")
    error: Mapped[str | None] = mapped_column(Text)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    stale_marked: Mapped[bool] = mapped_column(Boolean, default=False)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    __table_args__ = (UniqueConstraint("match_id", "kind", "version"),)


class RatingState(Base):
    """Singleton serializes rating writes and immutable team-input captures."""

    __tablename__ = "rating_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    revision: Mapped[int] = mapped_column(default=0)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("author_id", "player_id", "position"),
        CheckConstraint("author_id <> player_id"),
        CheckConstraint("defense BETWEEN 0 AND 50"),
        CheckConstraint(
            "(position = 'field' AND attack IS NOT NULL AND attack BETWEEN 0 AND 50) OR (position = 'keeper' AND attack IS NULL)"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    position: Mapped[str] = mapped_column(String(10))
    attack: Mapped[int | None] = mapped_column()
    defense: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class RatingHistory(Base):
    __tablename__ = "rating_history"
    __table_args__ = (UniqueConstraint("rating_id", "revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rating_id: Mapped[int] = mapped_column(ForeignKey("ratings.id"), index=True)
    revision: Mapped[int] = mapped_column()
    attack: Mapped[int | None] = mapped_column()
    defense: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ImportedRating(Base):
    """Exact source vote; current app votes from the same author supersede it."""

    __tablename__ = "imported_ratings"
    __table_args__ = (
        UniqueConstraint("source_id", "author_id", "player_id", "position"),
        CheckConstraint("author_id <> player_id"),
        CheckConstraint("position = 'field'"),
        CheckConstraint("attack_milli BETWEEN 0 AND 5000"),
        CheckConstraint("defense_milli BETWEEN 0 AND 5000"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100))
    source_sha256: Mapped[str] = mapped_column(String(64))
    author_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    position: Mapped[str] = mapped_column(String(10), default="field")
    attack_milli: Mapped[int] = mapped_column()
    defense_milli: Mapped[int] = mapped_column()
    attack_cell: Mapped[str] = mapped_column(String(12))
    defense_cell: Mapped[str] = mapped_column(String(12))
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class MatchRating(Base):
    """A fallback bound to a registration, never a permanent player rating."""

    __tablename__ = "match_ratings"
    __table_args__ = (
        CheckConstraint("defense BETWEEN 0 AND 50"),
        CheckConstraint(
            "(position = 'field' AND attack IS NOT NULL AND attack BETWEEN 0 AND 50) OR (position = 'keeper' AND attack IS NULL)"
        ),
    )
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    position: Mapped[str] = mapped_column(String(10))
    attack: Mapped[int | None] = mapped_column()
    defense: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class BalanceRun(Base):
    __tablename__ = "balance_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    roster_version: Mapped[int] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[list] = mapped_column(JSON)
    settings: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class TeamRatingDraft(Base):
    __tablename__ = "team_rating_drafts"
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("balance_runs.id"))
    variant: Mapped[int] = mapped_column()
    edited: Mapped[bool] = mapped_column(default=False)


class TeamRatingSnapshot(Base):
    __tablename__ = "team_rating_snapshots"
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("team_snapshots.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class MatchResult(Base):
    __tablename__ = "match_results"
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    completed: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ResultParticipant(Base):
    __tablename__ = "result_participants"
    __table_args__ = (
        CheckConstraint("team IN ('white', 'black')"),
        CheckConstraint("position IN ('field', 'keeper')"),
    )
    match_id: Mapped[int] = mapped_column(ForeignKey("match_results.match_id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    team: Mapped[str] = mapped_column(String(10))
    position: Mapped[str] = mapped_column(String(10))


class ResultGoal(Base):
    __tablename__ = "result_goals"
    __table_args__ = (
        CheckConstraint("team IN ('white', 'black')"),
        CheckConstraint("kind IN ('goal', 'own_goal')"),
        CheckConstraint("author_id IS NULL OR assist_id IS NULL OR author_id <> assist_id"),
        CheckConstraint("kind <> 'own_goal' OR assist_id IS NULL", name="ck_own_goal_no_assist"),
    )
    match_id: Mapped[int] = mapped_column(ForeignKey("match_results.match_id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(10))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    assist_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))


class Auction(Base):
    __tablename__ = "auctions"
    __table_args__ = (
        CheckConstraint("white_budget BETWEEN 0 AND 100 AND black_budget BETWEEN 0 AND 100"),
        CheckConstraint("white_captain <> black_captain"),
        CheckConstraint("white_limit >= 1 AND black_limit >= 1"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    roster_version: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(20), default="active")
    white_captain: Mapped[int] = mapped_column(ForeignKey("players.id"))
    black_captain: Mapped[int] = mapped_column(ForeignKey("players.id"))
    white_budget: Mapped[int] = mapped_column(default=100)
    black_budget: Mapped[int] = mapped_column(default=100)
    white_limit: Mapped[int] = mapped_column()
    black_limit: Mapped[int] = mapped_column()
    state: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class AuctionLot(Base):
    __tablename__ = "auction_lots"
    __table_args__ = (
        UniqueConstraint("auction_id", "number"),
        CheckConstraint("white_bid IS NULL OR white_bid BETWEEN 0 AND 100"),
        CheckConstraint("black_bid IS NULL OR black_bid BETWEEN 0 AND 100"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id"), index=True)
    registration_id: Mapped[int] = mapped_column(ForeignKey("registrations.id"))
    number: Mapped[int] = mapped_column()
    round: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(String(15), default="pending")
    white_bid: Mapped[int | None] = mapped_column()
    black_bid: Mapped[int | None] = mapped_column()
    winner: Mapped[str | None] = mapped_column(String(10))


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("white_score BETWEEN 0 AND 200 AND black_score BETWEEN 0 AND 200"),
        CheckConstraint("revision >= 1"),
    )
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    white_score: Mapped[int] = mapped_column()
    black_score: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)
    approved_version: Mapped[int] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
    succeeded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(String(100))


class SkippedGameDay(Base):
    __tablename__ = "skipped_game_days"
    game_day: Mapped[str] = mapped_column(String(10), primary_key=True)
    reason: Mapped[str] = mapped_column(String(300))
    actor_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class ProfileClaim(Base):
    __tablename__ = "profile_claims"
    __table_args__ = (CheckConstraint("status IN ('pending', 'accepted', 'rejected')"),)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    status: Mapped[str] = mapped_column(String(15), default="pending")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)
