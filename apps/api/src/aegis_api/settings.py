from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AEGIS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    profile: Literal["dev", "test", "prod"] = "dev"
    redis_url: SecretStr
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_runtime(self) -> "WorkerSettings":
        if not self.redis_url.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("Use a Redis connection URL")
        if self.profile == "prod" and self.log_level == "DEBUG":
            raise ValueError("Debug logging is disabled in production")
        return self


class Settings(WorkerSettings):
    database_url: SecretStr
    app_origin: str = "http://localhost:5173"
    cookie_secure: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_sender: str = "noreply@localhost"
    smtp_starttls: bool = True
    access_seconds: int = Field(default=600, ge=60, le=900)
    refresh_days: int = Field(default=30, ge=1, le=30)
    reset_minutes: int = Field(default=30, ge=1, le=60)
    auth_rate_limit: int = Field(default=10, ge=1, le=100)
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @model_validator(mode="after")
    def validate_database(self) -> "Settings":
        if not self.database_url.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("Use the PostgreSQL asyncpg driver")
        from urllib.parse import urlsplit

        origin = urlsplit(self.app_origin)
        if origin.scheme not in {"http", "https"} or not origin.netloc or origin.path:
            raise ValueError("Use an HTTP origin without a path")
        if self.profile == "prod" and (
            not self.cookie_secure or origin.scheme != "https"
        ):
            raise ValueError(
                "Production authentication requires HTTPS and secure cookies"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
