"""add manual sub_phase and last_agreed_concept

Revision ID: a1f6c8e21b34
Revises: e0d7c8c320d3
Create Date: 2026-05-27 19:00:00.000000

Adds two columns to ``manual_illustration_sessions`` required by the
§ 6A redesign (collaboration mode v2):

- ``sub_phase`` — `concept_design` / `feedback_gathering` flag persisting
  which side of the render the manual loop is currently on. Defaults to
  `concept_design` (the state every new session starts in).
- ``last_agreed_concept`` — verbatim English concept the user most
  recently confirmed; consumed by Agent 7 (``manual_revise_prompts``)
  on subsequent feedback iterations.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f6c8e21b34"
down_revision: str | Sequence[str] | None = "e0d7c8c320d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("manual_illustration_sessions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "sub_phase",
                sa.String(),
                nullable=False,
                server_default="concept_design",
            )
        )
        batch_op.add_column(sa.Column("last_agreed_concept", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("manual_illustration_sessions", schema=None) as batch_op:
        batch_op.drop_column("last_agreed_concept")
        batch_op.drop_column("sub_phase")
