"""add scoping to known_words, user_words, fragments

Revision ID: 7ef65ed1e654
Revises: c8965952973e
Create Date: 2026-08-31 00:00:00.000000

Adds optional analysis/input-text scoping to KnownWord, UserWord, and
Fragment - both NULL (the default, all existing rows) means global,
unchanged from today. At most one of the two scope columns may be set (see
each table's new CHECK constraint) - "scope to this analysis" and "scope to
this text" are alternative choices, not stackable.

Also adds UserWord.created_from_analysis_id/created_from_input_text_id -
purely informational, tracks where an entry (global or scoped) was first
added from.

The old (user_id, word) unique index on each table is replaced by
(user_id, word, scope_analysis_id, scope_input_text_id) with
NULLS NOT DISTINCT (Postgres 17, confirmed) - a plain unique index would
treat every NULL/NULL pair as distinct and silently allow duplicate global
rows for the same word, which is exactly the invariant this needs to keep.

No data migration needed: every existing row already has both new scope
columns NULL, which is precisely "global", matching current behavior with
zero rows changing meaning.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ef65ed1e654'
down_revision: Union[str, Sequence[str], None] = 'c8965952973e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # known_words
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

    # user_words
    op.add_column('user_words', sa.Column('scope_analysis_id', sa.Integer(), sa.ForeignKey('analyses.id'), nullable=True))
    op.add_column('user_words', sa.Column('scope_input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=True))
    op.add_column('user_words', sa.Column('created_from_analysis_id', sa.Integer(), sa.ForeignKey('analyses.id'), nullable=True))
    op.add_column('user_words', sa.Column('created_from_input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=True))
    op.create_index('ix_user_words_scope_analysis_id', 'user_words', ['scope_analysis_id'])
    op.create_index('ix_user_words_scope_input_text_id', 'user_words', ['scope_input_text_id'])
    op.create_check_constraint(
        'ck_user_words_scope_mutually_exclusive', 'user_words',
        'scope_analysis_id IS NULL OR scope_input_text_id IS NULL',
    )
    op.drop_index('ix_user_words_user_word', table_name='user_words')
    op.create_index(
        'ix_user_words_user_word_scope', 'user_words',
        ['user_id', 'word', 'scope_analysis_id', 'scope_input_text_id'],
        unique=True, postgresql_nulls_not_distinct=True,
    )

    # fragments
    op.add_column('fragments', sa.Column('scope_analysis_id', sa.Integer(), sa.ForeignKey('analyses.id'), nullable=True))
    op.add_column('fragments', sa.Column('scope_input_text_id', sa.Integer(), sa.ForeignKey('input_texts.id'), nullable=True))
    op.create_index('ix_fragments_scope_analysis_id', 'fragments', ['scope_analysis_id'])
    op.create_index('ix_fragments_scope_input_text_id', 'fragments', ['scope_input_text_id'])
    op.create_check_constraint(
        'ck_fragments_scope_mutually_exclusive', 'fragments',
        'scope_analysis_id IS NULL OR scope_input_text_id IS NULL',
    )
    op.drop_index('ix_fragments_user_word', table_name='fragments')
    op.create_index(
        'ix_fragments_user_word_scope', 'fragments',
        ['user_id', 'word', 'scope_analysis_id', 'scope_input_text_id'],
        unique=True, postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # fragments
    op.drop_index('ix_fragments_user_word_scope', table_name='fragments')
    op.create_index('ix_fragments_user_word', 'fragments', ['user_id', 'word'], unique=True)
    op.drop_constraint('ck_fragments_scope_mutually_exclusive', 'fragments', type_='check')
    op.drop_index('ix_fragments_scope_input_text_id', table_name='fragments')
    op.drop_index('ix_fragments_scope_analysis_id', table_name='fragments')
    op.drop_column('fragments', 'scope_input_text_id')
    op.drop_column('fragments', 'scope_analysis_id')

    # user_words
    op.drop_index('ix_user_words_user_word_scope', table_name='user_words')
    op.create_index('ix_user_words_user_word', 'user_words', ['user_id', 'word'], unique=True)
    op.drop_constraint('ck_user_words_scope_mutually_exclusive', 'user_words', type_='check')
    op.drop_index('ix_user_words_scope_input_text_id', table_name='user_words')
    op.drop_index('ix_user_words_scope_analysis_id', table_name='user_words')
    op.drop_column('user_words', 'created_from_input_text_id')
    op.drop_column('user_words', 'created_from_analysis_id')
    op.drop_column('user_words', 'scope_input_text_id')
    op.drop_column('user_words', 'scope_analysis_id')

    # known_words
    op.drop_index('ix_known_words_user_word_scope', table_name='known_words')
    op.create_index('ix_known_words_user_word', 'known_words', ['user_id', 'word'], unique=True)
    op.drop_constraint('ck_known_words_scope_mutually_exclusive', 'known_words', type_='check')
    op.drop_index('ix_known_words_scope_input_text_id', table_name='known_words')
    op.drop_index('ix_known_words_scope_analysis_id', table_name='known_words')
    op.drop_column('known_words', 'scope_input_text_id')
    op.drop_column('known_words', 'scope_analysis_id')
