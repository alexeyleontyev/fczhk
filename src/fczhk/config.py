from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FCZHK_", env_file=".env", extra="ignore")
    env: Literal["production", "demo", "test"] = "production"
    database_url: str = "sqlite:///./.local/fczhk.db"
    bot_token: str = ""
    bot_username: str = ""
    community_chat_id: str = ""
    publication_chat_id: str = ""
    admin_ids: str = ""
    public_url: str = "http://localhost:8000"
    webhook_secret: str = ""
    auth_max_age_seconds: int = 300
    session_hours: int = 12
    membership_cache_seconds: int = 300
    min_field_players: int = 2
    require_two_keepers: bool = False

    @property
    def admins(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

    @model_validator(mode="after")
    def validate_production(self):
        if self.env == "production":
            if not self.bot_token or not self.community_chat_id or not self.admins:
                raise ValueError("Production requires BOT_TOKEN, COMMUNITY_CHAT_ID and ADMIN_IDS")
            if not self.public_url.startswith("https://"):
                raise ValueError("Production PUBLIC_URL must use HTTPS")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
