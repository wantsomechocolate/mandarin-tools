"""add repeated_sequence source, split from extra_match

Revision ID: 4b3d642d78ed
Revises: e5640d2e5491
Create Date: 2026-09-04 23:32:05.607207

analysis_results.source's CHECK constraint gains 'repeated_sequence' as an
allowed value - service.analyze_text now tags tokenizer/repeated-sequence
finds with this label instead of lumping them into 'extra_match' alongside
full-segmentation-diff finds, so the two can be filtered independently. Any
row already carrying 'extra_match' from before this split may represent
either kind - not reclassified here, since there's no way to tell which one
a pre-split row was without re-running analysis, and old analyses aren't
re-run by this migration (same "never backfilled" precedent as every other
source-value change to this column).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b3d642d78ed'
down_revision: Union[str, Sequence[str], None] = 'e5640d2e5491'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_analysis_results_source', 'analysis_results', type_='check')
    op.create_check_constraint(
        'ck_analysis_results_source',
        'analysis_results',
        "source IN ('trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only', 'extra_match', 'repeated_sequence')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_analysis_results_source', 'analysis_results', type_='check')
    op.create_check_constraint(
        'ck_analysis_results_source',
        'analysis_results',
        "source IN ('trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only', 'extra_match')",
    )
    # NOTE: any row already carrying source='repeated_sequence' violates the
    # constraint just restored - same inherent limitation as downgrading any
    # migration after data using the new state has been written.
