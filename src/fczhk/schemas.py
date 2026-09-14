from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

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
