"""port fragment data into user_words

Revision ID: c63bcfec94cb
Revises: 7de0ba930744
Create Date: 2026-08-31 00:00:01.000000

Data-only migration: carries every existing Fragment row over into
UserWord.affects_dag=false, then leaves the (now-superseded) fragments
table in place untouched so its data can still be spot-checked against the
result before the next migration drops it for good.

For each Fragment row, at its exact (user_id, word, scope):
- If no UserWord row exists there yet, create one with affects_dag=false
  and the fragment's note copied into UserWord.notes (pronunciation/
  meaning left null - a Fragment never had those).
- If a UserWord row already exists there (the exact contradictory state
  the word-detail panel used to warn about - a word marked both a
  UserWord and a Fragment at the same scope), its own pronunciation/
  meaning/notes are left untouched; only affects_dag is set to false, and
  the fragment's note is appended to the end of its notes (blank-line
  separated) if not already present verbatim - this is what makes the
  UPDATE safe to run after the INSERT below without double-appending into
  rows it just created itself, since their notes already equal the
  fragment's note exactly at that point.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c63bcfec94cb'
down_revision: Union[str, Sequence[str], None] = '7de0ba930744'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create a UserWord row for every fragment that doesn't already have
    # one at its exact scope.
    op.execute("""
        INSERT INTO user_words (
            user_id, word, scope_analysis_id, scope_input_text_id,
            affects_dag, notes, created_at, updated_at
        )
        SELECT
            f.user_id, f.word, f.scope_analysis_id, f.scope_input_text_id,
            false, f.note, f.created_at, f.updated_at
        FROM fragments f
        WHERE NOT EXISTS (
            SELECT 1 FROM user_words uw
            WHERE uw.user_id = f.user_id AND uw.word = f.word
              AND uw.scope_analysis_id IS NOT DISTINCT FROM f.scope_analysis_id
              AND uw.scope_input_text_id IS NOT DISTINCT FROM f.scope_input_text_id
        )
    """)

    # Set affects_dag=false and append the note (if not already present
    # verbatim) on every UserWord row a fragment applies to - this also
    # covers the rows the INSERT above just created (idempotent no-op for
    # them, since their notes already equal the fragment's note exactly).
    op.execute("""
        UPDATE user_words uw
        SET affects_dag = false,
            notes = CASE
                WHEN f.note IS NULL OR f.note = '' THEN uw.notes
                WHEN uw.notes IS NULL OR uw.notes = '' THEN f.note
                WHEN POSITION(f.note IN uw.notes) > 0 THEN uw.notes
                ELSE uw.notes || E'\\n\\n' || f.note
            END
        FROM fragments f
        WHERE uw.user_id = f.user_id AND uw.word = f.word
          AND uw.scope_analysis_id IS NOT DISTINCT FROM f.scope_analysis_id
          AND uw.scope_input_text_id IS NOT DISTINCT FROM f.scope_input_text_id
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Not reversible: there's no way to tell a ported affects_dag=false
    # UserWord row apart from one a user set to false themselves after this
    # migration ran, so there's nothing safe to undo here. The paired
    # upgrade in the next migration (dropping fragments) is what would
    # actually need reversing first in a real rollback, at which point
    # this data would already be unreachable from the app either way.
    pass
