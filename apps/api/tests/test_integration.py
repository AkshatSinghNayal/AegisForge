import os

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from aegis_api.main import create_app
from aegis_api.settings import Settings


@pytest.mark.integration
def test_actual_services() -> None:
    # Missing credentials fail this explicit integration gate; never silently skip.
    settings = Settings(
        profile="test",
        database_url=SecretStr(os.environ["AEGIS_DATABASE_URL"]),
        redis_url=SecretStr(os.environ["AEGIS_REDIS_URL"]),
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200


@pytest.mark.integration
@pytest.mark.parametrize("dependency", ["database", "redis"])
def test_actual_unreachable_dependency(dependency: str) -> None:
    settings = Settings(
        profile="test",
        database_url=SecretStr(
            "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/invalid"
            if dependency == "database"
            else os.environ["AEGIS_DATABASE_URL"]
        ),
        redis_url=SecretStr(
            "redis://127.0.0.1:1/0"
            if dependency == "redis"
            else os.environ["AEGIS_REDIS_URL"]
        ),
        dependency_timeout_seconds=0.2,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
