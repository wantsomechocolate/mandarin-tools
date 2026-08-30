"""create user_word_sentences table

Revision ID: c911b7b6af46
Revises: a9e352dde715
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c911b7b6af46'
down_revision: Union[str, Sequence[str], None] = 'a9e352dde715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_word_sentences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_word_id', sa.Integer(), sa.ForeignKey('user_words.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sentence', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_user_word_sentences_user_word_id', 'user_word_sentences', ['user_word_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_word_sentences_user_word_id', table_name='user_word_sentences')
    op.drop_table('user_word_sentences')
