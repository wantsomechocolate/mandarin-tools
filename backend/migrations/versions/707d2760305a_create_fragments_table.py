"""create fragments table

Revision ID: 707d2760305a
Revises: 350aeebcb421
Create Date: 2026-08-21 10:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '707d2760305a'
down_revision: Union[str, Sequence[str], None] = '350aeebcb421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'fragments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_fragments_user_id', 'fragments', ['user_id'])
    op.create_index('ix_fragments_user_word', 'fragments', ['user_id', 'word'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_fragments_user_word', table_name='fragments')
    op.drop_index('ix_fragments_user_id', table_name='fragments')
    op.drop_table('fragments')