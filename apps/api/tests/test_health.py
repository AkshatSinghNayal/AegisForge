import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from aegis_api.logging import JsonFormatter
from aegis_api.main import create_app
from aegis_api.settings import Settings


class Probe:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.closed = False

    async def check(self) -> bool:
        return self.available

    async def close(self) -> None:
        self.closed = True


def settings() -> Settings:
    return Settings(
        profile="test",
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        redis_url=SecretStr("redis://localhost/15"),
    )


@pytest.mark.parametrize("available", [True, False])
def test_health(available: bool) -> None:
    probe = Probe(available)
    with TestClient(create_app(settings(), probe)) as client:
        live = client.get("/health/live", headers={"X-Request-ID": "secret-canary"})
        assert live.status_code == 200
        assert live.json() == {"status": "alive"}
        UUID(live.headers["X-Request-ID"])
        ready = client.get("/health/ready")
        assert ready.status_code == (200 if available else 503)
        assert ready.json() == {"status": "ready" if available else "unavailable"}
        assert ready.headers["X-Request-ID"] != live.headers["X-Request-ID"]
        assert ready.headers["Cache-Control"] == "no-store"
        assert client.get("/docs").status_code == 404
    assert probe.closed


def test_logging_does_not_include_secret_payloads() -> None:
    record = logging.LogRecord(
        "test", logging.ERROR, "", 0, "secret-canary %s", ("password",), None
    )
    data = JsonFormatter().format(record)
    assert "secret-canary" not in data and "password" not in data
    assert json.loads(data)["event"] == "runtime_event"


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError):
        Settings(
            profile="prod",
            log_level="DEBUG",
            database_url=settings().database_url,
            redis_url=settings().redis_url,
        )


def test_invalid_configuration_does_not_expose_credentials() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            database_url="invalid://secret-canary", redis_url="redis://localhost/0"
        )
    assert "secret-canary" not in str(error.value)
