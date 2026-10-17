from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FCZHK_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    env: Literal["production", "demo", "test"] = "production"
    database_url: str = "sqlite:///./.local/fczhk.db"
    bot_token: str = ""
    bot_username: str = ""
    telegram_login_client_id: int = Field(default=0, ge=0, le=2**52 - 1)
    community_chat_id: str = ""
    publication_chat_id: str = ""
    owner_id: int = Field(default=0, ge=0, le=2**52 - 1)
    # Legacy bootstrap list; explicit decisions in the database take precedence.
    admin_ids: str = ""
    public_url: str = "http://localhost:8000"
    webhook_secret: str = ""
    auth_max_age_seconds: int = 300
    session_hours: int = 12
    membership_cache_seconds: int = 300
    min_field_players: int = 2
    require_two_keepers: bool = False
    auth_ip_limit: int = Field(default=30, ge=1)
    auth_global_limit: int = Field(default=300, ge=1)
    worker_stale_seconds: int = Field(default=120, ge=30)
    publication_stale_seconds: int = Field(default=300, ge=30)
    metrics_token: str = ""
    # Docker gives only the reverse proxy access to the API port.
    forwarded_allow_ips: str = "127.0.0.1"

    @property
    def admins(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}

    @property
    def effective_owner_id(self) -> int:
        if self.owner_id:
            return self.owner_id
        # Keep existing installations accessible when adding the owner role.
        return next((int(x.strip()) for x in self.admin_ids.split(",") if x.strip()), 0)

    @model_validator(mode="after")
    def validate_production(self):
        if any(not 0 < value < 2**52 for value in self.admins):
            raise ValueError("ADMIN_IDS must contain positive numeric Telegram user IDs")
        if self.env == "production":
            if not self.bot_token or not self.community_chat_id or not self.effective_owner_id:
                raise ValueError("Production requires BOT_TOKEN, COMMUNITY_CHAT_ID and OWNER_ID")
            if not self.public_url.startswith("https://"):
                raise ValueError("Production PUBLIC_URL must use HTTPS")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
        return self


@lru_cache
def settings() -> Settings:
    return Settings()
