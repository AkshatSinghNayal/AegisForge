import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from factories import tenant
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from aegis_api.settings import get_settings


def migration_config() -> Config:
    return Config(str(Path(__file__).parents[1] / "alembic.ini"))


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Create a disposable DATABASE, never downgrade a user/development database."""
    import asyncio

    from sqlalchemy.engine import make_url

    if os.environ.get("AEGIS_PROFILE") != "test":
        pytest.fail("Database tests require AEGIS_PROFILE=test")
    original = os.environ["AEGIS_DATABASE_URL"]
    name = "phase4_test_" + uuid4().hex
    url = make_url(original)

    async def manage(create: bool) -> None:
        engine = create_async_engine(
            url, isolation_level="AUTOCOMMIT", hide_parameters=True
        )
        try:
            async with engine.connect() as conn:
                sql = (
                    f'CREATE DATABASE "{name}"'
                    if create
                    else f'DROP DATABASE "{name}" WITH (FORCE)'
                )
                await conn.execute(text(sql))
        finally:
            await engine.dispose()

    asyncio.run(manage(True))
    test_url = url.set(database=name).render_as_string(hide_password=False)
    os.environ["AEGIS_DATABASE_URL"] = test_url
    get_settings.cache_clear()
    try:
        command.upgrade(migration_config(), "head")
        yield test_url
    finally:
        os.environ["AEGIS_DATABASE_URL"] = original
        get_settings.cache_clear()
        asyncio.run(manage(False))


@pytest.fixture
async def db(migrated_database: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        migrated_database,
        hide_parameters=True,
        connect_args={"server_settings": {"timezone": "UTC"}},
    )
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def two_organizations(db: AsyncSession):  # type: ignore[no-untyped-def]
    return await tenant(db), await tenant(db)
