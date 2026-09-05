import asyncio
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from aegis_api.settings import Settings


class DependencyProbe(Protocol):
    async def check(self) -> bool: ...
    async def close(self) -> None: ...


class InfrastructureProbe:
    def __init__(self, settings: Settings) -> None:
        self.timeout = settings.dependency_timeout_seconds
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            hide_parameters=True,
        )
        self.redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=self.timeout,
            socket_timeout=self.timeout,
        )

    async def check(self) -> bool:
        try:
            async with asyncio.timeout(self.timeout):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return bool(await self.redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self.redis.aclose()
        await self.engine.dispose()
