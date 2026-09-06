import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from aegis_api.db.models import Base
from aegis_api.settings import get_settings

target_metadata = Base.metadata


def offline() -> None:
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        literal_binds=True,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = create_async_engine(
        get_settings().database_url.get_secret_value(),
        poolclass=pool.NullPool,
        hide_parameters=True,
    )
    async with engine.connect() as connection:

        def run_migrations(sync_connection):  # type: ignore[no-untyped-def]
            context.configure(
                connection=sync_connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()

        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    offline()
else:
    asyncio.run(online())
