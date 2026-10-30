from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    # hide_parameters: SQL errors must not contain message text or personal data.
    engine = create_async_engine(database_url, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name == "sqlite":  # tests: enforce foreign keys like PostgreSQL does

        @event.listens_for(engine.sync_engine, "connect")
        def _foreign_keys_on(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine, async_sessionmaker(engine, expire_on_commit=False)
