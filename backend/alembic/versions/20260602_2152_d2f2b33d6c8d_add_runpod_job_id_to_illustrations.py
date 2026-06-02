"""add runpod_job_id to illustrations

Revision ID: d2f2b33d6c8d
Revises: 450a78b8fda3
Create Date: 2026-06-02 21:52:39.053734

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2f2b33d6c8d"
down_revision: str | Sequence[str] | None = "450a78b8fda3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("runpod_job_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.drop_column("runpod_job_id")
