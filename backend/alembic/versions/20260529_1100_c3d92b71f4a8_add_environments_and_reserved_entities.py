"""add environments + reserved_entities + main_character_role + per-illustration environment

Revision ID: c3d92b71f4a8
Revises: b8c1f4d2a9e3
Create Date: 2026-05-29 11:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d92b71f4a8"
down_revision: str | Sequence[str] | None = "b8c1f4d2a9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("main_character_role", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("environments_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("reserved_entities_json", sa.Text(), nullable=True))

    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("environment_label", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("environment_aspect", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.drop_column("environment_aspect")
        batch_op.drop_column("environment_label")

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("reserved_entities_json")
        batch_op.drop_column("environments_json")
        batch_op.drop_column("main_character_role")
