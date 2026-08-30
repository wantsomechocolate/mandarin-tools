"""replace user_word_sentences with standalone sample_sentences

Revision ID: 54ffad806460
Revises: c911b7b6af46
Create Date: 2026-08-30 00:00:00.000000

Sample sentences were originally attached to a UserWord row (a word had to
be "in your dictionary" to have sample sentences). That's reversed here:
sample sentences become their own top-level, per-user, per-word entity -
see SampleSentence's docstring (models.py). Existing rows are carried over
by joining through user_words to recover (user_id, word) before dropping
the old table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54ffad806460'
down_revision: Union[str, Sequence[str], None] = 'c911b7b6af46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sample_sentences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('sentence', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sample_sentences_user_id', 'sample_sentences', ['user_id'])
    op.create_index('ix_sample_sentences_word', 'sample_sentences', ['word'])
    op.create_index('ix_sample_sentences_user_word', 'sample_sentences', ['user_id', 'word'])

    # Carry over existing rows - recover (user_id, word) via the parent
    # UserWord row each one was attached to.
    op.execute("""
        INSERT INTO sample_sentences (user_id, word, sentence, created_at)
        SELECT uw.user_id, uw.word, uws.sentence, uws.created_at
        FROM user_word_sentences uws
        JOIN user_words uw ON uws.user_word_id = uw.id
    """)

    op.drop_index('ix_user_word_sentences_user_word_id', table_name='user_word_sentences')
    op.drop_table('user_word_sentences')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'user_word_sentences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_word_id', sa.Integer(), sa.ForeignKey('user_words.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sentence', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_user_word_sentences_user_word_id', 'user_word_sentences', ['user_word_id'])

    # Not reconstructed - a sample sentence's word may no longer match any
    # UserWord row at all (the whole point of this migration), so there is
    # no lossless way back. Downgrade drops the data rather than guessing.
    op.drop_index('ix_sample_sentences_user_word', table_name='sample_sentences')
    op.drop_index('ix_sample_sentences_word', table_name='sample_sentences')
    op.drop_index('ix_sample_sentences_user_id', table_name='sample_sentences')
    op.drop_table('sample_sentences')
