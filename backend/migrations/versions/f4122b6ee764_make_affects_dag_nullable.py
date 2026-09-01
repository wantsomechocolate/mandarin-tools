"""make affects_dag nullable

Revision ID: f4122b6ee764
Revises: 97679be7880c
Create Date: 2026-08-31 00:00:00.000000

Fixes a data-model bug in affects_dag (added NOT NULL default true in
7de0ba930744): a UserWord row created purely to hold a note (no opinion on
segmentation weight) silently got affects_dag=true, which could override a
broader scope's explicit affects_dag=false without the user ever touching
that setting.

Makes the column nullable with no server default, so NULL becomes a real,
distinct third state ("no opinion at this scope, inherit from the next
broader scope") going forward. No backfill - every existing row keeps
whatever true/false value it already had; nullability only changes what
happens for rows created after this migration that intentionally leave the
field untouched (see UserWordCreate/UserWordUpsert, schemas.py). The
resolution walk in build_user_overlay (segmenter_loader.py) is updated
separately (application code, not this migration) to treat a NULL row as
"keep walking to the next broader scope."
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4122b6ee764'
down_revision: Union[str, Sequence[str], None] = '97679be7880c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('user_words', 'affects_dag', nullable=True, server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    # Backfill NULLs to true before re-adding NOT NULL - matches this
    # column's pre-migration meaning (every row unconditionally boosted
    # segmentation), the same reasoning 7de0ba930744's original backfill used.
    op.execute("UPDATE user_words SET affects_dag = true WHERE affects_dag IS NULL")
    op.alter_column('user_words', 'affects_dag', nullable=False, server_default=sa.text('true'))
