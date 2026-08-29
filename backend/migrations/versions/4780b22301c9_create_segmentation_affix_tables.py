"""create segmentation affix tables

Revision ID: 4780b22301c9
Revises: e5230637d821
Create Date: 2026-08-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4780b22301c9'
down_revision: Union[str, Sequence[str], None] = 'e5230637d821'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'segmentation_affixes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('affix', sa.String(), nullable=False),
        sa.Column('position', sa.String(), nullable=False),
        sa.Column('discount', sa.Float(), nullable=False),
        sa.CheckConstraint("position IN ('prefix', 'suffix')", name='ck_segmentation_affixes_position'),
        sa.CheckConstraint('discount > 0 AND discount <= 1', name='ck_segmentation_affixes_discount'),
    )
    op.create_index(
        'ix_segmentation_affixes_affix_position', 'segmentation_affixes', ['affix', 'position'], unique=True
    )

    op.create_table(
        'segmentation_affix_exemptions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
    )
    op.create_index(
        'ix_segmentation_affix_exemptions_word', 'segmentation_affix_exemptions', ['word'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_segmentation_affix_exemptions_word', table_name='segmentation_affix_exemptions')
    op.drop_table('segmentation_affix_exemptions')
    op.drop_index('ix_segmentation_affixes_affix_position', table_name='segmentation_affixes')
    op.drop_table('segmentation_affixes')
