"""create word_visibility table

Revision ID: a8057121e612
Revises: f4122b6ee764
Create Date: 2026-08-31 00:00:00.000000

New "hide word from results" feature - a scoped table sibling to UserWord,
not a column on it, so a word can be hidden with zero interest in
pronunciation/meaning/notes/affects_dag (e.g. 的, 了, 是) without disturbing
what "has a UserWord row" means elsewhere. Same scope_analysis_id/
scope_input_text_id shape, mutual-exclusion CHECK, and NULLS NOT DISTINCT
unique index as UserWord (see 7ef65ed1e654) - see WordVisibility's
docstring (models.py) for the full design, including why `hidden` is a
plain NOT NULL boolean rather than the tri-state UserWord.affects_dag needs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8057121e612'
down_revision: Union[str, Sequence[str], None] = 'f4122b6ee764'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'word_visibility',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('hidden', sa.Boolean(), nullable=False),
        sa.Column('scope_analysis_id', sa.Integer(), sa.ForeignKey('analyses.id'), nullable=True),
        sa.Column('scope_input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_word_visibility_user_id', 'word_visibility', ['user_id'])
    op.create_index('ix_word_visibility_word', 'word_visibility', ['word'])
    op.create_index('ix_word_visibility_scope_analysis_id', 'word_visibility', ['scope_analysis_id'])
    op.create_index('ix_word_visibility_scope_input_text_id', 'word_visibility', ['scope_input_text_id'])
    op.create_check_constraint(
        'ck_word_visibility_scope_mutually_exclusive', 'word_visibility',
        'scope_analysis_id IS NULL OR scope_input_text_id IS NULL',
    )
    op.create_index(
        'ix_word_visibility_user_word_scope', 'word_visibility',
        ['user_id', 'word', 'scope_analysis_id', 'scope_input_text_id'],
        unique=True, postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('word_visibility')
