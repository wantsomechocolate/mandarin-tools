"""add is_fragment to fragments

Revision ID: 0a65672db704
Revises: ec2b4eeb2e25
Create Date: 2026-08-30 00:00:00.000000

Fragment rows used to be presence-only ("this row exists" = "this is a
fragment"), which couldn't express "explicitly NOT a fragment here,
overriding a broader scope's marking" - that case was indistinguishable
from "no row, no opinion." is_fragment turns this into a real tri-state
per scope - see Fragment's docstring (models.py).

No data migration needed: every existing row was created only to mean
"this is a fragment" (the only thing a Fragment row could mean before this
column existed), so backfilling `true` via server_default is exactly
correct - zero rows change meaning.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a65672db704'
down_revision: Union[str, Sequence[str], None] = 'ec2b4eeb2e25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('fragments', sa.Column('is_fragment', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('fragments', 'is_fragment')
