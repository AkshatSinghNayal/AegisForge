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
    dependency_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @model_validator(mode="after")
    def validate_database(self) -> "Settings":
        if not self.database_url.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("Use the PostgreSQL asyncpg driver")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
