"""remove scoping from known_words (familiarity is always global)

Revision ID: ec2b4eeb2e25
Revises: 54ffad806460
Create Date: 2026-08-30 00:00:00.000000

Familiarity was scoped for a while (same design as UserWord/Fragment) but
that's reversed here - see KnownWord's docstring (models.py). No data is
lost: as of this migration every known_words row already has
scope_analysis_id/scope_input_text_id both NULL (verified live before
writing this), so the column drop can't orphan or collide any rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec2b4eeb2e25'
down_revision: Union[str, Sequence[str], None] = '54ffad806460'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('ix_known_words_user_word_scope', table_name='known_words')
    op.create_index('ix_known_words_user_word', 'known_words', ['user_id', 'word'], unique=True)
    op.drop_constraint('ck_known_words_scope_mutually_exclusive', 'known_words', type_='check')
    op.drop_index('ix_known_words_scope_input_text_id', table_name='known_words')
    op.drop_index('ix_known_words_scope_analysis_id', table_name='known_words')
    op.drop_column('known_words', 'scope_input_text_id')
    op.drop_column('known_words', 'scope_analysis_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('known_words', sa.Column('scope_analysis_id', sa.Integer(), sa.ForeignKey('analyses.id'), nullable=True))
    op.add_column('known_words', sa.Column('scope_input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=True))
    op.create_index('ix_known_words_scope_analysis_id', 'known_words', ['scope_analysis_id'])
    op.create_index('ix_known_words_scope_input_text_id', 'known_words', ['scope_input_text_id'])
    op.create_check_constraint(
        'ck_known_words_scope_mutually_exclusive', 'known_words',
        'scope_analysis_id IS NULL OR scope_input_text_id IS NULL',
    )
    op.drop_index('ix_known_words_user_word', table_name='known_words')
    op.create_index(
        'ix_known_words_user_word_scope', 'known_words',
        ['user_id', 'word', 'scope_analysis_id', 'scope_input_text_id'],
        unique=True, postgresql_nulls_not_distinct=True,
    )
