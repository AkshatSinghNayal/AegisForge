import asyncio
from unittest.mock import AsyncMock

import pytest
from test_health import settings

from aegis_api.dependencies import InfrastructureProbe


@pytest.mark.parametrize("failure", ["database", "redis", "timeout", "none"])
async def test_dependency_probe(failure: str) -> None:
    probe = InfrastructureProbe(settings())
    await probe.close()
    connection = AsyncMock()
    connection.__aenter__.return_value = connection
    connection.execute.side_effect = (
        RuntimeError("secret") if failure == "database" else None
    )
    engine = AsyncMock()
    engine.connect = lambda: connection
    redis = AsyncMock()
    if failure == "redis":
        redis.ping.side_effect = RuntimeError("secret")
    elif failure == "timeout":

        async def slow() -> bool:
            await asyncio.sleep(1)
            return True

        redis.ping.side_effect = slow
    else:
        redis.ping.return_value = True
    probe.engine = engine
    probe.redis = redis
    probe.timeout = 0.01
    assert await probe.check() is (failure == "none")
    await probe.close()
    redis.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
