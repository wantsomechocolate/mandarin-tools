"""add affects_dag to user_words

Revision ID: 7de0ba930744
Revises: 0a65672db704
Create Date: 2026-08-31 00:00:00.000000

First step of replacing the standalone Fragment concept with a single
boolean on UserWord - see UserWord's docstring (models.py) for the full
reasoning. affects_dag controls whether a UserWord entry's frequency
boosts DAG segmentation; everything else about the entry (pronunciation/
meaning/notes) is unaffected by it.

No data migration needed here: every existing UserWord row was created
under the old all-UserWords-boost-segmentation behavior, so backfilling
`true` via server_default preserves it exactly - zero rows change meaning.
The actual Fragment -> UserWord data port happens in the next migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7de0ba930744'
down_revision: Union[str, Sequence[str], None] = '0a65672db704'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_words', sa.Column('affects_dag', sa.Boolean(), nullable=False, server_default=sa.text('true')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_words', 'affects_dag')
