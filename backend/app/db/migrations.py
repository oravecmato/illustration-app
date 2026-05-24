"""Alembic helpers.

Apply migrations programmatically from the FastAPI lifespan and from
test fixtures. Both paths build an ``alembic.config.Config`` that points
at the project's ``alembic.ini`` and passes the runtime database URL via
``config.attributes["sqlalchemy.url"]`` so ``alembic/env.py`` can use it
without re-reading the settings (which may differ in tests).
"""

from __future__ import annotations

import asyncio
import os

from alembic.config import Config

from alembic import command

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ALEMBIC_INI = os.path.join(_BACKEND_ROOT, "alembic.ini")


def _make_config(database_url: str) -> Config:
    cfg = Config(_ALEMBIC_INI)
    # Resolve script_location to an absolute path so alembic works no
    # matter the current working directory.
    cfg.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    cfg.attributes["sqlalchemy.url"] = database_url
    cfg.attributes["configure_logger"] = False  # FastAPI owns logging
    return cfg


def upgrade_to_head(database_url: str) -> None:
    """Apply all pending migrations against ``database_url`` (sync)."""
    cfg = _make_config(database_url)
    command.upgrade(cfg, "head")


async def upgrade_to_head_async(database_url: str) -> None:
    """Run :func:`upgrade_to_head` off the event loop.

    Alembic's command API is synchronous and opens its own connection
    pool, so we delegate to a worker thread to avoid blocking the
    FastAPI startup loop.
    """
    await asyncio.to_thread(upgrade_to_head, database_url)
