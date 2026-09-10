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
    demo_mode: bool = False
    scanner_provider: Literal["none", "mock", "zap"] = "none"
    zap_dispatch_key: SecretStr = SecretStr("")
    zap_secret_key: SecretStr = SecretStr("")
    zap_artifact_key: SecretStr = SecretStr("")
    zap_artifact_root: str = "/var/lib/aegis/artifacts"
    zap_allowlist: list[str] = Field(default_factory=list)
    zap_egress_network: str = "bridge"
    zap_gateway_image: str = "aegisforge-scanner-worker:phase8"
    zap_cpus: float = Field(default=1.0, ge=0.5, le=4)
    zap_memory: str = Field(default="2g", pattern=r"^[1-4]g$")
    zap_poll_seconds: float = Field(default=2.0, ge=1, le=10)
    zap_redaction_patterns: list[str] = Field(default_factory=list)
    mock_stage_seconds: float = Field(default=1, ge=0, le=10)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_runtime(self) -> "WorkerSettings":
        if not self.redis_url.get_secret_value().startswith(("redis://", "rediss://")):
            raise ValueError("Use a Redis connection URL")
        if self.scanner_provider == "mock" and not (
            self.demo_mode or self.profile == "test"
        ):
            raise ValueError("Mock scanner requires DEMO_MODE or test profile")
        if self.profile == "prod" and self.demo_mode:
            raise ValueError("Demo mode is disabled in production")
        if self.profile == "prod" and self.scanner_provider == "mock":
            raise ValueError("Mock scanner is disabled in production")
        if self.profile == "prod" and self.log_level == "DEBUG":
            raise ValueError("Debug logging is disabled in production")
        return self


class Settings(WorkerSettings):
    ai_provider: Literal["none", "mock", "gemini"] = "none"
    ai_model: str = Field(
        default="gemini-2.5-flash",
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    gemini_api_key: SecretStr = SecretStr("")
    scan_coordinator_enabled: bool = True
    scan_concurrency: int = Field(default=3, ge=1, le=100)
    scan_daily_quota: int = Field(default=100, ge=1, le=10000)
    scan_stage_timeout_seconds: int = Field(default=30, ge=30, le=300)
    local_secret_key: SecretStr = SecretStr("")
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
        if self.ai_provider == "mock" and (
            self.profile == "prod" or not (self.demo_mode or self.profile == "test")
        ):
            raise ValueError("Mock AI requires local demo or test profile")
        if self.ai_provider == "gemini" and not self.gemini_api_key.get_secret_value():
            raise ValueError("Gemini requires an API key")
        if (
            "preview" in self.ai_model.lower()
            or "experimental" in self.ai_model.lower()
        ):
            raise ValueError("Use a stable model ID")
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
