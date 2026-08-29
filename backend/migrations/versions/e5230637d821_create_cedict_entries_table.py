"""create cedict_entries table

Revision ID: e5230637d821
Revises: 707d2760305a
Create Date: 2026-08-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5230637d821'
down_revision: Union[str, Sequence[str], None] = '707d2760305a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'cedict_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('simplified', sa.String(), nullable=False),
        sa.Column('traditional', sa.String(), nullable=True),
        sa.Column('pinyin', sa.String(), nullable=True),
        sa.Column('pinyin_numeric', sa.String(), nullable=True),
        sa.Column('definitions', sa.ARRAY(sa.String()), nullable=True),
    )
    op.create_index('ix_cedict_entries_simplified', 'cedict_entries', ['simplified'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_cedict_entries_simplified', table_name='cedict_entries')
    op.drop_table('cedict_entries')
