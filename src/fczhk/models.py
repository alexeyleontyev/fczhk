from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, now


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    alias: Mapped[str] = mapped_column(String(60))
    merged_into: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=now)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
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
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(default=1)
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
