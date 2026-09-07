"""create word_notes table, move StarredWord.note into it

Revision ID: a16cc143fd41
Revises: 4b3d642d78ed
Create Date: 2026-09-07 00:00:00.000000

A note used to be a StarredWord-only column (added to that table so a
starred word could carry a personal annotation). Generalized here into its
own table so any word can have a note regardless of starred/known/
user-word status - see WordNote's docstring, models.py.

Existing notes are carried over: every non-null, non-empty
starred_words.note becomes its own word_notes row (same user_id/word),
before the column is dropped from starred_words. A word that was starred
with a blank/whitespace-only note (previously a valid, if pointless, state)
does NOT get a word_notes row - WordNote.note is NOT NULL, and an empty
note has no reason to exist as its own row (same "this row's only reason to
exist" pattern KnownWord's familiarity already uses - see WordNote's
docstring).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a16cc143fd41'
down_revision: Union[str, Sequence[str], None] = '4b3d642d78ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'word_notes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('word', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_word_notes_user_id', 'word_notes', ['user_id'])
    op.create_index('ix_word_notes_user_word', 'word_notes', ['user_id', 'word'], unique=True)

    # Carry over existing starred-word notes before the column disappears.
    op.execute("""
        INSERT INTO word_notes (user_id, word, note, created_at, updated_at)
        SELECT user_id, word, note, created_at, updated_at
        FROM starred_words
        WHERE note IS NOT NULL AND trim(note) != ''
    """)

    op.drop_column('starred_words', 'note')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('starred_words', sa.Column('note', sa.String(), nullable=True))

    # Best-effort restore for words that were both starred and noted - a
    # word_notes row with no matching starred_words row (the whole point of
    # this feature) has nowhere to go back to and is dropped along with the
    # table, same inherent limitation as downgrading any migration after
    # data using the new state has been written.
    op.execute("""
        UPDATE starred_words
        SET note = word_notes.note
        FROM word_notes
        WHERE starred_words.user_id = word_notes.user_id
          AND starred_words.word = word_notes.word
    """)

    op.drop_index('ix_word_notes_user_word', table_name='word_notes')
    op.drop_index('ix_word_notes_user_id', table_name='word_notes')
    op.drop_table('word_notes')
