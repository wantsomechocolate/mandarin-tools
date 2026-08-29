"""add pronunciation and meaning to user_words

Revision ID: 350aeebcb421
Revises: 0c79510e2de6
Create Date: 2026-08-20 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '350aeebcb421'
down_revision: Union[str, Sequence[str], None] = '0c79510e2de6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('user_words', sa.Column('pronunciation', sa.String(), nullable=True))
    op.add_column('user_words', sa.Column('meaning', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('user_words', 'meaning')
    op.drop_column('user_words', 'pronunciation')
