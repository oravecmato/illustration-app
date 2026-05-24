"""Alembic environment for the Anime Illustrator backend.

Wires Alembic into the application configuration so there is one source
of truth for the database URL and the schema metadata. Supports both
sync (sqlite) and async (aiosqlite) URLs and uses batch mode so SQLite's
limited ALTER TABLE support doesn't block real migrations.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make the ``app`` package importable when running ``alembic`` from the
# backend root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Return the database URL, preferring runtime overrides.

    Lookup order:
    1. ``config.attributes["sqlalchemy.url"]`` — set programmatically by
       tests or by the application's startup hook before invoking
       ``command.upgrade``.
    2. ``DATABASE_URL`` environment variable — for ad-hoc CLI use.
    3. ``app.config.Settings.database_url`` — the normal production path.
    """
    url = config.attributes.get("sqlalchemy.url")
    if url:
        return url
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    return get_settings().database_url


def _is_async_url(url: str) -> bool:
    return "+aiosqlite" in url or "+asyncpg" in url or "+aiomysql" in url


def _to_sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "").replace("+asyncpg", "").replace("+aiomysql", "")


def _configure_context(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can only ALTER TABLE in very limited ways; batch mode
        # transparently emits the copy-and-rename dance.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI)."""
    url = _to_sync_url(_resolve_url())
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(url: str) -> None:
    cfg_section = config.get_section(config.config_ini_section, {}) or {}
    cfg_section["sqlalchemy.url"] = url
    connectable = engine_from_config(cfg_section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _configure_context(connection)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


async def _run_async_migrations(url: str) -> None:
    cfg_section = config.get_section(config.config_ini_section, {}) or {}
    cfg_section["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        cfg_section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(lambda sync_conn: _do_run_migrations(sync_conn))
    await connectable.dispose()


def _do_run_migrations(connection: Connection) -> None:
    _configure_context(connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with a live DBAPI connection)."""
    url = _resolve_url()
    if _is_async_url(url):
        asyncio.run(_run_async_migrations(url))
    else:
        _run_sync_migrations(url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
