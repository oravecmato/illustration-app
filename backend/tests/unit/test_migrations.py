"""Guard rails for Alembic migrations.

These tests fail loudly when somebody changes ``app/db/models.py``
without generating a matching migration, or when a migration's
downgrade path drifts from its upgrade path.
"""

from __future__ import annotations

import os

import pytest
from alembic.autogenerate import produce_migrations
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import ops
from sqlalchemy import create_engine, inspect

from alembic import command
from app.db.migrations import _make_config
from app.db.models import Base


def _sync_url(db_path: str) -> str:
    return f"sqlite:///{db_path}"


def _async_url(db_path: str) -> str:
    return f"sqlite+aiosqlite:///{db_path}"


def _all_ops(directives: ops.MigrationScript | ops.UpgradeOps | ops.MigrateOperation) -> list:
    """Flatten a migration directive tree into a list of leaf operations."""
    out: list = []
    if isinstance(directives, ops.MigrationScript):
        out.extend(_all_ops(directives.upgrade_ops))
        return out
    if isinstance(directives, ops.OpContainer):
        for child in directives.ops:
            out.extend(_all_ops(child))
        return out
    out.append(directives)
    return out


def _alembic_cfg(database_url: str) -> Config:
    cfg = _make_config(database_url)
    return cfg


def _snapshot_schema(db_path: str) -> dict[str, list[dict]]:
    """Reflect the live schema as a comparable dict."""
    engine = create_engine(_sync_url(db_path))
    inspector = inspect(engine)
    snapshot: dict[str, list[dict]] = {}
    for table in sorted(inspector.get_table_names()):
        if table == "alembic_version":
            continue
        cols = []
        for col in inspector.get_columns(table):
            cols.append(
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col["nullable"],
                }
            )
        snapshot[table] = sorted(cols, key=lambda c: c["name"])
    engine.dispose()
    return snapshot


def test_models_match_latest_migration(tmp_path):
    """Autogenerate against ``head`` must produce zero operations.

    If this fails, somebody changed a model without running
    ``alembic revision --autogenerate``. The failure message lists the
    missing operations so the fix is obvious.
    """
    db_path = str(tmp_path / "models_sync.db")
    sync_url = _sync_url(db_path)

    # Apply the full migration chain so the DB schema is at head.
    command.upgrade(_alembic_cfg(_async_url(db_path)), "head")

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        mc = MigrationContext.configure(
            connection=conn,
            opts={"compare_type": True, "compare_server_default": True},
        )
        diff = produce_migrations(mc, Base.metadata)
    engine.dispose()

    operations = _all_ops(diff)
    assert operations == [], (
        "Models are out of sync with the latest Alembic migration. "
        "Run `alembic revision --autogenerate -m '...'` and commit the "
        f"resulting file. Pending operations:\n{operations}"
    )


def test_upgrade_downgrade_upgrade_roundtrip(tmp_path):
    """``head → base → head`` must yield a byte-equivalent schema."""
    db_path = str(tmp_path / "roundtrip.db")
    cfg = _alembic_cfg(_async_url(db_path))

    command.upgrade(cfg, "head")
    before = _snapshot_schema(db_path)
    assert before, "Baseline upgrade produced no tables"

    command.downgrade(cfg, "base")
    # After downgrade-to-base only the alembic_version bookkeeping (if
    # any) survives — confirm all app tables are gone.
    inspector = inspect(create_engine(_sync_url(db_path)))
    app_tables = [t for t in inspector.get_table_names() if t != "alembic_version"]
    assert app_tables == [], f"Downgrade left tables behind: {app_tables}"

    command.upgrade(cfg, "head")
    after = _snapshot_schema(db_path)

    assert before == after, (
        "Schema after upgrade→downgrade→upgrade differs from initial upgrade. "
        "Some migration's downgrade() is not the inverse of its upgrade()."
    )


def test_alembic_ini_exists():
    """Sanity check: the helper resolves the project ``alembic.ini``."""
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    assert os.path.isfile(os.path.join(backend_root, "alembic.ini"))


@pytest.mark.parametrize("table", ["sessions", "session_messages", "runs", "illustrations"])
def test_baseline_creates_expected_tables(tmp_path, table):
    db_path = str(tmp_path / "baseline.db")
    command.upgrade(_alembic_cfg(_async_url(db_path)), "head")
    inspector = inspect(create_engine(_sync_url(db_path)))
    assert table in inspector.get_table_names()
