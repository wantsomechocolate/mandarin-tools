"""create starred_words table

Revision ID: a9e352dde715
Revises: 7ef65ed1e654
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9e352dde715'
down_revision: Union[str, Sequence[str], None] = '7ef65ed1e654'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'starred_words',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_starred_words_user_id', 'starred_words', ['user_id'])
    op.create_index('ix_starred_words_user_word', 'starred_words', ['user_id', 'word'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_starred_words_user_word', table_name='starred_words')
    op.drop_index('ix_starred_words_user_id', table_name='starred_words')
    op.drop_table('starred_words')
