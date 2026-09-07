"""create word frequency overrides table

Revision ID: 1930f98d2643
Revises: a16cc143fd41
Create Date: 2026-09-07 11:45:34.564428

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1930f98d2643'
down_revision: Union[str, Sequence[str], None] = 'a16cc143fd41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'word_frequency_overrides',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('frequency', sa.BigInteger(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index(
        'ix_word_frequency_overrides_word', 'word_frequency_overrides', ['word'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_word_frequency_overrides_word', table_name='word_frequency_overrides')
    op.drop_table('word_frequency_overrides')
