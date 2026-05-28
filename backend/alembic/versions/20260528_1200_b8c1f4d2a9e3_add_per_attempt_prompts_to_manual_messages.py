"""add per-attempt prompt/concept columns to manual_messages

Revision ID: b8c1f4d2a9e3
Revises: fa7fad0a24a7
Create Date: 2026-05-28 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c1f4d2a9e3"
down_revision: str | Sequence[str] | None = "fa7fad0a24a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("manual_messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("concept_used", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("positive_prompt", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("negative_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("manual_messages", schema=None) as batch_op:
        batch_op.drop_column("negative_prompt")
        batch_op.drop_column("positive_prompt")
        batch_op.drop_column("concept_used")
