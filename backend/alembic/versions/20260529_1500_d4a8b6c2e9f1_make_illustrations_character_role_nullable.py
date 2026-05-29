"""force illustrations.character_role to be nullable

Revision ID: d4a8b6c2e9f1
Revises: c3d92b71f4a8
Create Date: 2026-05-29 15:00:00.000000

Background: migration f3dec31ba972 (i18n) attempted to flip
``illustrations.character_role`` from NOT NULL to NULL via
``batch_alter_table.alter_column(nullable=True)`` without supplying
``existing_nullable=False``. On dev databases that ran through that
migration, the column kept its NOT NULL constraint because the batch
operation elided the table-recreation step. The new illustration-first
pipeline (Agent 0b) explicitly allows ``character_role=None`` for the
single no-human shot per run (cap 1/5), so the constraint must go.

This migration forces the table to be recreated with the column as
nullable, regardless of its current state.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a8b6c2e9f1"
down_revision: str | Sequence[str] | None = "c3d92b71f4a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.alter_column(
            "character_role",
            existing_type=sa.VARCHAR(),
            nullable=True,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.alter_column(
            "character_role",
            existing_type=sa.VARCHAR(),
            nullable=False,
            existing_nullable=True,
        )
