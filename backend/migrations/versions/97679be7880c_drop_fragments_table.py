"""drop fragments table

Revision ID: 97679be7880c
Revises: c63bcfec94cb
Create Date: 2026-08-31 00:00:02.000000

Fragment is fully replaced by UserWord.affects_dag now (see UserWord's
docstring, models.py, and the previous migration which ported every
Fragment row over). Nothing reads or writes this table anymore.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97679be7880c'
down_revision: Union[str, Sequence[str], None] = 'c63bcfec94cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table('fragments')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'fragments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('is_fragment', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('scope_analysis_id', sa.Integer(), sa.ForeignKey('analyses.id'), nullable=True),
        sa.Column('scope_input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_fragments_user_id', 'fragments', ['user_id'])
    op.create_index('ix_fragments_scope_analysis_id', 'fragments', ['scope_analysis_id'])
    op.create_index('ix_fragments_scope_input_text_id', 'fragments', ['scope_input_text_id'])
    op.create_index(
        'ix_fragments_user_word_scope', 'fragments',
        ['user_id', 'word', 'scope_analysis_id', 'scope_input_text_id'],
        unique=True, postgresql_nulls_not_distinct=True,
    )
    op.create_check_constraint(
        'ck_fragments_scope_mutually_exclusive', 'fragments',
        'scope_analysis_id IS NULL OR scope_input_text_id IS NULL',
    )
    # Data is not restored - see the previous migration's downgrade note.
