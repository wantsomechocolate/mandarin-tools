"""unify stopwords and add extra_match source

Revision ID: e5640d2e5491
Revises: 9ed863a26df4
Create Date: 2026-09-04 22:24:13.106937

Two independent changes bundled into one revision (both part of the same
segmentation-engine change):

1. stopwords: drops `algo_type` ("longest_match"/"tokenization") - both the
   DAG and the tokenizer now consult the same unified list (see
   service.get_user_stopwords/DEFAULT_STOPWORDS) rather than each seeing
   only its own half. Before dropping the column, de-duplicates any
   (user_id, word) pair that exists twice (once per algo_type) into a
   single row, keeping is_override=true if either copy had it (the
   stronger claim) - then drops algo_type + its CHECK constraint + the old
   3-column unique index, and adds a plain (user_id, word) unique index
   (same pattern GarbageWord already uses for its own user_id-nullable
   uniqueness, models.py).
2. analysis_results.source's CHECK constraint gains 'extra_match' (the new
   unified label for what full segmentation / the tokenizer's repeated-
   sequence pass contribute - see service.analyze_text) as an allowed
   value. The legacy 'trie'/'token'/'longest_match_only' values stay in the
   allowed set too, for existing historical rows - not backfilled, not
   removed from the constraint, since old analyses aren't re-run by this
   migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5640d2e5491'
down_revision: Union[str, Sequence[str], None] = '9ed863a26df4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- 1. stopwords: dedup (user_id, word) pairs before dropping algo_type ---
    # GROUP BY treats NULL user_id as equal to NULL user_id (unlike a plain
    # `=` comparison), so global rows dedup correctly too.
    op.execute("""
        WITH groups AS (
            SELECT user_id, word, MIN(id) AS keep_id, bool_or(is_override) AS merged_override
            FROM stopwords
            GROUP BY user_id, word
            HAVING COUNT(*) > 1
        )
        UPDATE stopwords s
        SET is_override = g.merged_override
        FROM groups g
        WHERE s.id = g.keep_id
    """)
    op.execute("""
        WITH groups AS (
            SELECT user_id, word, MIN(id) AS keep_id
            FROM stopwords
            GROUP BY user_id, word
            HAVING COUNT(*) > 1
        )
        DELETE FROM stopwords s
        USING groups g
        WHERE s.word = g.word
        AND s.user_id IS NOT DISTINCT FROM g.user_id
        AND s.id <> g.keep_id
    """)

    op.drop_index('ix_stopwords_user_word_algo', table_name='stopwords')
    op.drop_constraint('ck_stopwords_algo_type', 'stopwords', type_='check')
    op.drop_column('stopwords', 'algo_type')
    op.create_index('ix_stopwords_user_word', 'stopwords', ['user_id', 'word'], unique=True)

    # --- 2. analysis_results.source: add 'extra_match' ---
    op.drop_constraint('ck_analysis_results_source', 'analysis_results', type_='check')
    op.create_check_constraint(
        'ck_analysis_results_source',
        'analysis_results',
        "source IN ('trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only', 'extra_match')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_analysis_results_source', 'analysis_results', type_='check')
    op.create_check_constraint(
        'ck_analysis_results_source',
        'analysis_results',
        "source IN ('trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only')",
    )
    # NOTE: any row already carrying source='extra_match' violates the
    # constraint just restored - same inherent limitation as downgrading
    # any migration after data using the new state has been written.

    op.drop_index('ix_stopwords_user_word', table_name='stopwords')
    # algo_type's original per-row distinction can't be reconstructed (this
    # is a lossy downgrade for any row added after the upgrade, and for
    # every deduped row above) - restored as a NOT NULL column defaulting
    # to 'tokenization' so the column/constraint shape matches the old
    # schema, not as a claim about what each row's algorithm actually was.
    op.add_column('stopwords', sa.Column('algo_type', sa.String(), nullable=False, server_default='tokenization'))
    op.alter_column('stopwords', 'algo_type', server_default=None)
    op.create_check_constraint(
        'ck_stopwords_algo_type', 'stopwords',
        "algo_type IN ('longest_match', 'tokenization')",
    )
    op.create_index(
        'ix_stopwords_user_word_algo', 'stopwords',
        ['user_id', 'word', 'algo_type'], unique=True,
    )
