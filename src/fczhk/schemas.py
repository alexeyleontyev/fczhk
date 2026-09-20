from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Position = Literal["field", "keeper"]
Team = Literal["white", "black"]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Payload):
    init_data: str = Field(max_length=16000)


class Name(Payload):
    alias: str = Field(min_length=2, max_length=60)


class Version(Payload):
    version: int = Field(ge=1)


class GameFields(Payload):
    starts_at: AwareDatetime
    location: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=1500)
    cost: int = Field(default=0, ge=0, le=100_000_000)
    payment_details: str = Field(default="", max_length=500)


class GameEdit(GameFields, Version):
    pass


class Join(Payload):
    position: Position


class Payment(Version):
    paid: bool


class Include(Version):
    player_id: int
    position: Position
    replace_id: int | None = None


class Promote(Version):
    position: Position


class Teams(Version):
    assignments: dict[int, Team | None]
    reset: bool = False


class LinkGuest(Payload):
    target_id: int


class TemplateEdit(Version):
    enabled: bool
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    location: str = Field(max_length=200)
    description: str = Field(default="", max_length=1500)
    cost: int = Field(default=0, ge=0, le=100_000_000)
    payment_details: str = Field(default="", max_length=500)

    @field_validator("location")
    @classmethod
    def check_location(cls, value, info):
        if info.data.get("enabled") and len(value) < 2:
            raise ValueError("Укажите место до включения расписания")
        return value


class RatingValues(Payload):
    position: Position
    attack: int | None = None
    defense: int

    @field_validator("attack", "defense", mode="before")
    @classmethod
    def score_in_tenths(cls, value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("Оценка должна быть числом от 0 до 5 с шагом 0,1")
        try:
            score = Decimal(str(value).replace(",", "."))
            if (
                not score.is_finite()
                or not 0 <= score <= 5
                or score * 10 != (score * 10).to_integral_value()
            ):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("Оценка должна быть числом от 0 до 5 с шагом 0,1") from None
        return int(score * 10)

    @model_validator(mode="after")
    def complete_pair(self):
        if self.position == "field" and self.attack is None:
            raise ValueError("Полевому игроку нужны обе оценки: атака и защита")
        if self.position == "keeper" and self.attack is not None:
            raise ValueError("Вратарю выставляется только защита")
        return self


class RatingEdit(RatingValues):
    revision: int = Field(ge=0)


class MatchRatingEdit(RatingValues, Version):
    pass


class BalanceSettings(Payload):
    epsilon: Decimal = Field(default=Decimal("0.10"), ge=0, le=10, decimal_places=2)
    max_epsilon: Decimal = Field(default=Decimal("0.50"), ge=0, le=10, decimal_places=2)
    epsilon_step: Decimal = Field(default=Decimal("0.10"), gt=0, le=10, decimal_places=2)
    min_distance: int | None = Field(default=None, ge=1, le=8)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.max_epsilon < self.epsilon:
            raise ValueError("Максимальный допуск не может быть меньше начального")
        if (self.max_epsilon - self.epsilon) / self.epsilon_step > 20:
            raise ValueError("Не более 20 шагов расширения допуска")
        return self


class BalanceGenerate(Version):
    settings: BalanceSettings = Field(default_factory=BalanceSettings)


class BalanceApply(Version):
    variant: int = Field(ge=0, le=2)


class ActualParticipant(Payload):
    player_id: int = Field(gt=0)
    team: Team
    position: Position


class GoalEvent(Payload):
    id: UUID
    team: Team
    kind: Literal["goal", "own_goal"] = "goal"
    author_id: int | None = Field(default=None, gt=0)
    assist_id: int | None = Field(default=None, gt=0)


class ResultEdit(Version):
    participants: list[ActualParticipant] = Field(max_length=100)
    goals: list[GoalEvent] = Field(max_length=200)
    completed: bool = False


class AuctionStart(Version):
    white_captain: int = Field(gt=0)
    black_captain: int = Field(gt=0)
    larger_team: Team | None = None


class AuctionBid(Payload):
    auction_id: int = Field(gt=0)
    lot_id: UUID
    amount: int = Field(ge=0, le=100, strict=True)


class AuctionControl(Payload):
    auction_id: int = Field(gt=0)
    revision: int = Field(ge=1)
    action: Literal["pause", "resume", "cancel", "manual"]


class PredictionEdit(Payload):
    white_score: int = Field(ge=0, le=200, strict=True)
    black_score: int = Field(ge=0, le=200, strict=True)
    revision: int = Field(ge=0)
    approved_version: int = Field(ge=1)
