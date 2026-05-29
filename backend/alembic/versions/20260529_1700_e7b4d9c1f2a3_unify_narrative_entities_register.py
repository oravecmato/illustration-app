"""unify narrative_entities register: drop companion fields, rename reserved_entities_json

Revision ID: e7b4d9c1f2a3
Revises: d4a8b6c2e9f1
Create Date: 2026-05-29 17:00:00.000000

Migrates from the legacy companion / reserved_entities split into a single
``narrative_entities`` register. Concretely:

* ``runs.reserved_entities_json`` → ``runs.narrative_entities_json``. Same
  JSON-encoded list shape (legacy entries are forward-compatible because
  the new ``NarrativeEntity`` shape is a strict superset of the old
  ``ReservedEntity`` shape with the ``importance`` field expanded from
  ``{primary, secondary}`` to ``{primary, secondary, supporting}``).
* ``illustrations.companion_description`` and
  ``illustrations.companion_interaction`` → dropped. Replaced by
  ``illustrations.contains_entity_label`` (a single nullable Text column
  pointing at the NarrativeEntity register on the parent Run).

Legacy data is not back-filled (companion text was free-form and cannot
be safely promoted into a labelled entity). Old runs render their saved
images and paragraphs fine; only the prior companion description popover
disappears from the UI.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b4d9c1f2a3"
down_revision: str | Sequence[str] | None = "d4a8b6c2e9f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column(
            "reserved_entities_json",
            new_column_name="narrative_entities_json",
            existing_type=sa.Text(),
            existing_nullable=True,
        )

    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("contains_entity_label", sa.Text(), nullable=True))
        batch_op.drop_column("companion_interaction")
        batch_op.drop_column("companion_description")


def downgrade() -> None:
    with op.batch_alter_table("illustrations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("companion_description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("companion_interaction", sa.Text(), nullable=True))
        batch_op.drop_column("contains_entity_label")

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.alter_column(
            "narrative_entities_json",
            new_column_name="reserved_entities_json",
            existing_type=sa.Text(),
            existing_nullable=True,
        )
